import argparse
import gc
import logging

import geopandas as gpd
import xarray as xr

from src.calc.average import (
    load_existing_averages,
    run_yearly_averages,
)
from src.plotting.coastline import get_region_coastline
from src.plotting.spatial_plots import Outline, compute_shared_levels, plot_all_years
from src.utils.paths import (
    FIGURES_DIR,
    INTERM_DATA_DIR,
    PROCESSED_DATA_DIR,
)

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------

YEARS = range(2015, 2024)  # 2015-2023 inclusive
JJA_MONTHS = (6, 7, 8)
N_COLOR_LEVELS = 10
COLORMAP = "RdYlGn"
COUNT_COLORMAP = "magma"
N_COUNT_COLOR_LEVELS = 10

# they shoudl already be clipped before running this, if they are not set to True
RESOLUTION_DIR_TEMPLATES = {
    "1km": "SMAP_1km_{region}",
    "400m": "SMAP_400m_{region}",
}
RESOLUTION_NEEDS_CLIP = {
    "1km": False,
    "400m": False,
}


def output_raster_name(resolution: str, region: str, year: int) -> str:
    if resolution == "1km":
        return f"{region}_NSIDC-0779_EASE2_G1km_SMAP_SM_DS_JJA_avg_{year}.tif"
    return f"smap_sm_400m_{region}_JJA_avg_{year}.tif"


def output_count_raster_name(resolution: str, region: str, year: int) -> str:
    if resolution == "1km":
        return f"{region}_NSIDC-0779_EASE2_G1km_SMAP_SM_DS_JJA_count_{year}.tif"
    return f"smap_sm_400m_{region}_JJA_count_{year}.tif"


def output_figure_name(region: str, year: int) -> str:
    return f"{region}_JJA_avg_{year}.png"


def output_count_figure_name(region: str, year: int) -> str:
    return f"{region}_JJA_count_{year}.png"


