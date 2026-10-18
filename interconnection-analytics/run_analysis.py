"""Regenerate every interconnection-analytics artifact.

    python run_analysis.py
"""

from __future__ import annotations

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

from iqueue import analysis as an, ingest  # noqa: E402
from shared import io, paths, plotting  # noqa: E402

TRACK = "interconnection-analytics"
SUBTITLE = (
    "gatingfactor / interconnection-analytics. Berkeley Lab Queued Up 2025 release "
    "(36,441 requests through 2024). Cohorts within 5 years of the record end are excluded."
)
SUBTITLE_ALL_COHORTS = (
    "gatingfactor / interconnection-analytics. Berkeley Lab Queued Up 2025 release "
    "(36,441 requests through 2024). All cohorts shown; shares from status, which covers every row."
)
SUBTITLE_BACKTEST = (
    "gatingfactor / interconnection-analytics. Berkeley Lab Queued Up 2025 release. "
    "Fully resolved cohorts re-read at earlier record end dates; dated completions only."
)


def fig_cohort_outcomes(cohorts: pd.DataFrame) -> Path:
    """No cohort ever gets half its requests to operation."""
    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(cohorts))
    completed = 100 * cohorts.completion_rate
    withdrawn = 100 * cohorts.withdrawal_rate
    still_open = 100 * cohorts.still_open_rate
    ax.bar(x, completed, label="reached operation", color=plotting.PALETTE[0])
    ax.bar(x, withdrawn, bottom=completed, label="withdrew", color=plotting.COLOR_VIOLATION)
    ax.bar(x, still_open, bottom=completed + withdrawn, label="still in the queue",
           color=plotting.COLOR_NEUTRAL)
    ax.axhline(50, color="black", lw=1, ls="--")
    ax.text(len(cohorts) - 0.45, 51.5, "half the cohort", ha="right", fontsize=9)
    for i, (c, med) in enumerate(zip(completed, cohorts.naive_median_years)):
        label = f"{c:.0f}%\nmedian of\ncompleters\n{med:.1f} yr"
        # Small bars cannot hold the label; set it just above, on the red segment.
        y, va = (c / 2, "center") if c >= 10 else (c + 1.5, "bottom")
        ax.text(i, y, label, ha="center", va=va, fontsize=7.5, color="white")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{int(c)}-{int(c)+4}" for c in cohorts.cohort_start])
    ax.set_xlabel("Queue entry cohort")
    ax.set_ylabel("Share of cohort (%)")
    ax.set_ylim(0, 112)
    ax.set_yticks(range(0, 101, 20))
    ax.set_title("No cohort has had half its requests reach operation")
    ax.legend(loc="upper center", ncol=3, frameon=False)
    return plotting.finish(fig, paths.output(TRACK, "cohort_outcomes.png"), SUBTITLE_ALL_COHORTS)


def fig_realtime_backtest(backtest: pd.DataFrame) -> Path:
    """The completed-only median, as it would have read before each cohort resolved."""
    fig, ax = plt.subplots(figsize=(10, 6))
    for i, (cohort, g) in enumerate(backtest.groupby("cohort_start")):
        color = plotting.PALETTE[i]
        ax.plot(g.years_after_close, g.median_as_reported, "-o", color=color,
                label=f"{cohort}-{cohort + 4} cohort")
        ax.axhline(g.median_full_record.iloc[0], color=color, ls=":", lw=1)
        first = g.iloc[0]
        ax.annotate(f"{first.understatement:.2f}x low", (first.years_after_close, first.median_as_reported),
                    xytext=(8, -14), textcoords="offset points", fontsize=8, color=color)
    ax.set_xlabel("Years after the cohort's last entry year when the median is read")
    ax.set_ylabel("Median years to operation, completed projects only")
    ax.set_title("Read before a cohort resolves, the completed-only median is truncated low")
    ax.legend()
    ax.text(0.99, 0.02, "dotted lines: value once the cohort has fully resolved",
            transform=ax.transAxes, ha="right", fontsize=8, color=plotting.COLOR_NEUTRAL)
    return plotting.finish(fig, paths.output(TRACK, "realtime_backtest.png"), SUBTITLE_BACKTEST)


def fig_completion_trend(rates: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(10, 6))
    r = rates[rates.queue_year >= 2000]
    ax.plot(r.queue_year, 100 * r.operational, "-o", label="reached operation")
    ax.plot(r.queue_year, 100 * r.withdrawn, "-s", label="withdrawn",
            color=plotting.COLOR_VIOLATION)
    ax.plot(r.queue_year, 100 * r.active, "-^", label="still active",
            color=plotting.COLOR_NEUTRAL)
    ax.set_xlabel("Queue entry year")
    ax.set_ylabel("Share of cohort (%)")
    ax.set_title("Withdrawal is the modal outcome, and its share is rising")
    ax.legend()
    return plotting.finish(fig, paths.output(TRACK, "completion_trend.png"), SUBTITLE)


def fig_resource(res: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(10, 6))
    r = res.sort_values("completion_rate")
    y = np.arange(len(r))
    ax.barh(y, 100 * r.completion_rate, color=plotting.PALETTE[0])
    ax.set_yticks(y)
    ax.set_yticklabels(r.resource_group)
    for i, (rate, n) in enumerate(zip(r.completion_rate, r.n_projects)):
        ax.text(100 * rate + 0.6, i, f"n={n}", va="center", fontsize=8)
    ax.set_xlabel("Completion rate (%)")
    ax.set_title("Completion rate by resource type, mature cohorts")
    return plotting.finish(fig, paths.output(TRACK, "completion_by_resource.png"), SUBTITLE)


