"""Functions for computing and saving per-pixel yearly (JJA) averages
from stacks of daily SMAP rasters.

Two filename conventions are supported:

- 1km:  "hokkaido_NSIDC-0779_EASE2_G1km_SMAP_SM_DS_20150603.tif"
        (region prefix + full YYYYMMDD date, one directory per region)
- 400m: "smap_sm_400m_2015091.tif"
        (no region in the name; YYYY + DOY (day-of-year); assumed to
        live in a single directory and be clipped to a region using a
        shapefile, since the filename carries no region info)
"""

from __future__ import annotations

import gc
import logging
import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from pathlib import Path

import geopandas as gpd
import pandas as pd
import rioxarray  # noqa: F401  (registers the .rio accessor)  # noqa: F401  (registers the rio accessor on xarray objects)
import xarray as xr

from src.utils.paths import INTERM_DATA_DIR, PROCESSED_DATA_DIR

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Filename parsing
# --------------------------------------------------------------------------

_1KM_PATTERN = re.compile(
    r"^(?P<region>[a-zA-Z]+)_NSIDC-0779_EASE2_G1km_SMAP_SM_DS_(?P<date>\d{8})\.tif$"
)
_400M_PATTERN = re.compile(r"^smap_sm_400m_(?P<year>\d{4})(?P<doy>\d{3})\.tif$")


def parse_date_from_filename(filename: str, resolution: str) -> date | None:
    """Extract the acquisition date encoded in a SMAP filename.

    Returns None if the filename doesn't match the expected pattern for
    the given resolution (so unrelated files in the same directory are
    silently skipped rather than raising).
    """
    if resolution == "1km":
        m = _1KM_PATTERN.match(filename)
        if not m:
            return None
        return datetime.strptime(m.group("date"), "%Y%m%d").date()

    if resolution == "400m":
        m = _400M_PATTERN.match(filename)
        if not m:
            return None
        year = int(m.group("year"))
        doy = int(m.group("doy"))
        return (datetime(year, 1, 1) + timedelta(days=doy - 1)).date()

    raise ValueError(f"Unknown resolution: {resolution!r}")


# --------------------------------------------------------------------------
# File selection
# --------------------------------------------------------------------------


def list_jja_files(
    directory: Path,
    resolution: str,
    year: int,
    months: tuple[int, ...] = (6, 7, 8),
) -> list[Path]:
    """List files in `directory` that fall within `months` of `year`."""
    matched = []
    for f in sorted(directory.glob("*.tif")):
        d = parse_date_from_filename(f.name, resolution)
        if d is not None and d.year == year and d.month in months:
            matched.append(f)
    return matched


# --------------------------------------------------------------------------
# Averaging
# --------------------------------------------------------------------------


