"""Queue outcome analysis, with censoring handled explicitly.

The central hazard in this dataset is that **the obvious statistic is wrong**.

"Median time to interconnect" computed over completed projects is conditioned
on success: it can only see projects that finished, and a project that entered
the queue in 2021 and is still waiting contributes nothing. When queues get
slower, slow projects stay unfinished and drop out of the sample, so the
measured median gets *faster*. The bias runs opposite to the trend.

Two corrections are applied throughout:

1. **Cohort framing.** Outcomes are reported by the year a project entered the
   queue, never pooled across entry years. A 2022 cohort has had three years to
   resolve and a 2010 cohort has had fifteen, so pooling them is meaningless.

2. **Kaplan-Meier survival.** For time-to-outcome, every project contributes
   the time it was actually observed. Projects still active at the end of the
   record are right-censored rather than dropped, which uses their information
   without pretending to know when they will finish.

Withdrawal and completion are **competing risks**: a project that withdraws can
never complete. Treating withdrawal as ordinary censoring would overstate the
completion rate, so cumulative incidence is computed for each outcome against
the shared at-risk pool.

``maturity_cutoff`` exists because recent cohorts are not yet informative. A
cohort needs several years before its completion rate means anything, and the
default of 5 years is stated rather than buried.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import ingest

RECORD_END = pd.Timestamp("2024-12-31")
DEFAULT_MATURITY_YEARS = 5


# --- outcome resolution -----------------------------------------------------


def resolve_outcomes(df: pd.DataFrame, record_end: pd.Timestamp = RECORD_END) -> pd.DataFrame:
    """Attach outcome, observed duration, and timing availability to each project.

    Outcome comes from **status**, not from dates. This matters: about half of
    withdrawn projects carry no withdrawal date, and classifying those as
    "still waiting" because a date is missing would understate the withdrawal
    rate by roughly a factor of two. The outcome is known; only its timing is
    not.

    ``duration_years`` is therefore populated only where a terminal date
    exists, and ``timing_known`` flags which rows can enter a survival model.
    Rate statistics use every row; timing statistics use the subset.
    """
    out = df.copy()

    outcome = pd.Series("active", index=out.index, dtype=object)
    outcome[out.status.eq(ingest.OPERATIONAL)] = "operational"
    outcome[out.status.eq(ingest.WITHDRAWN)] = "withdrawn"
    outcome[out.status.eq(ingest.SUSPENDED)] = "suspended"

    end_date = pd.Series(pd.NaT, index=out.index)
    is_op = outcome.eq("operational") & out.actual_cod_date.notna()
    end_date[is_op] = out.actual_cod_date[is_op]
    is_wd = outcome.eq("withdrawn") & out.withdrawal_date.notna()
    end_date[is_wd] = out.withdrawal_date[is_wd]

    still_open = outcome.isin(["active", "suspended"])
    end_date[still_open] = record_end

    out["outcome"] = outcome
    out["terminal_event"] = outcome.isin(["operational", "withdrawn"])
    out["end_date"] = end_date
    out["duration_years"] = (out.end_date - out.queue_date).dt.days / 365.25
    out.loc[(out.duration_years < 0) | (out.duration_years > 30), "duration_years"] = np.nan
    out["timing_known"] = out.duration_years.notna()
    return out


def mature_cohorts(
    df: pd.DataFrame,
    maturity_years: int = DEFAULT_MATURITY_YEARS,
    record_end: pd.Timestamp = RECORD_END,
) -> pd.DataFrame:
    """Drop cohorts too recent to have resolved.

    Without this, the most recent years show an artificially low completion
    rate simply because nothing has had time to finish yet, and it reads as a
    collapse in throughput.
    """
    cutoff = record_end.year - maturity_years
    return df[df.queue_year <= cutoff]


# --- survival ---------------------------------------------------------------


def kaplan_meier(durations: np.ndarray, events: np.ndarray) -> pd.DataFrame:
    """Kaplan-Meier estimator of the survival function.

    ``events`` is 1 where the event of interest occurred and 0 where the
    observation is censored. Returns time, at_risk, events, and survival.
    """
    order = np.argsort(durations)
    t, e = np.asarray(durations)[order], np.asarray(events)[order]
    n = len(t)
    rows = []
    survival = 1.0
    i = 0
    while i < n:
        time = t[i]
        tied = t == time
        d = int(e[tied].sum())
        at_risk = int(n - i)
        if d > 0:
            survival *= 1.0 - d / at_risk
        rows.append(
            {"time_years": float(time), "at_risk": at_risk, "events": d, "survival": survival}
        )
        i += int(tied.sum())
    return pd.DataFrame(rows)


def cumulative_incidence(
    df: pd.DataFrame, outcome: str, horizon_years: float = 10.0, steps: int = 60
) -> pd.DataFrame:
    """Probability of a given outcome by time t, treating the other as a competing risk.

    This is not 1 minus Kaplan-Meier survival. With competing risks, KM applied
    to one outcome while censoring the other overstates it, because it assumes
    withdrawn projects could still have completed.
    """
    t = df.duration_years.to_numpy()
    obs = df.outcome.to_numpy()
    # Denominator is the full cohort, including projects whose terminal date is
    # unknown. Those can never appear in the numerator, so this is a lower
    # bound on incidence and is stated as such.
    grid = np.linspace(0, horizon_years, steps)
    n = len(df)
    t = np.nan_to_num(t, nan=np.inf)
    rows = []
    for horizon in grid:
        resolved = (t <= horizon) & (obs == outcome)
        rows.append(
            {
                "time_years": float(horizon),
                "cumulative_incidence": float(resolved.sum() / n) if n else np.nan,
            }
        )
    return pd.DataFrame(rows)


# --- headline statistics ----------------------------------------------------


def completion_rates(
    df: pd.DataFrame, by: str = "queue_year", maturity_years: int = DEFAULT_MATURITY_YEARS
) -> pd.DataFrame:
    """Share of each cohort that reached operation, withdrew, or is still waiting."""
    mature = mature_cohorts(df, maturity_years)
    grouped = mature.groupby(by).outcome.value_counts(normalize=True).unstack(fill_value=0.0)
    counts = mature.groupby(by).size().rename("n_projects")
    mw = mature.groupby(by).capacity_mw.sum().rename("total_mw")
    out = grouped.join(counts).join(mw)
    for col in ("operational", "withdrawn", "censored"):
        if col not in out.columns:
            out[col] = 0.0
    return out.reset_index()


def naive_vs_survival_duration(df: pd.DataFrame) -> pd.DataFrame:
    """Quantify the survivorship bias in the usual time-to-interconnect statistic.

    ``naive_median_years`` is what a straightforward groupby over completed
    projects gives, and it is the number most often quoted.

    ``completion_prob_5yr`` and ``completion_prob_10yr`` come from the
    competing-risks cumulative incidence over the whole cohort, so they include
    projects that withdrew or are still waiting.

    ``km_median_years`` is usually **NaN by construction**, and that is the
    finding rather than a failure: when a cohort's lifetime completion
    probability is below 50%, the median time to completion does not exist. The
    naive median still returns a number because it silently conditions on the
    minority that finished.
    """
    rows = []
    for cohort, group in df.groupby(df.queue_year // 5 * 5):
        completed = group[group.outcome == "operational"].duration_years.dropna()
        if len(completed) < 10:
            continue
        timed = group[group.timing_known]
        km = kaplan_meier(
            timed.duration_years.to_numpy(),
            (timed.outcome == "operational").astype(int).to_numpy(),
        )
        below = km[km.survival <= 0.5]
        km_median = float(below.time_years.iloc[0]) if len(below) else np.nan
        inc = cumulative_incidence(group, "operational", horizon_years=10.0, steps=41)
        rows.append(
            {
                "cohort_start": int(cohort),
                "n_projects": int(len(group)),
                "n_completed": int(len(completed)),
                "naive_median_years": float(completed.median()),
                "km_median_years": km_median,
                "completion_prob_5yr": float(
                    inc.loc[inc.time_years.sub(5).abs().idxmin(), "cumulative_incidence"]
                ),
                "completion_prob_10yr": float(inc.cumulative_incidence.iloc[-1]),
                "completion_rate": float((group.outcome == "operational").mean()),
            }
        )
    return pd.DataFrame(rows)


def queue_growth(df: pd.DataFrame) -> pd.DataFrame:
    """Annual requests and capacity entering the queue."""
    valid = df[df.queue_year.between(2000, 2024)]
    out = valid.groupby("queue_year").agg(
        n_requests=("project_id", "count"),
        total_mw=("capacity_mw", "sum"),
        median_mw=("capacity_mw", "median"),
    )
    return out.reset_index()


def by_resource(df: pd.DataFrame, maturity_years: int = DEFAULT_MATURITY_YEARS) -> pd.DataFrame:
    """Completion and withdrawal by resource type, mature cohorts only."""
    mature = mature_cohorts(df, maturity_years)
    rows = []
    for resource, group in mature.groupby("resource_group"):
        if len(group) < 50:
            continue
        completed = group[group.outcome == "operational"].duration_years.dropna()
        rows.append(
            {
                "resource_group": resource,
                "n_projects": int(len(group)),
                "total_mw": float(group.capacity_mw.sum()),
                "completion_rate": float((group.outcome == "operational").mean()),
                "withdrawal_rate": float((group.outcome == "withdrawn").mean()),
                "naive_median_years": float(completed.median()) if len(completed) else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("completion_rate", ascending=False)


def by_region(df: pd.DataFrame, maturity_years: int = DEFAULT_MATURITY_YEARS) -> pd.DataFrame:
    mature = mature_cohorts(df, maturity_years)
    rows = []
    for region, group in mature.groupby("region"):
        completed = group[group.outcome == "operational"].duration_years.dropna()
        rows.append(
            {
                "region": region,
                "n_projects": int(len(group)),
                "total_mw": float(group.capacity_mw.sum()),
                "completion_rate": float((group.outcome == "operational").mean()),
                "withdrawal_rate": float((group.outcome == "withdrawn").mean()),
                "naive_median_years": float(completed.median()) if len(completed) else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("completion_rate", ascending=False)
