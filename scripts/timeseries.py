import argparse
import gc
import logging

import geopandas as gpd
import pandas as pd

from src.calc.average import (
    REGION_SHAPEFILES,
    load_existing_daily_averages,
    run_daily_spatial_averages,
)
from src.plotting.timeseries import compute_shared_ranges, plot_dotplot
from src.utils.paths import FIGURES_DIR, INTERM_DATA_DIR, PROCESSED_DATA_DIR

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

# CONFIG

YEARS = range(2015, 2024)  # 2015-2023 inclusive


def _csv_name(resolution: str, region: str, year: int) -> str:
    return f"{resolution}/{region}/{resolution}_{region}_{year}.csv"


def _raw_directory(resolution: str, region: str):
    return INTERM_DATA_DIR / f"SMAP_{resolution}_{region}"


def main():
    parser = argparse.ArgumentParser(
        description="Calculate and plot daily spatial averaged soil mositure from 2015 to 2023"
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
        "--calc",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Re-calcualtes the time series analysis",
    )
    parser.add_argument(
        "--plot",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="plots the time series analysis",
    )
    args = parser.parse_args()

    if args.calc:
        for resolution in args.resolutions:
            for region in args.regions:
                directory = _raw_directory(resolution, region)

                clip_gdf = None
                if resolution == "400m":
                    clip_gdf = gpd.read_file(REGION_SHAPEFILES[region])

                logger.info("Averaging resolution=%s region=%s", resolution, region)
                run_daily_spatial_averages(
                    directory=directory,
                    resolution=resolution,
                    region=region,
                    years=YEARS,
                    output_dir=PROCESSED_DATA_DIR,
                    csv_name_fn=_csv_name,
                    clip_gdf=clip_gdf,
                )

                del clip_gdf
                gc.collect()

    if args.plot:
        for resolution in args.resolutions:
            region_frames = {}
            for region in args.regions:
                frames = [
                    df
                    for year in YEARS
                    if (
                        df := load_existing_daily_averages(
                            PROCESSED_DATA_DIR / _csv_name(resolution, region, year)
                        )
                    )
                    is not None
                ]
                region_frames[region] = (
                    pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
                )

            x_range, y_range = compute_shared_ranges(region_frames)

            for region, df in region_frames.items():
                if df.empty:
                    logger.warning(
                        "No data to plot for resolution=%s region=%s",
                        resolution,
                        region,
                    )
                    continue
                plot_dotplot(
                    resolution,
                    region,
                    df,
                    YEARS,
                    x_range,
                    y_range,
                    FIGURES_DIR / "timeseries" / resolution,
                )

            del region_frames
            gc.collect()


if __name__ == "__main__":
    main()
