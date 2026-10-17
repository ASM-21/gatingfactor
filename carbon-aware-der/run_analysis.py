"""Regenerate every carbon-aware-der artifact.

    python run_analysis.py --stage annual     # full-year anchors vs baseline
    python run_analysis.py --stage frontier   # weight sweep
    python run_analysis.py --stage figures
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from cader import (  # noqa: E402
    data as cd,
    frontier as cf,
    marginal as cm,
    optimizer as op,
    signal_choice as sc,
)
from shared import io, paths, plotting  # noqa: E402

TRACK = "carbon-aware-der"
YEAR = 2021
SUBTITLE = (
    "gatingfactor / carbon-aware-der. Carbon intensity is real hourly PJM data (CarbonCast, "
    "EIA-derived). Price is a representative TOU structure and household load is synthetic."
)


def fig_carbon_vs_price(df: pd.DataFrame) -> Path:
    """The central diagnostic: does the price signal point the same way as carbon?"""
    hourly = df.groupby("hour").agg(
        carbon=("carbon_g_per_kwh", "mean"), price=("price_per_kwh", "mean")
    )
    fig, ax1 = plt.subplots(figsize=(10, 6))
    ax2 = ax1.twinx()
    ax1.plot(hourly.index, hourly.carbon, "-o", color=plotting.PALETTE[0], label="carbon intensity")
    ax2.plot(hourly.index, hourly.price, "-s", color=plotting.PALETTE[1], label="TOU price")
    ax1.set_xlabel("Hour of day (Eastern)")
    ax1.set_ylabel("Mean carbon intensity (gCO2/kWh)", color=plotting.PALETTE[0])
    ax2.set_ylabel("Mean price ($/kWh)", color=plotting.PALETTE[1])
    ax2.grid(False)
    r = np.corrcoef(df.carbon_g_per_kwh, df.price_per_kwh)[0, 1]
    ax1.set_title(f"PJM carbon intensity vs TOU price shape (hourly r = {r:.2f})")
    return plotting.finish(fig, paths.output(TRACK, "carbon_vs_price.png"), SUBTITLE)


def fig_frontier(front: pd.DataFrame) -> Path:
    agg = front.groupby("weight_cost").agg(cost=("cost", "sum"), carbon=("carbon_kg", "sum"))
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.plot(agg.carbon, agg.cost, "-o", color=plotting.PALETTE[0])
    for w, row in agg.iterrows():
        ax.annotate(f"w={w:g}", (row.carbon, row.cost), fontsize=8,
                    xytext=(5, 4), textcoords="offset points")
    ax.set_xlabel("Total CO2 over sampled days (kg)")
    ax.set_ylabel("Total cost over sampled days ($)")
    ax.set_title("Cost/carbon tradeoff frontier, weight w on the cost objective")
    return plotting.finish(fig, paths.output(TRACK, "tradeoff_frontier.png"), SUBTITLE)


def fig_monthly(annual: pd.DataFrame) -> Path:
    m = annual.groupby("month").sum(numeric_only=True)
    carbon_saving = 100 * (m.unmanaged_carbon - m.carbon_opt_carbon) / m.unmanaged_carbon
    cost_saving = 100 * (m.unmanaged_cost - m.cost_opt_cost) / m.unmanaged_cost
    fig, ax = plt.subplots(figsize=(10, 6))
    width = 0.4
    ax.bar([i - width / 2 for i in m.index], cost_saving, width, label="cost saving (cost-optimal)")
    ax.bar([i + width / 2 for i in m.index], carbon_saving, width,
           label="carbon saving (carbon-optimal)")
    ax.set_xticks(list(m.index))
    ax.set_xlabel("Month")
    ax.set_ylabel("Reduction vs unmanaged (%)")
    ax.set_title("Cost savings dwarf carbon savings in every month")
    ax.legend()
    return plotting.finish(fig, paths.output(TRACK, "monthly_savings.png"), SUBTITLE)


def fig_example_day(df: pd.DataFrame) -> Path:
    block = cd.daily_horizons(df)[180]
    base = block.base_load_kwh.to_numpy()
    price = block.price_per_kwh.to_numpy()
    carbon = block.carbon_kg_per_kwh.to_numpy()
    cost_opt, carbon_opt = op.anchors(base, price, carbon, op.Battery(), op.EV())
    un = op.unmanaged(base, price, carbon, op.EV())
    hours = range(len(base))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    ax1.plot(hours, un.net_load, label="unmanaged", color=plotting.COLOR_NEUTRAL)
    ax1.plot(hours, cost_opt.net_load, label="cost-optimal", color=plotting.PALETTE[0])
    ax1.plot(hours, carbon_opt.net_load, label="carbon-optimal", color=plotting.PALETTE[2])
    ax1.set_ylabel("Grid draw (kWh)")
    ax1.legend()
    ax1.set_title(f"Dispatch on {block.timestamp.iloc[0].date()}, noon to noon")

    ax2.plot(hours, carbon * 1000, "-o", color=plotting.PALETTE[0], label="carbon (gCO2/kWh)")
    ax2b = ax2.twinx()
    ax2b.plot(hours, price, "-s", color=plotting.PALETTE[1], label="price ($/kWh)")
    ax2b.grid(False)
    ax2.set_xlabel("Hour index from noon")
    ax2.set_ylabel("gCO2/kWh", color=plotting.PALETTE[0])
    ax2b.set_ylabel("$/kWh", color=plotting.PALETTE[1])
    return plotting.finish(fig, paths.output(TRACK, "example_day.png"), SUBTITLE)


def fig_signal_profiles(ds: pd.DataFrame) -> Path:
    """The anti-correlation, shown directly. The single most important figure here."""
    hourly = ds.assign(
        a=ds.carbon_kg_per_kwh * 1000, m=ds.marginal_kg_per_kwh * 1000
    ).groupby("hour").agg(a=("a", "mean"), m=("m", "mean"))
    r = np.corrcoef(hourly.a, hourly.m)[0, 1]

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(hourly.index, hourly.a, "-o", color=plotting.PALETTE[0],
            label="average intensity (published)")
    ax.plot(hourly.index, hourly.m, "-s", color=plotting.PALETTE[2],
            label="marginal intensity (estimated)")
    ax.set_xlabel("Hour of day (Eastern)")
    ax.set_ylabel("kgCO2/MWh")
    ax.set_title(f"PJM average and marginal carbon signals move oppositely (r = {r:.2f})")
    ax.legend()
    return plotting.finish(fig, paths.output(TRACK, "signal_profiles.png"), SUBTITLE)


def fig_signal_choice(results: pd.DataFrame) -> Path:
    summary = sc.summarize(results)
    labels = [s for s in sc.STRATEGIES if s in summary.index and s != "unmanaged"]
    avg_change = [summary.loc[s, "avg_carbon_change_pct"] for s in labels]
    mrg_change = [summary.loc[s, "marginal_carbon_change_pct"] for s in labels]

    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(labels))
    width = 0.36
    ax.bar(x - width / 2, avg_change, width, label="scored on average signal")
    ax.bar(x + width / 2, mrg_change, width, label="scored on marginal signal",
           color=plotting.PALETTE[2])
    ax.axhline(0, color="black", lw=1)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Carbon change vs unmanaged (%)")
    ax.set_title("Optimizing on the published average signal raises marginal emissions")
    ax.legend()
    return plotting.finish(fig, paths.output(TRACK, "signal_choice.png"), SUBTITLE)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all",
                    choices=("all", "annual", "frontier", "signal", "figures"))
    args = ap.parse_args()
    plotting.apply_theme()

    df = cd.build_dataset(YEAR)

    if args.stage in ("all", "annual"):
        print(f"[annual] {YEAR}: unmanaged vs cost-optimal vs carbon-optimal, every day")
        annual = cf.annual_summary(df)
        io.write_processed(annual, TRACK, "annual_summary")
        summary = cf.summarize(annual)
        paths.output(TRACK, "summary.json").write_text(json.dumps(summary, indent=2))
        for k, v in summary.items():
            print(f"    {k:34s} {v:,.4f}" if isinstance(v, float) else f"    {k:34s} {v}")

    if args.stage in ("all", "frontier"):
        print("[frontier] weight sweep on weekly sample")
        front = cf.frontier(df)
        io.write_processed(front, TRACK, "frontier")

    if args.stage in ("all", "signal"):
        print("[signal] average vs marginal carbon signal, scored on marginal")
        fit = cm.estimate()
        print(f"    pooled MEF {fit.pooled_mef:.1f} kg/MWh, R2 {fit.pooled_r2:.3f} "
              f"(uncontrolled {fit.pooled_r2_uncontrolled:.3f})")
        io.write_processed(fit.table, TRACK, "mef_table")
        marginal_ds = cm.attach_marginal(df, fit)
        comparison = cm.signal_comparison(marginal_ds)
        results = sc.run_year(marginal_ds, progress_every=0)
        io.write_processed(results, TRACK, "signal_choice")
        summary = sc.summarize(results)
        summary.to_csv(paths.output(TRACK, "signal_choice.csv"))
        print(summary[["cost_change_pct", "avg_carbon_change_pct",
                       "marginal_carbon_change_pct"]].round(2).to_string())
        flips = sc.sign_flip_days(results)
        print(f"    average-signal control helps on average but hurts on marginal: "
              f"{flips['helps_avg_but_hurts_marginal']}/{flips['days']} days")
        paths.output(TRACK, "signal_comparison.json").write_text(
            json.dumps({**comparison, **flips,
                        "pooled_mef_kg_per_mwh": fit.pooled_mef,
                        "pooled_r2": fit.pooled_r2,
                        "pooled_r2_uncontrolled": fit.pooled_r2_uncontrolled}, indent=2))

    if args.stage in ("all", "figures"):
        print("[figures]")
        made = [fig_carbon_vs_price(df), fig_example_day(df)]
        try:
            made.append(fig_monthly(io.read_processed(TRACK, "annual_summary")))
        except FileNotFoundError:
            print("    (annual not built yet)")
        try:
            made.append(fig_frontier(io.read_processed(TRACK, "frontier")))
        except FileNotFoundError:
            print("    (frontier not built yet)")
        try:
            made.append(fig_signal_profiles(cm.attach_marginal(df)))
            made.append(fig_signal_choice(io.read_processed(TRACK, "signal_choice")))
        except FileNotFoundError:
            print("    (signal comparison not built yet)")
        for p in made:
            print("   ", p.relative_to(paths.REPO_ROOT))


if __name__ == "__main__":
    main()
