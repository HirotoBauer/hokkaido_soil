"""Spatial plotting helpers for yearly average rasters.

One figure per year; a shared, discretized (BoundaryNorm) colorbar
across every figure passed through the same `plot_all_years` call so
years/regions/resolutions are visually comparable.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import NamedTuple

import geopandas as gpd
import matplotlib.colors as mcolors
import matplotlib.lines as mlines
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

logger = logging.getLogger(__name__)

BACKGROUND_COLOR = "lightgrey"


class Outline(NamedTuple):
    """A boundary to draw on top of the raster, e.g. a coastline or a
    sub-region border."""

    gdf: gpd.GeoDataFrame
    color: str = "black"
    linewidth: float = 1.2
    label: str | None = None


def compute_shared_levels(
    data_arrays: list[xr.DataArray],
    n_levels: int = 10,
    round_to: float | None = None,
) -> np.ndarray:
    """Discretized color levels spanning the min/max of every array
    passed in, so all resulting plots share one color scale."""
    vmin = min(float(da.min(skipna=True)) for da in data_arrays)
    vmax = max(float(da.max(skipna=True)) for da in data_arrays)

    if round_to is not None and round_to > 0:
        vmin = 0
        vmax = math.ceil(vmax / round_to) * round_to

    return np.linspace(vmin, vmax, n_levels + 1)


def plot_yearly_spatial(
    data_array: xr.DataArray,
    year: int,
    region: str,
    levels: np.ndarray,
    cmap: str,
    outlines: list[Outline] | None = None,
    output_path: Path | None = None,
) -> plt.Figure:
    """Plot a single year's spatial average with a discretized colorbar
    on a light-grey background, optionally drawing one or more
    boundaries on top (e.g. Hokkaido's shoreline, the Kushiro border)."""
    norm = mcolors.BoundaryNorm(levels, ncolors=256)
    dfont = 16

    if "hokkaido" in region.lower():
        fig, ax = plt.subplots(figsize=(12, 8))
    elif "kushiro" in region.lower():
        fig, ax = plt.subplots(figsize=(9, 9))
    else:
        fig, ax = plt.subplots(figsize=(12, 8))

    ax.set_facecolor(BACKGROUND_COLOR)

    im = data_array.plot(ax=ax, cmap=cmap, norm=norm, add_colorbar=False)
    cbar = fig.colorbar(
        im,
        ax=ax,
        boundaries=levels,
        ticks=levels,
        spacing="proportional",
        shrink=0.81,
        aspect=20,
        pad=0.02,
    )
    if output_path is not None and "count" in output_path.name.lower():
        cbar_label = "Sample Count"
    elif output_path is not None and "avg" in output_path.name.lower():
        cbar_label = "Soil Moisture (m³/m³)"
    else:
        cbar_label = data_array.attrs.get("long_name", "Value")

    cbar.set_label(cbar_label, fontsize=dfont + 2)
    cbar.ax.tick_params(labelsize=dfont - 1)

    if outlines:
        raster_crs = data_array.rio.crs
        image_zorder = im.get_zorder() if hasattr(im, "get_zorder") else 1
        outline_zorder = image_zorder + 1

        legend_handles = []
        for outline in outlines:
            gdf = outline.gdf
            if gdf.empty:
                logger.warning("Outline '%s' has no geometry - skipping", outline.label)
                continue
            if raster_crs is not None and gdf.crs is not None:
                gdf = gdf.to_crs(raster_crs)
            logger.info(
                "Drawing outline '%s': %d feature(s), bounds=%s",
                outline.label,
                len(gdf),
                tuple(gdf.total_bounds),
            )

            geom_types = set(gdf.geometry.geom_type)
            if geom_types <= {"LineString", "MultiLineString"}:
                gdf.plot(
                    ax=ax,
                    color=outline.color,
                    linewidth=outline.linewidth,
                    zorder=outline_zorder,
                )
            else:
                gdf.boundary.plot(
                    ax=ax,
                    edgecolor=outline.color,
                    linewidth=outline.linewidth,
                    zorder=outline_zorder,
                )
            if outline.label:
                legend_handles.append(
                    mlines.Line2D(
                        [],
                        [],
                        color=outline.color,
                        linewidth=outline.linewidth,
                        label=outline.label,
                    )
                )

        if legend_handles:
            ax.legend(handles=legend_handles, loc="lower right", fontsize=dfont)

    ax.set_title(f"{region.capitalize()} JJA Average — {year}", fontsize=dfont + 4)
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.set_xticks([])
    ax.set_yticks([])
    fig.tight_layout()

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=200, facecolor=fig.get_facecolor())
        logger.info("Saved figure to %s", output_path)

    return fig


def plot_all_years(
    yearly_data: dict[int, xr.DataArray],
    region: str,
    output_dir: Path,
    levels: np.ndarray,
    cmap: str = "viridis",
    outlines: list[Outline] | None = None,
    output_name_fn=None,
) -> None:
    """Plot every year in `yearly_data` for one region, using
    pre-computed `levels` so the colorbar matches whatever else was
    plotted with the same `levels` array."""
    if not yearly_data:
        logger.warning("No data provided to plot for region=%s", region)
        return

    for year, da in sorted(yearly_data.items()):
        out_path = output_dir / output_name_fn(region, year) if output_name_fn else None
        fig = plot_yearly_spatial(
            da,
            year=year,
            region=region,
            levels=levels,
            cmap=cmap,
            outlines=outlines,
            output_path=out_path,
        )
        plt.close(fig)
