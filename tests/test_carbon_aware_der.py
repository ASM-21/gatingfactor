"""Tests for carbon-aware-der.

These target the ways a dispatch model silently produces flattering results:
free energy from the battery, infeasible EV schedules, and objective weights
that do not actually change behavior.
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
sys.path.insert(0, str(REPO / "carbon-aware-der"))

from cader import data as cd, optimizer as op  # noqa: E402

HOURS = 24


@pytest.fixture(scope="module")
def dataset():
    return cd.build_dataset(2021)


@pytest.fixture
def toy():
    """A day with a deliberately strong, known carbon and price shape."""
    base = np.full(HOURS, 0.5)
    price = np.full(HOURS, 0.15)
    price[2:6] = 0.05  # cheap window
    price[14:18] = 0.30  # expensive window
    carbon = np.full(HOURS, 0.30)
    carbon[8:12] = 0.15  # clean window, deliberately NOT aligned with cheap window
    return base, price, carbon


# --- data integrity ---------------------------------------------------------


def test_carbon_units_match_repo_convention(dataset):
    """gCO2/kWh is numerically kg/MWh; the kg/kWh column must be 1/1000 of it."""
    row = dataset.iloc[0]
    assert row.carbon_kg_per_kwh == pytest.approx(row.carbon_g_per_kwh / 1000.0)


def test_carbon_intensity_physically_plausible(dataset):
    ci = dataset.carbon_g_per_kwh
    assert ci.min() > 50, "implausibly clean for PJM"
    assert ci.max() < 900, "implausibly dirty, above coal-only intensity"


def test_no_missing_hours(dataset):
    gaps = dataset.timestamp.diff().dropna()
    assert (gaps == gaps.mode()[0]).all()


def test_household_profile_hits_annual_target(dataset):
    assert dataset.base_load_kwh.sum() == pytest.approx(10_500, rel=0.02)


def test_tou_ordering():
    t = cd.TOUTariff()
    assert t.off_peak < t.mid_peak < t.on_peak


def test_daily_horizons_are_full_days(dataset):
    blocks = cd.daily_horizons(dataset)
    assert len(blocks) > 350
    assert all(len(b) == HOURS for b in blocks)
    assert all(b.hour.iloc[0] == cd.HORIZON_START_HOUR for b in blocks)


# --- battery physics --------------------------------------------------------


def test_one_way_efficiency_squares_to_roundtrip():
    b = op.Battery(efficiency_roundtrip=0.90)
    assert b.eta**2 == pytest.approx(0.90)


def test_terminal_soc_constraint_holds(toy):
    """The battery must not end the horizon below where it started.

    Without this the optimizer drains stored energy and books it as savings.
    """
    base, price, carbon = toy
    battery = op.Battery()
    for w in (0.0, 0.5, 1.0):
        res = op.dispatch(base, price, carbon, battery, op.EV(), weight_cost=w)
        assert res.solved
        assert res.soc[-1] >= battery.soc_init - 1e-6


def test_soc_stays_within_bounds(toy):
    base, price, carbon = toy
    battery = op.Battery()
    res = op.dispatch(base, price, carbon, battery, op.EV())
    assert res.soc.min() >= battery.soc_min - 1e-6
    assert res.soc.max() <= battery.capacity_kwh + 1e-6


def test_no_simultaneous_charge_and_discharge(toy):
    base, price, carbon = toy
    res = op.dispatch(base, price, carbon, op.Battery(), op.EV())
    assert np.all(res.battery_charge * res.battery_discharge < 1e-6)


def test_power_limits_respected(toy):
    base, price, carbon = toy
    battery = op.Battery()
    res = op.dispatch(base, price, carbon, battery, op.EV())
    assert res.battery_charge.max() <= battery.power_kw + 1e-6
    assert res.battery_discharge.max() <= battery.power_kw + 1e-6


def test_no_export(toy):
    base, price, carbon = toy
    res = op.dispatch(base, price, carbon, op.Battery(), op.EV())
    assert res.net_load.min() >= -1e-6


# --- EV ---------------------------------------------------------------------


def test_ev_energy_requirement_met(toy):
    base, price, carbon = toy
    ev = op.EV(energy_kwh=12.0)
    res = op.dispatch(base, price, carbon, op.Battery(), ev)
    assert res.ev_charge.sum() == pytest.approx(12.0, rel=1e-4)


def test_ev_charges_only_inside_window(toy):
    base, price, carbon = toy
    ev = op.EV()
    res = op.dispatch(base, price, carbon, op.Battery(), ev)
    outside = [t for t in range(HOURS) if t not in ev.window(HOURS)]
    assert np.allclose(res.ev_charge[outside], 0.0, atol=1e-6)


def test_infeasible_ev_raises(toy):
    base, price, carbon = toy
    impossible = op.EV(energy_kwh=500.0, power_kw=1.0)
    with pytest.raises(ValueError):
        op.dispatch(base, price, carbon, op.Battery(), impossible)


def test_unmanaged_baseline_charges_immediately():
    base = np.full(HOURS, 0.5)
    ev = op.EV(energy_kwh=12.0, power_kw=11.5)
    res = op.unmanaged(base, np.full(HOURS, 0.15), np.full(HOURS, 0.3), ev)
    assert res.ev_charge[ev.plug_in_index] == pytest.approx(11.5)
    assert res.ev_charge.sum() == pytest.approx(12.0)


# --- objective behavior -----------------------------------------------------


def test_cost_objective_beats_carbon_objective_on_cost(toy):
    base, price, carbon = toy
    cost_opt, carbon_opt = op.anchors(base, price, carbon, op.Battery(), op.EV())
    assert cost_opt.cost <= carbon_opt.cost + 1e-6


def test_carbon_objective_beats_cost_objective_on_carbon(toy):
    base, price, carbon = toy
    cost_opt, carbon_opt = op.anchors(base, price, carbon, op.Battery(), op.EV())
    assert carbon_opt.carbon_kg <= cost_opt.carbon_kg + 1e-6


def test_objectives_actually_diverge_when_signals_conflict(toy):
    """The toy day puts the cheap window and the clean window in different hours.

    If the two objectives produce identical dispatch here, the weight is not
    wired into the problem.
    """
    base, price, carbon = toy
    cost_opt, carbon_opt = op.anchors(base, price, carbon, op.Battery(), op.EV())
    assert not np.allclose(cost_opt.net_load, carbon_opt.net_load, atol=1e-3)


def test_optimizer_beats_unmanaged_on_its_own_objective(toy):
    base, price, carbon = toy
    ev = op.EV()
    un = op.unmanaged(base, price, carbon, ev)
    cost_opt, carbon_opt = op.anchors(base, price, carbon, op.Battery(), ev)
    assert cost_opt.cost <= un.cost + 1e-6
    assert carbon_opt.carbon_kg <= un.carbon_kg + 1e-6


def test_lp_relaxation_matches_milp(toy):
    """With round-trip efficiency below 1, the exclusivity binary is not binding.

    If these diverge, the relaxation is unsafe and the fast path must not be used.
    """
    base, price, carbon = toy
    strict = op.dispatch(base, price, carbon, op.Battery(), op.EV(), relax=False)
    loose = op.dispatch(base, price, carbon, op.Battery(), op.EV(), relax=True)
    assert loose.cost == pytest.approx(strict.cost, rel=1e-4)


def test_weight_normalization_is_scale_invariant(toy):
    """Passing references must not change the physical dispatch at the extremes."""
    base, price, carbon = toy
    plain = op.dispatch(base, price, carbon, op.Battery(), op.EV(), weight_cost=1.0)
    scaled = op.dispatch(
        base, price, carbon, op.Battery(), op.EV(),
        weight_cost=1.0, cost_ref=plain.cost, carbon_ref=100.0,
    )
    assert scaled.cost == pytest.approx(plain.cost, rel=1e-4)


def test_bigger_battery_never_hurts(toy):
    base, price, carbon = toy
    small = op.dispatch(base, price, carbon, op.Battery(capacity_kwh=5.0), op.EV())
    big = op.dispatch(base, price, carbon, op.Battery(capacity_kwh=20.0), op.EV())
    assert big.cost <= small.cost + 1e-4


# --- marginal emissions -----------------------------------------------------


from cader import marginal as cm, signal_choice as sc  # noqa: E402


@pytest.fixture(scope="module")
def fit():
    return cm.estimate()


@pytest.fixture(scope="module")
def marginal_ds(fit):
    return cm.attach_marginal(cd.build_dataset(2021), fit)


def test_fuel_mix_totals_are_positive():
    df = cm.load_fuel_mix()
    assert (df.total_mw > 0).all()
    assert df.renewable_mw.min() >= 0


def test_renewable_control_improves_fit(fit):
    """The whole justification for the control term."""
    assert fit.pooled_r2 > fit.pooled_r2_uncontrolled


def test_renewable_coefficient_is_negative(fit):
    """A MWh of renewable ramp must displace fossil, so the sign must be negative.

    A positive coefficient would mean renewables raise emissions, which would
    indicate the regression is picking up something other than dispatch.
    """
    assert fit.renewable_coef < 0


def test_marginal_exceeds_average(fit, marginal_ds):
    """In a fossil-margin grid like PJM the marginal unit is dirtier than the mean."""
    avg = marginal_ds.carbon_kg_per_kwh.mean() * 1000
    mrg = marginal_ds.marginal_kg_per_kwh.mean() * 1000
    assert mrg > avg


def test_marginal_factor_physically_plausible(fit):
    """Bounded below by combined-cycle gas, above by coal."""
    assert 250 < fit.pooled_mef < 1000
    assert fit.table.mef_kg_per_mwh.between(150, 1200).all()


def test_bins_cover_all_hours_and_seasons(fit):
    assert set(fit.table.hour) == set(range(24))
    assert set(fit.table.season) == {0, 1, 2, 3}


def test_signals_are_anticorrelated(marginal_ds):
    """The core empirical claim of finding 5."""
    stats = cm.signal_comparison(marginal_ds)
    assert stats["profile_correlation"] < -0.3


def test_marginal_signal_is_stronger(marginal_ds):
    stats = cm.signal_comparison(marginal_ds)
    assert stats["signal_strength_ratio"] > 2.0


def test_attach_marginal_units_match_average(marginal_ds):
    """Both carbon columns must be kg/kWh so the optimizer can swap them freely."""
    assert marginal_ds.marginal_kg_per_kwh.between(0.1, 1.2).all()
    assert marginal_ds.carbon_kg_per_kwh.between(0.1, 1.2).all()


def test_lookup_falls_back_to_pooled(fit):
    out = fit.lookup(np.array([99]), np.array([99]))
    assert out[0] == pytest.approx(fit.pooled_mef)


# --- signal choice ----------------------------------------------------------


def test_optimizing_on_marginal_beats_optimizing_on_average(marginal_ds):
    """The headline claim, checked on a sample of days rather than the full year."""
    sample = cd.daily_horizons(marginal_ds)[::30]
    avg_score = mrg_score = 0.0
    for block in sample:
        base = block.base_load_kwh.to_numpy()
        price = block.price_per_kwh.to_numpy()
        avg = block.carbon_kg_per_kwh.to_numpy()
        mrg = block.marginal_kg_per_kwh.to_numpy()
        on_avg = op.dispatch(base, price, avg, op.Battery(), op.EV(), weight_cost=0.0)
        on_mrg = op.dispatch(base, price, mrg, op.Battery(), op.EV(), weight_cost=0.0)
        avg_score += float(np.dot(mrg, on_avg.net_load))
        mrg_score += float(np.dot(mrg, on_mrg.net_load))
    assert mrg_score < avg_score


def test_summarize_has_zero_baseline():
    results = pd.DataFrame(
        {
            "date": ["d1"] * 2,
            "month": [1] * 2,
            "strategy": ["unmanaged", "cost"],
            "cost": [10.0, 8.0],
            "avg_carbon_kg": [5.0, 5.5],
            "marginal_carbon_kg": [6.0, 7.0],
            "grid_kwh": [30.0, 30.0],
        }
    )
    s = sc.summarize(results)
    assert s.loc["unmanaged", "cost_change_pct"] == pytest.approx(0.0)
    assert s.loc["cost", "cost_change_pct"] == pytest.approx(-20.0)
    assert s.loc["cost", "marginal_carbon_change_pct"] > 0
