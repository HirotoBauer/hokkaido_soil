"""Real-world coastline geometry for use as a shoreline outline on plots.

Uses Natural Earth data (bundled with cartopy's shapereader, downloaded
and cached on first use) rather than an analysis-region shapefile, since
things like `hokkaido_shape.shp` are study-area boundaries, not the
actual coastline.
"""

from __future__ import annotations

import logging

import cartopy.io.shapereader as shpreader
import geopandas as gpd
from shapely.geometry import box

logger = logging.getLogger(__name__)


def get_coastline_gdf(resolution: str = "10m") -> gpd.GeoDataFrame:
    """Load the global Natural Earth coastline as a GeoDataFrame (EPSG:4326).

    `resolution` is one of "10m" (most detailed), "50m", or "110m", per
    Natural Earth's naming. Requires internet access the first time it's
    called for a given resolution; cartopy caches the download locally
    after that.
    """
    path = shpreader.natural_earth(
        resolution=resolution, category="physical", name="coastline"
    )
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs(4326)
    return gdf


def clip_coastline_to_region(
    coastline_gdf: gpd.GeoDataFrame,
    region_gdf: gpd.GeoDataFrame,
    buffer_deg: float = 0.1,
) -> gpd.GeoDataFrame:
    """Clip a (typically global) coastline GeoDataFrame down to the
    bounding box of `region_gdf`, with a small buffer so the coastline
    isn't cut off right at the region's edge."""
    region_wgs84 = region_gdf.to_crs(4326)
    minx, miny, maxx, maxy = region_wgs84.total_bounds
    bbox = box(
        minx - buffer_deg, miny - buffer_deg, maxx + buffer_deg, maxy + buffer_deg
    )

    coastline_wgs84 = (
        coastline_gdf
        if coastline_gdf.crs.to_epsg() == 4326
        else coastline_gdf.to_crs(4326)
    )
    clipped = gpd.clip(coastline_wgs84, bbox)
    logger.info(
        "Coastline clip: region bbox=%s -> %d feature(s) (from %d global)",
        (minx, miny, maxx, maxy),
        len(clipped),
        len(coastline_wgs84),
    )
    if clipped.empty:
        logger.warning(
            "Coastline clip returned no geometry for bbox=%s. Check that the "
            "region shapefile's extent is actually coastal, or increase buffer_deg.",
            (minx, miny, maxx, maxy),
        )
    return clipped


def get_region_coastline(
    region_gdf: gpd.GeoDataFrame, resolution: str = "10m", buffer_deg: float = 0.1
) -> gpd.GeoDataFrame:
    """Convenience wrapper: fetch + clip in one call."""
    coastline = get_coastline_gdf(resolution=resolution)
    return clip_coastline_to_region(coastline, region_gdf, buffer_deg=buffer_deg)
