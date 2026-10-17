"""Tests for tariff-explorer.

Focus is on billing determinants that are easy to get subtly wrong: monthly
tier resets, demand assessed on the monthly maximum, export credited at the
right rate, and minimum bills that raise a bill without ever refunding.
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
sys.path.insert(0, str(REPO / "tariff-explorer"))

from shared import loadshapes  # noqa: E402
from texplorer import archetypes as ar, tariffs as tf  # noqa: E402


@pytest.fixture(scope="module")
def ts():
    return loadshapes.hourly_index(2021)


@pytest.fixture(scope="module")
def archetypes():
    return ar.build_archetypes(2021)


# --- load shapes ------------------------------------------------------------


def test_shapes_hit_annual_targets(ts):
    assert loadshapes.residential(ts, annual_kwh=10_500).sum() == pytest.approx(10_500, rel=1e-6)
    assert loadshapes.all_electric(ts, annual_kwh=16_000).sum() == pytest.approx(16_000, rel=1e-6)
    assert loadshapes.commercial_flat(ts, annual_kwh=120_000).sum() == pytest.approx(120_000, rel=1e-6)


def test_all_shapes_non_negative(ts):
    for fn in (loadshapes.residential, loadshapes.all_electric,
               loadshapes.commercial_daytime, loadshapes.commercial_flat):
        assert fn(ts).min() >= 0.0


def test_pv_is_zero_at_night(ts):
    pv = loadshapes.pv_generation(ts, capacity_kw=7.0)
    hours = pd.DatetimeIndex(ts).hour
    assert pv[(hours >= 1) & (hours <= 3)].max() == pytest.approx(0.0, abs=1e-9)
    assert pv[(hours >= 11) & (hours <= 13)].mean() > 0


def test_pv_summer_exceeds_winter(ts):
    pv = loadshapes.pv_generation(ts, capacity_kw=7.0)
    month = pd.DatetimeIndex(ts).month
    assert pv[month == 6].sum() > pv[month == 12].sum()


def test_all_electric_is_winter_peaking(ts):
    load = loadshapes.all_electric(ts)
    month = pd.DatetimeIndex(ts).month
    assert load[month == 1].sum() > load[month == 6].sum()


def test_commercial_daytime_is_peakier_than_flat(ts):
    day = loadshapes.commercial_daytime(ts)
    flat = loadshapes.commercial_flat(ts)
    assert day.max() > flat.max()


def test_managed_ev_shifts_later(ts):
    unmanaged = loadshapes.ev_charging(ts, managed=False)
    managed = loadshapes.ev_charging(ts, managed=True)
    hours = pd.DatetimeIndex(ts).hour
    evening = (hours >= 18) & (hours < 22)
    assert managed[evening].sum() < unmanaged[evening].sum()
    assert managed.sum() == pytest.approx(unmanaged.sum(), rel=0.15)


def test_cader_profile_matches_shared(ts):
    """The two tracks must not drift on what a household is."""
    sys.path.insert(0, str(REPO / "carbon-aware-der"))
    from cader import data as cd

    assert np.array_equal(
        cd.HouseholdProfile().series(ts), loadshapes.residential(ts)
    )


# --- billing mechanics ------------------------------------------------------


def test_flat_bill_is_rate_times_energy(ts):
    load = np.full(len(ts), 1.0)
    t = tf.FlatRate(rate=0.10, fixed_monthly=0.0)
    b = t.annual(ts, load)
    assert b.energy == pytest.approx(0.10 * load.sum())


def test_fixed_charge_applied_monthly(ts):
    load = np.full(len(ts), 1.0)
    t = tf.FlatRate(rate=0.10, fixed_monthly=10.0)
    assert t.annual(ts, load).fixed == pytest.approx(120.0)


def test_demand_uses_monthly_max_not_annual_max(ts):
    """Twelve monthly peaks must be billed, not one annual peak."""
    load = np.full(len(ts), 1.0)
    idx = pd.DatetimeIndex(ts)
    load[idx.month == 7] = 5.0  # one spiky month
    t = tf.DemandChargeRate(rate=0.0, demand_rate_per_kw=10.0, fixed_monthly=0.0)
    b = t.annual(ts, load)
    # 11 months at 1 kW plus 1 month at 5 kW, times $10.
    assert b.demand == pytest.approx(10.0 * (11 * 1.0 + 5.0))


def test_tiers_reset_each_month(ts):
    """A customer just over tier 1 every month must not be pushed into tier 3."""
    load = np.full(len(ts), 600.0 / (24 * 30))  # about 600 kWh/month
    t = tf.TieredRate(
        tiers=[(500.0, 0.10), (1000.0, 0.20), (float("inf"), 0.40)],
        fixed_monthly=0.0,
    )
    b = t.annual(ts, load)
    # Should never reach the 0.40 tier if tiers reset monthly.
    blended = b.energy / b.consumption_kwh
    assert blended < 0.20


def test_tiered_is_more_expensive_per_kwh_at_higher_usage(ts):
    t = tf.TieredRate(fixed_monthly=0.0)
    low = t.annual(ts, np.full(len(ts), 0.3))
    high = t.annual(ts, np.full(len(ts), 3.0))
    assert high.effective_rate > low.effective_rate


def test_tou_charges_more_in_peak_hours(ts):
    idx = pd.DatetimeIndex(ts)
    t = tf.TOURate(fixed_monthly=0.0)
    rates = t.rate_at(idx)
    weekday = idx.dayofweek < 5
    assert rates[weekday & np.isin(idx.hour, t.on_peak_hours)].max() == t.on_peak
    assert rates[np.isin(idx.hour, t.off_peak_hours)].max() == t.off_peak


def test_weekend_is_off_peak(ts):
    idx = pd.DatetimeIndex(ts)
    t = tf.TOURate(weekend_off_peak=True)
    assert np.all(t.rate_at(idx)[idx.dayofweek >= 5] == t.off_peak)


def test_minimum_bill_raises_but_never_refunds(ts):
    tiny = np.full(len(ts), 0.001)
    t = tf.FlatRate(rate=0.10, fixed_monthly=0.0, minimum_monthly=15.0)
    b = t.annual(ts, tiny)
    assert b.total == pytest.approx(12 * 15.0)
    big = np.full(len(ts), 5.0)
    b2 = t.annual(ts, big)
    assert b2.minimum_adjustment == pytest.approx(0.0)


def test_net_metering_credits_at_retail(ts):
    load = np.full(len(ts), -1.0)  # pure export
    t = tf.FlatRate(rate=0.20, fixed_monthly=0.0, export_rate=None)
    b = t.annual(ts, load)
    assert b.export_credit == pytest.approx(0.20 * len(ts))


def test_net_billing_credits_at_lower_rate(ts):
    load = np.full(len(ts), -1.0)
    nem = tf.FlatRate(rate=0.20, fixed_monthly=0.0, export_rate=None)
    net_billing = tf.FlatRate(rate=0.20, fixed_monthly=0.0, export_rate=0.04)
    assert net_billing.annual(ts, load).export_credit < nem.annual(ts, load).export_credit


def test_demand_never_negative_on_export(ts):
    load = np.full(len(ts), -2.0)
    t = tf.DemandChargeRate(demand_rate_per_kw=10.0)
    assert t.annual(ts, load).demand == pytest.approx(0.0)


def test_scale_multiplies_volumetric_only(ts):
    load = np.full(len(ts), 1.0)
    t = tf.FlatRate(rate=0.10, fixed_monthly=10.0)
    base = t.annual(ts, load)
    scaled = t.with_scale(2.0).annual(ts, load)
    assert scaled.energy == pytest.approx(2 * base.energy)
    assert scaled.fixed == pytest.approx(base.fixed)


# --- archetypes and analysis ------------------------------------------------


def test_load_factor_ordering(archetypes):
    lf = {k: a.load_factor for k, a in archetypes.items()}
    assert lf["ev_home"] < lf["solar_home"]
    assert lf["commercial_flat"] > lf["commercial_daytime"]


def test_solar_reduces_energy_far_more_than_peak(archetypes):
    """The core reason a solar customer fares badly under a demand charge.

    PV offsets a large share of annual energy but barely touches the evening
    peak, which happens after sunset.
    """
    solar = archetypes["solar_home"]
    gross_peak = float(solar.load.max())
    energy_offset = 1 - solar.net_annual_kwh / solar.annual_kwh
    peak_offset = 1 - solar.peak_kw / gross_peak
    assert energy_offset > 0.5
    assert peak_offset < energy_offset


def test_revenue_neutral_scale_equalizes_revenue(archetypes):
    subset = {k: archetypes[k] for k in ("all_electric", "ev_home", "solar_home")}
    rn = ar.revenue_neutral_comparison(subset)
    totals = rn.groupby("tariff").annual_bill.sum()
    assert totals.max() - totals.min() < 0.02 * totals.mean()


def test_flat_is_its_own_baseline(archetypes):
    rn = ar.revenue_neutral_comparison(archetypes)
    flat = rn[rn.tariff == "flat"]
    assert np.allclose(flat.change_pct, 0.0, atol=1e-6)
    assert flat.scale.iloc[0] == pytest.approx(1.0, rel=1e-3)


def test_demand_charge_penalizes_low_load_factor(archetypes):
    subset = {k: archetypes[k] for k in ("commercial_daytime", "commercial_flat")}
    rn = ar.revenue_neutral_comparison(subset)
    d = rn[rn.tariff == "demand"].set_index("archetype")
    assert d.loc["commercial_daytime", "change_pct"] > d.loc["commercial_flat", "change_pct"]


def test_tou_favors_solar(archetypes):
    subset = {k: archetypes[k] for k in ("all_electric", "ev_home", "solar_home")}
    rn = ar.revenue_neutral_comparison(subset)
    tou = rn[rn.tariff == "tou"].set_index("archetype")
    assert tou.loc["solar_home", "change_pct"] < tou.loc["ev_home", "change_pct"]


def test_bill_matrix_covers_all_pairs(archetypes):
    m = ar.bill_matrix(archetypes)
    assert len(m) == len(archetypes) * len(tf.DEFAULT_TARIFFS)
    assert m.annual_bill.notna().all()