def calculate_yearly_jja_average(
    directory: Path,
    resolution: str,
    year: int,
    clip_gdf: gpd.GeoDataFrame | None = None,
    months: tuple[int, ...] = (6, 7, 8),
) -> xr.Dataset | None:
    """Compute the per-pixel JJA mean for a single year, along with a
    per-pixel count of how many samples (non-nodata days/bands) went
    into that mean.

    Returns an `xr.Dataset` with two variables, "mean" and "count", or
    None if no files were found for that year/season.

    If `clip_gdf` is given, each raster is clipped to that geometry
    before averaging (needed for the 400m data, which isn't already
    split by region).

    The 1km rasters have 2 bands (AM/PM overpasses). Rather than
    squeezing/dropping a band, every band is kept and treated as its
    own sample in the average alongside every day, so a file with 2
    bands contributes 2 observations, not 1. The "count" pixel value
    reflects this too - a pixel with valid data on every day/band gets
    n_files * n_bands, but nodata pixels on any given day/band (e.g.
    at a clip edge, or masked out) get a lower count than a neighboring
    pixel with full coverage.
    """
    files = list_jja_files(directory, resolution, year, months=months)
    if not files:
        logger.warning("No %s files found for %d in %s", resolution, year, directory)
        return None

    arrays = []
    for f in files:
        da = rioxarray.open_rasterio(f, masked=True)
        if clip_gdf is not None:
            da = da.rio.clip(clip_gdf.geometry, clip_gdf.crs, drop=True)
        arrays.append(da)

    # Concat along a fresh "time" dim (one per file); "band" (AM/PM,
    # or just 1 band for 400m) is preserved on each array.
    stacked = xr.concat(arrays, dim="time")
    n_bands = stacked.sizes["band"]

    # Average over every band of every day together, e.g. for 1km:
    # n_files * 2 samples per pixel instead of n_files.
    sample_dim = stacked.stack(sample=("time", "band"))
    yearly_avg = sample_dim.mean(dim="sample", skipna=True)
    yearly_count = sample_dim.count(dim="sample").astype("int32")

    result = xr.Dataset({"mean": yearly_avg, "count": yearly_count})

    # Drop leftover multiindex/scalar coords from the stack (band,
    # time, sample) so only the spatial coords remain before writing.
    keep = set(yearly_avg.dims) | {"spatial_ref"}
    drop_coords = [c for c in result.coords if c not in keep]
    result = result.drop_vars(drop_coords, errors="ignore")

    result.rio.write_crs(arrays[0].rio.crs, inplace=True)
    for attrs in (result.attrs, result["mean"].attrs, result["count"].attrs):
        attrs["year"] = year
        attrs["resolution"] = resolution
        attrs["n_days_averaged"] = len(files)
        attrs["n_bands_per_day"] = n_bands
        attrs["n_samples_averaged"] = len(files) * n_bands

    del stacked, sample_dim, arrays
    gc.collect()

    return result


# --------------------------------------------------------------------------
# I/O
# --------------------------------------------------------------------------