def main():
    parser = argparse.ArgumentParser(
        description="Calculate and plot yearly averages from 2015 to 2023"
    )
    parser.add_argument(
        "--resolutions",
        nargs="+",
        default=["400m", "1km"],
        choices=["400m", "1km"],
        help="List of resolutions to process (e.g. 400m 1km)",
    )
    parser.add_argument(
        "--regions",
        nargs="+",
        default=["hokkaido", "kushiro"],
        choices=["hokkaido", "kushiro"],
        help="List of regions to clip data to (e.g. hokkaido)",
    )
    parser.add_argument(
        "--calcavg",
        nargs="+",
        default=["yearly", "total"],
        choices=["yearly", "total"],
        help="List of averages to calculate",
    )
    parser.add_argument(
            "--plot",
            nargs="+",
            default=["yearly", "total"],
            choices=["yearly", "total"],
            help="List of averages to plot",
        )
    parser.add_argument(
        "--plot-counts",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Also plot, per pixel, how many samples (days x bands) went into each yearly average",
    )
    args = parser.parse_args()

    # Load shapefiles
    shapefile_dir = INTERM_DATA_DIR / "shapefiles"
    region_file_map = {
        "hokkaido": shapefile_dir / "hokkaido_shape.shp",
        "kushiro": shapefile_dir / "kushiro_shape.shp",
    }
    for region in args.regions:
        shp_path = region_file_map[region]
        if not shp_path.exists():
            raise FileNotFoundError(f"Shapefile not found at: {shp_path}")

    selected_regions = {
        region: gpd.read_file(region_file_map[region]) for region in args.regions
    }

    # Real coastline (Natural Earth), clipped around Hokkaido, drawn on
    # every plot as a geographic reference. Fetched once and reused.
    coastline_gdf = None
    if "hokkaido" in selected_regions and args.plot:
        coastline_gdf = get_region_coastline(selected_regions["hokkaido"])

    for resolution in args.resolutions:
        proc_dir = PROCESSED_DATA_DIR / "yearly_avg" / resolution
        fig_dir = FIGURES_DIR / "yearly_avg" / resolution

        all_region_data: dict[str, dict[int, xr.Dataset]] = {}

        for region in args.regions:
            data_dir = INTERM_DATA_DIR / RESOLUTION_DIR_TEMPLATES[resolution].format(
                region=region
            )
            clip_gdf = (
                selected_regions[region] if RESOLUTION_NEEDS_CLIP[resolution] else None
            )

            if not data_dir.exists():
                logger.warning("Directory not found, skipping: %s", data_dir)
                continue

            if "yearly" in args.calcavg:
                yearly_data = run_yearly_averages(
                    directory=data_dir,
                    resolution=resolution,
                    region=region,
                    years=YEARS,
                    output_dir=proc_dir,
                    output_name_fn=output_raster_name,
                    count_name_fn=output_count_raster_name,
                    clip_gdf=clip_gdf,
                    months=JJA_MONTHS,
                )
            elif "yearly" in args.plot:
                yearly_data = load_existing_averages(
                    output_dir=proc_dir,
                    resolution=resolution,
                    region=region,
                    years=YEARS,
                    output_name_fn=output_raster_name,
                    count_name_fn=output_count_raster_name,
                )
                
            if "total" in args.calcavg:
                # calculate the total JJA average across all years

            elif "total" in args.plot:
                # plot the total JJA average 

            yearly_region_data[region] = yearly_data
            total_region_data[region] = total_data
            gc.collect()

        if args.plot:
            mean_by_region = {
                region: {year: ds["mean"] for year, ds in region_data.items()}
                for region, region_data in all_region_data.items()
            }
            combined = [
                da
                for region_data in mean_by_region.values()
                for da in region_data.values()
            ]
            if not combined:
                logger.warning("Nothing to plot for resolution=%s", resolution)
                continue

            # Shared, discretized color scale across every region/year
            # plotted for this resolution.
            levels = compute_shared_levels(
                combined, n_levels=N_COLOR_LEVELS, round_to=0.1
            )

            if args.plot_counts:
                count_by_region = {
                    region: {
                        year: ds["count"]
                        for year, ds in region_data.items()
                        if "count" in ds
                    }
                    for region, region_data in all_region_data.items()
                }
                combined_counts = [
                    da
                    for region_data in count_by_region.values()
                    for da in region_data.values()
                ]
                count_levels = (
                    compute_shared_levels(
                        combined_counts, n_levels=N_COUNT_COLOR_LEVELS, round_to=10
                    )
                    if combined_counts
                    else None
                )
                if count_levels is None:
                    logger.warning(
                        "No count data available to plot for resolution=%s "
                        "(re-run with --calcavg, or make sure saved *_count_*.tif files exist)",
                        resolution,
                    )

            for region in all_region_data:
                outlines = []
                if coastline_gdf is not None and not coastline_gdf.empty:
                    outlines.append(
                        Outline(
                            coastline_gdf,
                            color="black",
                            linewidth=1.0,
                            label="Coastline",
                        )
                    )
                # On the Hokkaido plot specifically, also draw the
                # Kushiro sub-region border.
                if region == "hokkaido" and "kushiro" in selected_regions:
                    outlines.append(
                        Outline(
                            selected_regions["kushiro"],
                            color="blue",
                            linewidth=1.5,
                            label="Kushiro Basin",
                        )
                    )

                plot_all_years(
                    yearly_data=mean_by_region[region],
                    region=region,
                    output_dir=fig_dir / region,
                    levels=levels,
                    cmap=COLORMAP,
                    outlines=outlines,
                    output_name_fn=output_figure_name,
                )

                if args.plot_counts and count_levels is not None:
                    plot_all_years(
                        yearly_data=count_by_region[region],
                        region=region,
                        output_dir=fig_dir / region,
                        levels=count_levels,
                        cmap=COUNT_COLORMAP,
                        outlines=outlines,
                        output_name_fn=output_count_figure_name,
                    )


if __name__ == "__main__":
    main()
