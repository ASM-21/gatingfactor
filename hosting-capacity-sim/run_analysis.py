"""Regenerate every hosting-capacity-sim artifact.

    python run_analysis.py            # full run
    python run_analysis.py --quick    # coarser tolerance, skips nodal maps

Outputs land in data/processed/hosting-capacity-sim/ and outputs/hosting-capacity-sim/.
"""

from __future__ import annotations

import argparse
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from hcsim import feeders, hosting_capacity as hc  # noqa: E402
from shared import io, paths, plotting  # noqa: E402

TRACK = "hosting-capacity-sim"
SUBTITLE = (
    "gatingfactor / hosting-capacity-sim. Synthetic feeder archetypes, balanced "
    "positive-sequence model. Illustrative only, not calibrated to any real circuit."
)


def build_results(tol_mw: float) -> pd.DataFrame:
    rows = []
    for feeder_name in feeders.SPECS:
        for strategy in hc.STRATEGIES:
            for vv in (False, True):
                t0 = time.time()
                res = hc.search(feeder_name, strategy, use_volt_var=vv, tol_mw=tol_mw)
                rows.append(res.to_row())
                print(
                    f"  {feeder_name:9s} {strategy:17s} vv={str(vv):5s} "
                    f"HC={res.hosting_capacity_mw:7.3f} MW  binds={res.binding_screen:<14s} "
                    f"({time.time() - t0:.1f}s)",
                    flush=True,
                )
    return pd.DataFrame(rows)


def build_nodal(tol_mw: float, only: str | None = None) -> pd.DataFrame:
    rows = []
    specs = {only: feeders.SPECS[only]} if only else feeders.SPECS
    for feeder_name, spec in specs.items():
        scaffold = feeders.build(spec, load_scale=spec.min_daytime_load_frac)
        dist = feeders.distance_km(scaffold, spec)
        for vv in (False, True):
            t0 = time.time()
            nodal = hc.nodal_map(feeder_name, use_volt_var=vv, tol_mw=tol_mw)
            for bus, mw in nodal.items():
                rows.append(
                    {
                        "feeder": feeder_name,
                        "volt_var": vv,
                        "bus": bus,
                        "distance_km": dist[bus],
                        "hosting_capacity_mw": mw,
                    }
                )
            print(f"  nodal {feeder_name:9s} vv={str(vv):5s} ({time.time() - t0:.1f}s)", flush=True)
    return pd.DataFrame(rows)


def build_sweeps() -> pd.DataFrame:
    rows = []
    caps = {"rural": 3.0, "suburban": 8.0, "urban": 20.0}
    for feeder_name, upper in caps.items():
        for vv in (False, True):
            for rec in hc.sweep(feeder_name, "distributed", use_volt_var=vv, upper_mw=upper):
                rec |= {"feeder": feeder_name, "volt_var": vv}
                rows.append(rec)
    return pd.DataFrame(rows)


# --- figures ----------------------------------------------------------------


def fig_screen_comparison(results: pd.DataFrame) -> Path:
    """Where each screen binds, for the distributed / no-volt-var base case."""
    base = results[(results.strategy == "distributed") & (~results.volt_var)]
    screens_cols = [
        ("limit_penetration_15_mw", "Fast Track 15% of peak"),
        ("limit_min_daytime_mw", "100% of min daytime load"),
        ("limit_reverse_power_mw", "Substation reverse power"),
        ("limit_voltage_mw", "Voltage (ANSI Range A)"),
        ("limit_thermal_mw", "Thermal (conductor)"),
    ]
    fig, ax = plt.subplots(figsize=(11, 6))
    n = len(screens_cols)
    width = 0.15
    x = range(len(base))
    for i, (col, label) in enumerate(screens_cols):
        offs = [xi + (i - n / 2) * width + width / 2 for xi in x]
        ax.bar(offs, base[col].to_numpy(), width=width, label=label)
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{f}\npeak {p:.2f} MW" for f, p in zip(base.feeder, base.peak_load_mw)])
    ax.set_ylabel("Limiting DER nameplate (MW)")
    ax.set_yscale("log")
    ax.set_title("Which screen binds first, by feeder archetype")
    ax.legend(ncol=2)
    return plotting.finish(fig, paths.output(TRACK, "screen_comparison.png"), SUBTITLE)


def fig_nodal(nodal: pd.DataFrame) -> Path:
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=False)
    for ax, feeder_name in zip(axes, feeders.SPECS):
        sub = nodal[nodal.feeder == feeder_name]
        for vv, style in ((False, "-o"), (True, "--s")):
            s = sub[sub.volt_var == vv].sort_values("distance_km")
            ax.plot(
                s.distance_km,
                s.hosting_capacity_mw,
                style,
                ms=3,
                label="volt-var on" if vv else "volt-var off",
            )
        ax.set_title(feeder_name)
        ax.set_xlabel("Circuit distance from substation (km)")
        ax.set_yscale("log")
    axes[0].set_ylabel("Single-site hosting capacity (MW)")
    axes[0].legend()
    fig.suptitle("Hosting capacity falls with distance from the substation")
    return plotting.finish(fig, paths.output(TRACK, "nodal_hosting_capacity.png"), SUBTITLE)


