"""Shared plotting theme so all six tracks produce visually consistent figures.

Palette is colorblind-safe (blue/orange primary pair rather than red/green) and
every helper here defaults to labeling axes with units, because unlabeled axes
are the single most common defect in engineering charts.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt

mpl.use("Agg")

# Colorblind-safe categorical palette.
PALETTE = [
    "#2B6CB0",  # blue
    "#DD6B20",  # orange
    "#38A169",  # green
    "#805AD5",  # purple
    "#D53F8C",  # magenta
    "#718096",  # slate
]

SEQUENTIAL = "YlOrRd"
DIVERGING = "RdBu_r"

# Semantic colors reused across tracks.
COLOR_VIOLATION = "#C53030"
COLOR_OK = "#38A169"
COLOR_NEUTRAL = "#718096"


def apply_theme() -> None:
    """Install the gatingfactor matplotlib defaults. Idempotent."""
    plt.rcParams.update(
        {
            "figure.figsize": (10, 6),
            "figure.dpi": 150,
            "savefig.dpi": 150,
            "savefig.bbox": "tight",
            "font.size": 11,
            "axes.titlesize": 13,
            "axes.titleweight": "bold",
            "axes.labelsize": 11,
            "axes.grid": True,
            "axes.axisbelow": True,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.prop_cycle": mpl.cycler(color=PALETTE),
            "grid.color": "#E2E8F0",
            "grid.linewidth": 0.8,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
            "legend.frameon": False,
            "figure.titlesize": 15,
        }
    )


def finish(fig, path: Path, subtitle: str | None = None) -> Path:
    """Attach an optional source/caveat line, save, and close the figure."""
    if subtitle:
        fig.text(
            0.005,
            -0.015,
            subtitle,
            fontsize=8,
            color=COLOR_NEUTRAL,
            ha="left",
            va="top",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path


def money(val: float) -> str:
    """Compact currency label for axis ticks and annotations."""
    a = abs(val)
    if a >= 1e9:
        return f"${val / 1e9:.1f}B"
    if a >= 1e6:
        return f"${val / 1e6:.1f}M"
    if a >= 1e3:
        return f"${val / 1e3:.1f}K"
    return f"${val:,.0f}"


apply_theme()
