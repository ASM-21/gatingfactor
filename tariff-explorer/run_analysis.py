"""Regenerate every tariff-explorer artifact.

    python run_analysis.py

Revenue neutrality is enforced **within customer class**, since real tariffs
are class-specific and scaling one structure across residential and commercial
together produces a cross-subsidy that is an artifact of the modeling rather
than a property of the rate design.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from shared import io, paths, plotting  # noqa: E402
from texplorer import archetypes as ar, tariffs as tf  # noqa: E402

TRACK = "tariff-explorer"
SUBTITLE = (
    "gatingfactor / tariff-explorer. Load shapes are synthetic parameterized archetypes "
    "(ResStock unreachable). Tariff levels are representative, not filed rates."
)

CLASSES = {
    "residential": ("all_electric", "ev_home", "solar_home"),
    "commercial": ("commercial_daytime", "commercial_flat"),
}


def within_class_revenue_neutral(archetypes: dict) -> pd.DataFrame:
    frames = []
    for cls, keys in CLASSES.items():
        subset = {k: archetypes[k] for k in keys}
        df = ar.revenue_neutral_comparison(subset)
        df["customer_class"] = cls
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def fig_bill_change(rn: pd.DataFrame) -> Path:
    pivot = (
        rn.pivot(index="archetype", columns="tariff", values="change_pct")
        .drop(columns=["flat"])
        .sort_index()
    )
    lf = rn.groupby("archetype").load_factor.first()
    pivot = pivot.loc[lf.sort_values().index]

    fig, ax = plt.subplots(figsize=(10, 6))
    data = pivot.to_numpy()
    lim = np.abs(data).max()
    im = ax.imshow(data, cmap="RdBu_r", vmin=-lim, vmax=lim, aspect="auto")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns, rotation=20, ha="right")
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([f"{k}\nLF={lf[k]:.2f}" for k in pivot.index])
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            ax.text(j, i, f"{data[i, j]:+.0f}%", ha="center", va="center", fontsize=9)
    ax.grid(False)
    fig.colorbar(im, ax=ax, label="Bill change vs flat rate (%)")
    ax.set_title("Who wins and loses, at equal revenue within customer class")
    return plotting.finish(fig, paths.output(TRACK, "bill_change_heatmap.png"), SUBTITLE)


def fig_load_factor(rn: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(9, 6))
    for tariff, marker in (("demand", "o"), ("tou", "s"), ("hybrid_tou_demand", "^")):
        sub = rn[rn.tariff == tariff]
        ax.scatter(sub.load_factor, sub.change_pct, s=90, marker=marker, label=tariff)
    for _, row in rn[rn.tariff == "demand"].iterrows():
        ax.annotate(row.archetype, (row.load_factor, row.change_pct),
                    fontsize=8, xytext=(6, 4), textcoords="offset points")
    ax.axhline(0, color=plotting.COLOR_NEUTRAL, lw=1)
    ax.set_xlabel("Load factor (average demand / peak demand)")
    ax.set_ylabel("Bill change vs flat rate (%)")
    ax.set_title("Demand charges track load factor; TOU tracks timing instead")
    ax.legend()
    return plotting.finish(fig, paths.output(TRACK, "load_factor_vs_impact.png"), SUBTITLE)


def fig_shapes(archetypes: dict) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    ts = pd.DatetimeIndex(next(iter(archetypes.values())).timestamps)
    for key, arch in archetypes.items():
        ax = axes[0] if key in CLASSES["residential"] else axes[1]
        avg = pd.Series(arch.net, index=ts).groupby(ts.hour).mean()
        ax.plot(avg.index, avg.to_numpy(), "-o", ms=3, label=key)
    for ax, title in zip(axes, ("Residential", "Commercial")):
        ax.set_xlabel("Hour of day")
        ax.set_title(title)
        ax.legend(fontsize=8)
        ax.axhline(0, color=plotting.COLOR_NEUTRAL, lw=0.8)
    axes[0].set_ylabel("Mean net grid draw (kWh)")
    fig.suptitle("Archetype net load shapes, annual average day")
    return plotting.finish(fig, paths.output(TRACK, "archetype_shapes.png"), SUBTITLE)


def fig_composition(matrix: pd.DataFrame) -> Path:
    res = matrix[matrix.archetype.isin(CLASSES["residential"])]
    fig, ax = plt.subplots(figsize=(11, 6))
    keys = res.groupby(["archetype", "tariff"]).first().index
    labels = [f"{a}\n{t}" for a, t in keys]
    energy = res.groupby(["archetype", "tariff"]).energy.first().to_numpy()
    demand = res.groupby(["archetype", "tariff"]).demand.first().to_numpy()
    fixed = res.groupby(["archetype", "tariff"]).fixed.first().to_numpy()
    credit = -res.groupby(["archetype", "tariff"]).export_credit.first().to_numpy()
    x = range(len(labels))
    ax.bar(x, energy, label="energy")
    ax.bar(x, demand, bottom=energy, label="demand")
    ax.bar(x, fixed, bottom=energy + demand, label="fixed")
    ax.bar(x, credit, label="export credit", color=plotting.COLOR_OK)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=90, fontsize=7)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("Annual $")
    ax.set_title("Bill composition, residential archetypes at as-written rates")
    ax.legend()
    return plotting.finish(fig, paths.output(TRACK, "bill_composition.png"), SUBTITLE)


def main() -> None:
    plotting.apply_theme()
    print("[archetypes]")
    archetypes = ar.build_archetypes(2021)
    summary = pd.DataFrame(
        [
            {
                "archetype": a.key,
                "label": a.label,
                "annual_kwh": a.annual_kwh,
                "net_annual_kwh": a.net_annual_kwh,
                "peak_kw": a.peak_kw,
                "load_factor": a.load_factor,
            }
            for a in archetypes.values()
        ]
    )
    io.write_processed(summary, TRACK, "archetype_summary")
    print(summary.round(3).to_string(index=False))

    print("\n[bills] as-written rates")
    matrix = ar.bill_matrix(archetypes)
    io.write_processed(matrix, TRACK, "bill_matrix")
    matrix.to_csv(paths.output(TRACK, "bill_matrix.csv"), index=False)

    print("[revenue-neutral] within customer class")
    rn = within_class_revenue_neutral(archetypes)
    io.write_processed(rn, TRACK, "revenue_neutral")
    rn.to_csv(paths.output(TRACK, "revenue_neutral.csv"), index=False)
    pivot = rn.pivot(index="archetype", columns="tariff", values="change_pct")
    lf = rn.groupby("archetype").load_factor.first()
    pivot["load_factor"] = lf
    print(pivot.round(1).sort_values("load_factor").to_string())

    d = rn[rn.tariff == "demand"]
    r = np.corrcoef(d.load_factor, d.change_pct)[0, 1]
    print(f"\n  corr(load factor, demand-charge bill change) r = {r:.2f}")

    print("\n[figures]")
    for p in (
        fig_bill_change(rn),
        fig_load_factor(rn),
        fig_shapes(archetypes),
        fig_composition(matrix),
    ):
        print("   ", p.relative_to(paths.REPO_ROOT))


if __name__ == "__main__":
    main()