def save_raster(data_array: xr.DataArray, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data_array.rio.to_raster(output_path)
    logger.info("Saved %s", output_path)


def save_yearly_result(
    result: xr.Dataset,
    mean_path: Path,
    count_path: Path | None = None,
) -> None:
    """Save a `calculate_yearly_jja_average` result. `count_path` is
    optional - pass None to skip saving the datapoint-count raster."""
    save_raster(result["mean"], mean_path)
    if count_path is not None:
        save_raster(result["count"], count_path)


def load_existing_averages(
    output_dir: Path,
    resolution: str,
    region: str,
    years: Iterable[int],
    output_name_fn,
    count_name_fn=None,
) -> dict[int, xr.Dataset]:
    """Load previously-saved yearly average (and, if `count_name_fn` is
    given, datapoint-count) GeoTIFFs - used when --no-calcavg is passed
    and we just want to (re)plot."""
    data = {}
    for year in years:
        mean_path = output_dir / output_name_fn(resolution, region, year)
        if not mean_path.exists():
            logger.warning("No saved average found, skipping: %s", mean_path)
            continue
        mean_da = rioxarray.open_rasterio(mean_path, masked=True).squeeze(
            "band", drop=True
        )

        count_da = None
        if count_name_fn is not None:
            count_path = output_dir / count_name_fn(resolution, region, year)
            if count_path.exists():
                count_da = rioxarray.open_rasterio(count_path, masked=True).squeeze(
                    "band", drop=True
                )
            else:
                logger.warning("No saved count raster found, skipping: %s", count_path)

        data_vars = {"mean": mean_da}
        if count_da is not None:
            data_vars["count"] = count_da
        data[year] = xr.Dataset(data_vars)
    return data


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def run_yearly_averages(
    directory: Path,
    resolution: str,
    region: str,
    years: Iterable[int],
    output_dir: Path,
    output_name_fn,
    count_name_fn=None,
    clip_gdf: gpd.GeoDataFrame | None = None,
    months: tuple[int, ...] = (6, 7, 8),
) -> dict[int, xr.Dataset]:
    """Compute and save the JJA yearly average (and, if `count_name_fn`
    is given, a per-pixel datapoint-count raster) for every year in
    `years`.

    Returns a {year: Dataset} dict (each with "mean" and "count" data
    variables) so the caller can plot immediately without re-reading
    the files back off disk.
    """
    results = {}
    for year in years:
        result = calculate_yearly_jja_average(
            directory, resolution, year, clip_gdf=clip_gdf, months=months
        )
        if result is None:
            continue
        mean_path = output_dir / output_name_fn(resolution, region, year)
        count_path = (
            output_dir / count_name_fn(resolution, region, year)
            if count_name_fn
            else None
        )
        save_yearly_result(result, mean_path, count_path)
        results[year] = result
        gc.collect()
    return results


# --------------------------------------------------------------------------
# Daily spatial-mean time series (every day/band of the year, one scalar
# each) - feeds the dot-plot time series. Distinct from the JJA per-pixel
# raster averages above: each band is its own timestep here rather than
# being averaged together, and the whole year is used, not just JJA.
# --------------------------------------------------------------------------

BAND_TIMES = {1: "06:00", 2: "18:00"}  # band 1 = AM overpass, band 2 = PM overpass

TS_COLUMN_DATETIME = "datetime"
TS_COLUMN_VALUE = "soil_moisture"

# 400m, since 1km is already split into per-region directories)
REGION_SHAPEFILES = {
    "hokkaido": INTERM_DATA_DIR / "shapefiles" / "hokkaido.shp",
    "kushiro": INTERM_DATA_DIR / "shapefiles" / "kushiro.shp",
}


def list_year_files(directory: Path, resolution: str, year: int) -> list[Path]:
    """List every file in `directory` for `resolution` that falls in `year` (all 12 months)."""
    return list_jja_files(directory, resolution, year, months=tuple(range(1, 13)))


def calculate_daily_spatial_means(
    directory: Path,
    resolution: str,
    year: int,
    clip_gdf: gpd.GeoDataFrame | None = None,
) -> pd.DataFrame:
    """Compute one spatial-mean scalar per band per day for `year`.

    Each band is its own timestep (1km: AM + PM -> 2 rows/day; 400m:
    single band -> 1 row/day). If `clip_gdf` is given (needed for 400m,
    which isn't already split by region), each raster is clipped first.
    """
    files = list_year_files(directory, resolution, year)
    if not files:
        logger.warning("No %s files found for %d in %s", resolution, year, directory)
        return pd.DataFrame(columns=[TS_COLUMN_DATETIME, TS_COLUMN_VALUE])

    records = []
    for f in files:
        file_date = parse_date_from_filename(f.name, resolution)
        da = rioxarray.open_rasterio(f, masked=True)
        if clip_gdf is not None:
            da = da.rio.clip(clip_gdf.geometry, clip_gdf.crs, drop=True)

        for band in da["band"].values:
            band = int(band)
            band_mean = float(da.sel(band=band).mean(skipna=True).item())
            timestamp = pd.Timestamp(
                f"{file_date:%Y-%m-%d} {BAND_TIMES.get(band, '00:00')}"
            )
            records.append({TS_COLUMN_DATETIME: timestamp, TS_COLUMN_VALUE: band_mean})

        da.close()

    gc.collect()

    return (
        pd.DataFrame.from_records(records)
        .sort_values(TS_COLUMN_DATETIME)
        .reset_index(drop=True)
    )


def save_daily_averages(df: pd.DataFrame, csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)
    logger.info("Saved %s (%d timesteps)", csv_path, len(df))


def load_existing_daily_averages(csv_path: Path) -> pd.DataFrame | None:
    if not csv_path.exists():
        logger.warning("No saved daily averages found, skipping: %s", csv_path)
        return None
    return pd.read_csv(csv_path, parse_dates=[TS_COLUMN_DATETIME])


def run_daily_spatial_averages(
    directory: Path,
    resolution: str,
    region: str,
    years: Iterable[int],
    output_dir: Path,
    csv_name_fn,
    clip_gdf: gpd.GeoDataFrame | None = None,
) -> dict[int, pd.DataFrame]:
    """Compute and save the daily spatial-mean time series for every year in `years`."""
    results = {}
    for year in years:
        df = calculate_daily_spatial_means(
            directory, resolution, year, clip_gdf=clip_gdf
        )
        if df.empty:
            continue
        csv_path = output_dir / csv_name_fn(resolution, region, year)
        save_daily_averages(df, csv_path)
        results[year] = df
        gc.collect()
    return results
