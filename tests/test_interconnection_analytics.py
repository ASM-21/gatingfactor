"""Tests for interconnection-analytics.

Two classes of test: the ingest quirks that silently corrupt this dataset
(Excel serial dates, date-vs-status outcome classification), and the survival
math that the headline finding depends on.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "interconnection-analytics"))

from iqueue import analysis as an, ingest  # noqa: E402


@pytest.fixture(scope="module")
def raw():
    return ingest.load_lbnl()


@pytest.fixture(scope="module")
def resolved(raw):
    return an.resolve_outcomes(raw)


# --- ingest -----------------------------------------------------------------


def test_dataset_shape(raw):
    assert len(raw) > 30_000
    assert raw.queue_year.min() >= 1970
    assert raw.queue_year.max() <= 2024


def test_excel_serial_dates_parsed(raw):
    """The single easiest way to corrupt this dataset.

    Read without an origin, these come through as float64 and every duration
    is NaN, which looks like missing data rather than a parsing bug.
    """
    assert pd.api.types.is_datetime64_any_dtype(raw.queue_date)
    assert raw.queue_date.notna().mean() > 0.95
    assert raw.queue_date.min() >= pd.Timestamp("1970-01-01")
    assert raw.queue_date.max() <= pd.Timestamp("2025-01-01")


def test_all_major_regions_present(raw):
    regions = set(raw.region.dropna())
    for expected in ("PJM", "CAISO", "ERCOT", "MISO", "NYISO", "ISO-NE", "SPP"):
        assert expected in regions


def test_capacity_decrease_requests_are_flagged(raw):
    """A few rows carry negative MW: capacity give-back requests, not errors.

    They must be flagged so a "total MW requested" figure can exclude them
    rather than letting them net out silently.
    """
    assert raw.is_capacity_decrease.sum() > 0
    assert (raw.loc[raw.is_capacity_decrease, "capacity_mw"] < 0).all()
    additions = raw.loc[~raw.is_capacity_decrease, "capacity_mw"].dropna()
    assert additions.min() >= 0
    assert additions.sum() > 1_000_000  # over a TW of cumulative requests


def test_ppl_is_present(raw):
    """The utility this repo cares about most."""
    assert (raw.utility == "PPL").sum() > 100


def test_project_id_round_trips_through_parquet(raw, tmp_path):
    dest = tmp_path / "t.parquet"
    raw.head(500).to_parquet(dest, index=False)
    assert len(pd.read_parquet(dest)) == 500


def test_coverage_report_flags_sparse_dates(raw):
    cov = ingest.coverage_report(raw)
    by_col = cov.set_index("column").coverage_pct
    assert by_col["queue_date"] > 95
    assert by_col["actual_cod_date"] < 20


# --- outcome resolution -----------------------------------------------------


def test_outcome_comes_from_status_not_dates(raw, resolved):
    """About half of withdrawn projects have no withdrawal date.

    Classifying those as still-waiting because a date is missing would
    understate the withdrawal rate roughly twofold. This test pins that.
    """
    status_withdrawn = (raw.status == ingest.WITHDRAWN).sum()
    outcome_withdrawn = (resolved.outcome == "withdrawn").sum()
    assert outcome_withdrawn == status_withdrawn
    dated = resolved[resolved.outcome == "withdrawn"].withdrawal_date.notna().mean()
    assert dated < 0.75  # the gap this test exists to protect


def test_outcomes_partition_the_dataset(raw, resolved):
    assert len(resolved) == len(raw)
    assert set(resolved.outcome) <= {"operational", "withdrawn", "active", "suspended"}


def test_terminal_events_flagged(resolved):
    assert resolved.loc[resolved.outcome == "operational", "terminal_event"].all()
    assert not resolved.loc[resolved.outcome == "active", "terminal_event"].any()


def test_durations_are_sane(resolved):
    d = resolved.duration_years.dropna()
    assert d.min() >= 0
    assert d.max() <= 30


def test_timing_known_is_a_subset(resolved):
    assert resolved.timing_known.sum() < len(resolved)
    assert resolved.loc[resolved.timing_known, "duration_years"].notna().all()


# --- survival math ----------------------------------------------------------


def test_kaplan_meier_no_censoring_matches_empirical():
    """With every observation an event, survival is just the empirical tail."""
    durations = np.array([1.0, 2.0, 3.0, 4.0])
    events = np.ones(4)
    km = an.kaplan_meier(durations, events)
    assert km.survival.iloc[0] == pytest.approx(0.75)
    assert km.survival.iloc[-1] == pytest.approx(0.0)


def test_kaplan_meier_censoring_raises_survival():
    """Censored observations must not be counted as events."""
    d = np.array([1.0, 2.0, 3.0, 4.0])
    all_events = an.kaplan_meier(d, np.ones(4))
    some_censored = an.kaplan_meier(d, np.array([1, 1, 1, 0]))
    assert all_events.survival.iloc[-1] == pytest.approx(0.0)
    assert some_censored.survival.iloc[-1] == pytest.approx(0.25)


def test_kaplan_meier_is_monotonic_decreasing():
    rng = np.random.default_rng(0)
    d = rng.uniform(0, 10, 200)
    e = rng.integers(0, 2, 200)
    km = an.kaplan_meier(d, e)
    assert (km.survival.diff().dropna() <= 1e-12).all()


def test_cumulative_incidence_is_monotonic(resolved):
    pjm = an.mature_cohorts(resolved[resolved.region == "PJM"])
    inc = an.cumulative_incidence(pjm, "operational", horizon_years=15.0, steps=30)
    assert (inc.cumulative_incidence.diff().dropna() >= -1e-12).all()


def test_competing_incidences_sum_below_one(resolved):
    """Completion and withdrawal cannot together exceed the whole cohort."""
    pjm = an.mature_cohorts(resolved[resolved.region == "PJM"])
    op = an.cumulative_incidence(pjm, "operational", 20.0, 20).cumulative_incidence.iloc[-1]
    wd = an.cumulative_incidence(pjm, "withdrawn", 20.0, 20).cumulative_incidence.iloc[-1]
    assert 0 <= op + wd <= 1.0


def test_maturity_filter_drops_recent_cohorts(resolved):
    mature = an.mature_cohorts(resolved, maturity_years=5)
    assert mature.queue_year.max() <= 2019
    assert len(mature) < len(resolved)


# --- the headline finding ---------------------------------------------------


def test_no_pre2020_cohort_reaches_half_completion(resolved):
    """The core result, and it needs no dates: status covers every row."""
    cohorts = an.cohort_outcomes(resolved)
    pre2020 = cohorts[cohorts.cohort_start < 2020]
    assert len(pre2020) >= 5
    assert (pre2020.completion_rate < 0.5).all()


def test_no_pre2020_cohort_can_reach_half(resolved):
    """Even if every project still waiting completed. The robust upper bound."""
    cohorts = an.cohort_outcomes(resolved)
    pre2020 = cohorts[cohorts.cohort_start < 2020]
    ceiling = pre2020.completion_rate + pre2020.still_open_rate
    assert (ceiling < 0.5).all()


def test_completed_only_median_still_returns_a_number(resolved):
    """The statistic people quote exists even where no median wait does."""
    cohorts = an.cohort_outcomes(resolved)
    assert cohorts.naive_median_years.notna().all()


def test_cohort_shares_partition(resolved):
    cohorts = an.cohort_outcomes(resolved)
    total = cohorts.completion_rate + cohorts.withdrawal_rate + cohorts.still_open_rate
    assert np.allclose(total, 1.0, atol=1e-9)


def test_realtime_median_reads_low_before_resolution(resolved):
    """Right-truncation: read at the close of the entry window, it reads low."""
    bt = an.realtime_backtest(resolved)
    at_close = bt[bt.years_after_close == 0]
    assert len(at_close) == len(an.BACKTEST_COHORTS)
    assert (at_close.understatement > 1.4).all()


def test_realtime_median_converges_as_window_extends(resolved):
    """The truncation must shrink as the cohort resolves, or it is not truncation."""
    bt = an.realtime_backtest(resolved)
    for _, g in bt.groupby("cohort_start"):
        g = g.sort_values("years_after_close")
        assert g.n_completed_seen.is_monotonic_increasing
        assert g.understatement.iloc[-1] < 1.05
        assert g.understatement.iloc[-1] < g.understatement.iloc[0]


def test_backtest_refuses_unresolved_cohort(resolved):
    """A cohort without 10 years to resolve has no trustworthy full-record median."""
    with pytest.raises(ValueError):
        an.realtime_backtest(resolved, cohorts=(2015,))


def test_cumulative_incidence_approaches_lifetime_share(resolved):
    """CIF must end near the status-based share for a resolved cohort.

    An earlier version kept undated outcomes in the denominator with no way into
    the numerator, and ended at roughly half the true share.
    """
    cohort = resolved[(resolved.queue_year // 5 * 5) == 2005]
    share = (cohort.outcome == "operational").mean()
    cif = an.cumulative_incidence(cohort, "operational", horizon_years=19.0, steps=20)
    end = cif.cumulative_incidence.iloc[-1]
    assert end <= share + 1e-12
    assert end > 0.95 * share


def test_retracted_km_median_came_from_censoring_withdrawals(resolved):
    """Pins the retraction in FINDINGS.md so it cannot quietly drift.

    The retracted headline was a Kaplan-Meier fit on time-to-completion with
    withdrawn projects treated as censored. This reproduces its 15.06 yr figure
    for the 2005-09 cohort, then shows the competing-risks view: completion
    probability never reaches one half, so no median exists at all.
    """
    cohort = resolved[(resolved.queue_year // 5 * 5) == 2005]
    timed = cohort[cohort.timing_known]
    events = (timed.outcome == "operational").astype(int).to_numpy()
    assert (timed.outcome == "withdrawn").sum() > 1000  # all treated as censored

    km = an.kaplan_meier(timed.duration_years.to_numpy(), events)
    retracted = float(km[km.survival <= 0.5].time_years.iloc[0])
    assert retracted == pytest.approx(15.06, abs=0.01)

    cif = an.cumulative_incidence(cohort, "operational", horizon_years=19.0, steps=40)
    assert cif.cumulative_incidence.max() < 0.5


def test_withdrawal_is_the_modal_outcome(resolved):
    mature = an.mature_cohorts(resolved)
    shares = mature.outcome.value_counts(normalize=True)
    assert shares.idxmax() == "withdrawn"
    assert shares["withdrawn"] > shares["operational"]


def test_completion_rate_declines_over_time(resolved):
    rates = an.completion_rates(resolved)
    early = rates[rates.queue_year.between(2000, 2007)].operational.mean()
    late = rates[rates.queue_year.between(2012, 2019)].operational.mean()
    assert late < early


def test_by_resource_covers_major_types(resolved):
    res = an.by_resource(resolved)
    groups = set(res.resource_group)
    assert {"Solar", "Wind", "Gas", "Storage"} <= groups
    assert res.completion_rate.between(0, 1).all()


def test_by_region_rates_are_shares(resolved):
    reg = an.by_region(resolved)
    assert reg.completion_rate.between(0, 1).all()
    assert (reg.completion_rate + reg.withdrawal_rate <= 1.0 + 1e-9).all()
    assert "PJM" in set(reg.region)


def test_queue_growth_increases(resolved):
    growth = an.queue_growth(resolved)
    early = growth[growth.queue_year.between(2000, 2005)].n_requests.mean()
    late = growth[growth.queue_year.between(2019, 2024)].n_requests.mean()
    assert late > early * 2