def fig_incidence(resolved: pd.DataFrame) -> Path:
    """Competing risks: where projects actually end up over time."""
    pjm = resolved[resolved.region == "PJM"]
    mature = an.mature_cohorts(pjm)
    fig, ax = plt.subplots(figsize=(10, 6))
    for outcome, color in (("operational", plotting.PALETTE[0]),
                           ("withdrawn", plotting.COLOR_VIOLATION)):
        inc = an.cumulative_incidence(mature, outcome, horizon_years=15.0, steps=60)
        ax.plot(inc.time_years, 100 * inc.cumulative_incidence, label=outcome, color=color)
    ax.set_xlabel("Years since queue entry")
    ax.set_ylabel("Cumulative incidence (%)")
    ax.set_title("PJM: competing outcomes over time, mature cohorts")
    ax.legend()
    return plotting.finish(fig, paths.output(TRACK, "pjm_cumulative_incidence.png"), SUBTITLE)


def fig_growth(growth: pd.DataFrame) -> Path:
    fig, ax1 = plt.subplots(figsize=(10, 6))
    ax2 = ax1.twinx()
    ax1.bar(growth.queue_year, growth.n_requests, color=plotting.PALETTE[0], alpha=0.75,
            label="requests")
    ax2.plot(growth.queue_year, growth.total_mw / 1000, "-o", color=plotting.PALETTE[2],
             label="capacity")
    ax2.grid(False)
    ax1.set_xlabel("Queue entry year")
    ax1.set_ylabel("Interconnection requests", color=plotting.PALETTE[0])
    ax2.set_ylabel("Capacity requested (GW)", color=plotting.PALETTE[2])
    ax1.set_title("Annual interconnection requests and capacity, all US regions")
    return plotting.finish(fig, paths.output(TRACK, "queue_growth.png"), SUBTITLE)


def main() -> None:
    plotting.apply_theme()

    print("[ingest] LBNL Queued Up")
    raw = ingest.load_lbnl()
    print(f"    {len(raw):,} requests, {raw.queue_year.min():.0f}-{raw.queue_year.max():.0f}")
    coverage = ingest.coverage_report(raw)
    io.write_processed(coverage, TRACK, "coverage")
    print("    date coverage: " + ", ".join(
        f"{r.column} {r.coverage_pct}%"
        for _, r in coverage[coverage.column.str.contains("date")].iterrows()
    ))

    resolved = an.resolve_outcomes(raw)
    io.write_processed(resolved, TRACK, "resolved")
    print(f"    outcomes: {resolved.outcome.value_counts().to_dict()}")
    print(f"    timing known for {100 * resolved.timing_known.mean():.1f}% of rows")

    print("\n[cohort outcomes] lifetime shares and the completed-only median")
    cohorts = an.cohort_outcomes(resolved)
    io.write_processed(cohorts, TRACK, "cohort_outcomes")
    cohorts.to_csv(paths.output(TRACK, "cohort_outcomes.csv"), index=False)
    print(cohorts.round(3).to_string(index=False))

    print("\n[real-time backtest] completed-only median read before resolution")
    backtest = an.realtime_backtest(resolved)
    io.write_processed(backtest, TRACK, "realtime_backtest")
    backtest.to_csv(paths.output(TRACK, "realtime_backtest.csv"), index=False)
    print(backtest.round(3).to_string(index=False))

    print("\n[cohorts]")
    rates = an.completion_rates(resolved)
    io.write_processed(rates, TRACK, "completion_rates")

    resources = an.by_resource(resolved)
    regions = an.by_region(resolved)
    io.write_processed(resources, TRACK, "by_resource")
    io.write_processed(regions, TRACK, "by_region")
    regions.to_csv(paths.output(TRACK, "by_region.csv"), index=False)
    resources.to_csv(paths.output(TRACK, "by_resource.csv"), index=False)
    print(regions.round(3).to_string(index=False))

    print("\n[pjm/ppl cut]")
    pjm = resolved[resolved.region == "PJM"]
    ppl = resolved[resolved.utility == "PPL"]
    cut = {
        "pjm_projects": int(len(pjm)),
        "pjm_completion_rate": float((pjm.outcome == "operational").mean()),
        "pjm_withdrawal_rate": float((pjm.outcome == "withdrawn").mean()),
        "pjm_total_mw": float(pjm.capacity_mw.sum()),
        "ppl_projects": int(len(ppl)),
        "ppl_completion_rate": float((ppl.outcome == "operational").mean()),
        "ppl_withdrawal_rate": float((ppl.outcome == "withdrawn").mean()),
        "ppl_total_mw": float(ppl.capacity_mw.sum()),
    }
    paths.output(TRACK, "pjm_ppl_summary.json").write_text(json.dumps(cut, indent=2))
    for k, v in cut.items():
        print(f"    {k:24s} {v:,.3f}" if isinstance(v, float) else f"    {k:24s} {v:,}")

    growth = an.queue_growth(resolved)
    io.write_processed(growth, TRACK, "queue_growth")

    print("\n[figures]")
    for p in (
        fig_cohort_outcomes(cohorts),
        fig_realtime_backtest(backtest),
        fig_completion_trend(rates),
        fig_resource(resources),
        fig_incidence(resolved),
        fig_growth(growth),
    ):
        print("   ", p.relative_to(paths.REPO_ROOT))


if __name__ == "__main__":
    main()
