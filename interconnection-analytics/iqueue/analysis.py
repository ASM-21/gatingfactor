"""Queue outcome analysis, with the competing-risks structure handled explicitly.

The central hazard in this dataset is that **the obvious statistic answers a
different question than the one people ask of it.**

"Median time to interconnect" computed over completed projects is conditioned
on success. It describes the projects that finished. A developer entering the
queue wants to know how long *their* project will wait, and in this dataset no
cohort has ever had even half its requests reach operation, so that wait has no
median at all. The completed-only median is a statistic about a minority.

It also has a second, mechanical problem when read in real time. A cohort that
entered recently has only had time to produce its fast completions; its slow
ones are still in the queue. So a completed-only median read before the cohort
resolves is right-truncated, and reads low. ``realtime_backtest`` measures how
low by re-reading fully resolved cohorts at earlier record end dates.

Three rules are applied throughout:

1. **Cohort framing.** Outcomes are reported by the year a project entered the
   queue, never pooled across entry years. A 2022 cohort has had two years to
   resolve and a 2010 cohort fourteen, so pooling them is meaningless.

2. **Withdrawal is a competing risk, not censoring.** A project that withdraws
   can never complete. Treating withdrawal as ordinary censoring, as a plain
   Kaplan-Meier fit on time-to-completion does, estimates time-to-completion in
   a hypothetical queue where nobody withdraws. That quantity describes no real
   project. An earlier version of this module made exactly that error in its
   headline function while this docstring warned against it; see the retraction
   in FINDINGS.md.

3. **Outcome shares come from status; timing comes from dates.** Status has
   complete coverage. Dates do not: about half of withdrawals and of
   completions carry no terminal date. Rate statistics therefore use every row,
   and timing statistics state the subset they rest on.

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
    """Probability a project has reached ``outcome`` by time t, under competing risks.

    Decomposed as

        CIF_k(t) = P(outcome = k) * P(T <= t | outcome = k)

    The first factor comes from status, which has complete coverage. The second
    comes from the dated projects with outcome k, under the stated assumption
    that a terminal date is missing at random *within* an outcome. That
    assumption is needed because about half of withdrawals and of completions
    carry no date, and it is weaker than the alternatives: dropping undated
    rows distorts the outcome mix, and keeping them in the denominator with no
    way into the numerator (an earlier version of this function) understates
    incidence by roughly half.

    This is not 1 minus Kaplan-Meier survival. Applying Kaplan-Meier to one
    outcome while censoring the other assumes withdrawn projects could still
    have completed.

    Use on resolved cohorts (``mature_cohorts``). For a cohort still largely in
    the queue, P(outcome = k) is not yet final and the curve reads low.
    """
    n = len(df)
    grid = np.linspace(0, horizon_years, steps)
    if n == 0:
        return pd.DataFrame({"time_years": grid, "cumulative_incidence": np.nan})

    share = float((df.outcome == outcome).mean())
    dated = df.loc[(df.outcome == outcome) & df.timing_known, "duration_years"].to_numpy()
    rows = []
    for horizon in grid:
        conditional = float((dated <= horizon).mean()) if len(dated) else 0.0
        rows.append(
            {"time_years": float(horizon), "cumulative_incidence": share * conditional}
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


def cohort_outcomes(df: pd.DataFrame) -> pd.DataFrame:
    """Lifetime outcome shares and the completed-only median, by 5-year entry cohort.

    ``completion_rate`` is the share of the cohort whose status is operational.
    It needs no dates, so it covers every row. For resolved cohorts it is the
    whole story about the median wait: if it is below 0.5, no median time to
    completion exists for a project entering that cohort, because most of them
    never complete.

    ``naive_median_years`` is the median entry-to-operation duration over the
    dated completions, which is the statistic usually quoted. It is a fair
    description of the completers in a resolved cohort. It is not a description
    of the wait facing a new entrant, and for unresolved cohorts it is also
    right-truncated; see ``realtime_backtest``.
    """
    rows = []
    for cohort, group in df.groupby(df.queue_year // 5 * 5):
        completed = group[group.outcome == "operational"].duration_years.dropna()
        if len(completed) < 10:
            continue
        inc = cumulative_incidence(group, "operational", horizon_years=10.0, steps=41)
        rows.append(
            {
                "cohort_start": int(cohort),
                "n_projects": int(len(group)),
                "n_completed_dated": int(len(completed)),
                "completion_rate": float((group.outcome == "operational").mean()),
                "withdrawal_rate": float((group.outcome == "withdrawn").mean()),
                "still_open_rate": float(group.outcome.isin(["active", "suspended"]).mean()),
                "naive_median_years": float(completed.median()),
                "completion_prob_5yr": float(
                    inc.loc[inc.time_years.sub(5).abs().idxmin(), "cumulative_incidence"]
                ),
                "completion_prob_10yr": float(inc.cumulative_incidence.iloc[-1]),
            }
        )
    return pd.DataFrame(rows)


BACKTEST_COHORTS = (2000, 2005, 2010)
BACKTEST_OFFSETS = (0, 1, 3, 5, 10)


def realtime_backtest(
    df: pd.DataFrame,
    cohorts: tuple[int, ...] = BACKTEST_COHORTS,
    offsets: tuple[int, ...] = BACKTEST_OFFSETS,
    record_end: pd.Timestamp = RECORD_END,
) -> pd.DataFrame:
    """How low the completed-only median reads before a cohort has resolved.

    For each fully resolved 5-year cohort, the completed-only median is
    recomputed as it would have been reported at an earlier record end:
    ``offset`` years after the cohort's last entry year closed. Comparing that
    to the full-record median measures right-truncation directly, with no
    modeling assumption beyond the dates themselves.

    Offset 0 is the analog of reading the most recent cohort in the record
    today. The 2020-24 cohort, read at the end of 2024, sits exactly there.

    Only cohorts that have had at least 10 years to resolve are eligible, so the
    full-record median is itself close to final.
    """
    op = df[(df.outcome == "operational") & df.actual_cod_date.notna() & df.duration_years.notna()]
    cohort_of = op.queue_year // 5 * 5
    rows = []
    for cohort in cohorts:
        if cohort + 4 + 10 > record_end.year:
            raise ValueError(f"cohort {cohort} has not had 10 years to resolve; not a valid backtest")
        group = op[cohort_of == cohort]
        full = float(group.duration_years.median())
        for offset in offsets:
            cut = pd.Timestamp(f"{cohort + 4 + offset}-12-31")
            seen = group[group.actual_cod_date <= cut]
            as_reported = float(seen.duration_years.median()) if len(seen) else np.nan
            rows.append(
                {
                    "cohort_start": int(cohort),
                    "years_after_close": int(offset),
                    "report_date": cut.date().isoformat(),
                    "n_completed_seen": int(len(seen)),
                    "n_completed_total": int(len(group)),
                    "median_as_reported": as_reported,
                    "median_full_record": full,
                    "understatement": full / as_reported if as_reported else np.nan,
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
