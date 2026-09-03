import logging
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from src.calc.average import TS_COLUMN_DATETIME, TS_COLUMN_VALUE

logger = logging.getLogger(__name__)


def compute_shared_ranges(
    region_frames: dict[str, pd.DataFrame],
) -> tuple[tuple[float, float], tuple[float, float]]:
    """X (day-of-year) and Y (value) ranges shared across all regions for one resolution."""
    non_empty = [df for df in region_frames.values() if df is not None and not df.empty]
    if not non_empty:
        return (1, 365), (0.0, 1.0)

    all_df = pd.concat(non_empty, ignore_index=True)
    days = all_df[TS_COLUMN_DATETIME].dt.dayofyear
    x_range = (days.min(), days.max())
    y_range = (all_df[TS_COLUMN_VALUE].min(), all_df[TS_COLUMN_VALUE].max())
    return x_range, y_range


def plot_dotplot(
    resolution: str,
    region: str,
    df: pd.DataFrame,
    years: range,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    out_dir: Path,
) -> None:
    """Dot plot of soil moisture per timestep, one color per year."""
    fig, ax = plt.subplots(figsize=(11, 5))
    cmap = plt.get_cmap("tab10")

    for i, year in enumerate(years):
        year_df = df[df[TS_COLUMN_DATETIME].dt.year == year]
        if year_df.empty:
            continue
        ax.scatter(
            year_df[TS_COLUMN_DATETIME].dt.dayofyear,
            year_df[TS_COLUMN_VALUE],
            s=10,
            alpha=0.7,
            color=cmap(i % 10),
            label=str(year),
        )

    ax.set_xlim(*x_range)
    ax.set_ylim(*y_range)
    ax.set_xlabel("Day of year")
    ax.set_ylabel("Soil moisture")
    ax.set_title(f"{region.title()} ({resolution}) daily soil moisture, 2015-2023")
    ax.legend(title="Year", bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=8)
    fig.tight_layout()

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{resolution}_{region}_dotplot.png"
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    logger.info("Saved figure to %s", out_path)
