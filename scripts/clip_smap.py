# scripts/clip_smpa.py
import argparse
import gc
import logging

import geopandas as gpd

from src.data.spatial import clip_raster
from src.utils.paths import INTERM_DATA_DIR, RAW_DATA_DIR

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

import os

os.environ["GDAL_CACHEMAX"] = "5120"  # MB, tune to your machine


def process_smap_clipping(
    resolutions: list[str], regions: dict[str, gpd.GeoDataFrame]
) -> None:
    """Iterates over SMAP resolutions and clips each file to target region boundaries."""
    for res in resolutions:
        sm_dir = RAW_DATA_DIR / f"SMAP_{res}"
        sm_files = sorted(sm_dir.glob("*.tif"))

        if not sm_files:
            logging.warning(f"No GeoTIFFs found in {sm_dir}")
            continue

        logging.info(f"Processing resolution '{res}': found {len(sm_files)} file(s)")

        for sm_f in sm_files:
            for region_name, region_gdf in regions.items():
                out_dir = INTERM_DATA_DIR / f"SMAP_{res}_{region_name}"
                out_file = out_dir / f"{region_name}_{sm_f.name}"

                # Skip recomputation if output file already exists
                if out_file.exists():
                    logging.debug(f"Skipping existing file: {out_file.name}")
                    continue

                clip_raster(
                    raster_path=sm_f, gdf=region_gdf, output_path=out_file, drop=True
                )
                logging.info(f"Saved: {out_file.name} -> {out_dir.name}")
                gc.collect()


def main():
    parser = argparse.ArgumentParser(
        description="Clip SMAP raster data to regional boundaries."
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
    args = parser.parse_args()

    # Load shapefiles
    shapefile_dir = INTERM_DATA_DIR / "shapefiles"
    region_file_map = {
        "hokkaido": shapefile_dir / "hokkaido_shape.shp",
        "kushiro": shapefile_dir / "kushiro_shape.shp",
    }
    selected_regions = {}
    for region in args.regions:
        shp_path = region_file_map[region]
        if not shp_path.exists():
            raise FileNotFoundError(f"Shapefile not found at: {shp_path}")

    selected_regions = {
        region: gpd.read_file(region_file_map[region]) for region in args.regions
    }
    process_smap_clipping(resolutions=args.resolutions, regions=selected_regions)


if __name__ == "__main__":
    main()
