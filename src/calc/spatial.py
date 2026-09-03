# src/processing/spatial.py
from pathlib import Path

import geopandas as gpd
import rioxarray


def clip_raster(
    raster_path: Path,
    gdf: gpd.GeoDataFrame,
    output_path: Path,
    drop: bool = True,
) -> None:
    """Opens a raster, matches CRS to the vector boundary, clips, and saves the result."""
    with rioxarray.open_rasterio(raster_path) as da:
        # Reproject vector only if CRS does not match
        target_gdf = gdf.to_crs(da.rio.crs) if gdf.crs != da.rio.crs else gdf

        clipped = da.rio.clip(target_gdf.geometry, target_gdf.crs, drop=drop)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        clipped.rio.to_raster(output_path)