def fig_sweeps(sweeps: pd.DataFrame) -> Path:
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    for ax, feeder_name in zip(axes, feeders.SPECS):
        sub = sweeps[sweeps.feeder == feeder_name]
        for vv, style in ((False, "-"), (True, "--")):
            s = sub[sub.volt_var == vv]
            ax.plot(s.der_mw, s.max_vm_pu, style, label="volt-var on" if vv else "volt-var off")
        ax.axhline(1.05, color=plotting.COLOR_VIOLATION, lw=1.2, ls=":")
        ax.text(0.02, 1.0505, "ANSI Range A max", fontsize=8, color=plotting.COLOR_VIOLATION)
        ax.set_title(feeder_name)
        ax.set_xlabel("Aggregate DER (MW)")
    axes[0].set_ylabel("Max feeder voltage (pu)")
    axes[0].legend()
    fig.suptitle("Voltage rise vs DER penetration, distributed siting at min daytime load")
    return plotting.finish(fig, paths.output(TRACK, "voltage_rise_sweep.png"), SUBTITLE)


def fig_strategy(results: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(10, 6))
    width = 0.25
    strategies = list(hc.STRATEGIES)
    feeder_names = list(feeders.SPECS)
    for i, strategy in enumerate(strategies):
        vals = [
            results[
                (results.feeder == f) & (results.strategy == strategy) & (~results.volt_var)
            ].hosting_capacity_mw.iloc[0]
            for f in feeder_names
        ]
        offs = [j + (i - len(strategies) / 2) * width + width / 2 for j in range(len(feeder_names))]
        ax.bar(offs, vals, width=width, label=strategy.replace("_", " "))
    ax.set_xticks(range(len(feeder_names)))
    ax.set_xticklabels(feeder_names)
    ax.set_ylabel("Hosting capacity (MW)")
    ax.set_yscale("log")
    ax.set_title("Siting strategy changes hosting capacity by an order of magnitude")
    ax.legend()
    return plotting.finish(fig, paths.output(TRACK, "siting_strategy.png"), SUBTITLE)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--stage",
        default="all",
        choices=("all", "results", "sweeps", "nodal", "figures", "verify"),
        help="run one stage; each caches to parquet so stages are resumable",
    )
    ap.add_argument("--feeder", default=None, help="restrict the nodal stage to one feeder")
    ap.add_argument("--quick", action="store_true", help="coarse tolerance")
    args = ap.parse_args()
    tol = 0.05 if args.quick else 0.01
    plotting.apply_theme()
    stage = args.stage

    if stage in ("all", "results"):
        print("[results] hosting capacity by feeder / strategy / volt-var")
        results = build_results(tol)
        io.write_processed(results, TRACK, "hosting_capacity_results")
        results.to_csv(paths.output(TRACK, "hosting_capacity_results.csv"), index=False)

    if stage in ("all", "sweeps"):
        print("[sweeps] penetration sweeps")
        sweeps = build_sweeps()
        io.write_processed(sweeps, TRACK, "penetration_sweeps")

    if stage in ("all", "nodal"):
        print(f"[nodal] nodal hosting capacity maps{' for ' + args.feeder if args.feeder else ''}")
        fresh = build_nodal(tol_mw=0.05, only=args.feeder)
        try:
            prior = io.read_processed(TRACK, "nodal_hosting_capacity")
            if args.feeder:
                prior = prior[prior.feeder != args.feeder]
            nodal = pd.concat([prior, fresh], ignore_index=True)
        except FileNotFoundError:
            nodal = fresh
        io.write_processed(nodal, TRACK, "nodal_hosting_capacity")
        nodal.to_csv(paths.output(TRACK, "nodal_hosting_capacity.csv"), index=False)

    if stage in ("all", "figures"):
        print("[figures]")
        results = io.read_processed(TRACK, "hosting_capacity_results")
        sweeps = io.read_processed(TRACK, "penetration_sweeps")
        made = [fig_screen_comparison(results), fig_sweeps(sweeps), fig_strategy(results)]
        try:
            made.append(fig_nodal(io.read_processed(TRACK, "nodal_hosting_capacity")))
        except FileNotFoundError:
            print("    (nodal map not built yet, skipping that figure)")
        for p in made:
            print("   ", p.relative_to(paths.REPO_ROOT))

    if stage in ("all", "verify"):
        print("[verify] monotonicity check (bisection validity)")
        for feeder_name in feeders.SPECS:
            ok = hc.verify_monotonic(feeder_name, upper_mw=8.0, steps=25)
            print(f"  {feeder_name:9s} monotonic={ok}")


if __name__ == "__main__":
    main()
