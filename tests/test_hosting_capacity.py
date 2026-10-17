"""Tests for hosting-capacity-sim.

These check physics and screening semantics, not just that the code runs.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "hosting-capacity-sim"))

from hcsim import feeders, hosting_capacity as hc, screens, volt_var  # noqa: E402


# --- feeder construction ----------------------------------------------------


@pytest.mark.parametrize("name", list(feeders.SPECS))
def test_feeder_is_radial(name):
    """A radial feeder has exactly one fewer line than buses."""
    net = feeders.build(name)
    assert len(net.line) == len(net.bus) - 1


@pytest.mark.parametrize("name", list(feeders.SPECS))
def test_peak_voltage_within_range_a(name):
    """With no DER at full load, the feeder must already be in spec.

    A model that violates ANSI Range A before any DER is added is broken, and
    every hosting capacity number computed from it would be meaningless.
    """
    res = hc.evaluate_penetration(feeders.SPECS[name], 0.0, load_scale=1.0)
    assert res is not None
    assert res.voltage_ok, f"{name} out of Range A at peak with no DER: {res.min_vm_pu}"


@pytest.mark.parametrize("name", list(feeders.SPECS))
def test_no_der_passes_all_screens(name):
    res = hc.evaluate_penetration(feeders.SPECS[name], 0.0)
    assert res.all_ok


def test_load_scale_reduces_demand():
    full = feeders.build("suburban", load_scale=1.0)
    light = feeders.build("suburban", load_scale=0.3)
    assert light.load.p_mw.sum() == pytest.approx(0.3 * full.load.p_mw.sum())


# --- volt-var curve ---------------------------------------------------------


def test_volt_var_deadband_produces_no_reactive_power():
    for v in (0.98, 1.00, 1.02):
        assert volt_var.q_target_mvar(v, 1.0) == pytest.approx(0.0)


def test_volt_var_absorbs_at_high_voltage():
    """Above the deadband the inverter must absorb (negative q) to pull V down."""
    assert volt_var.q_target_mvar(1.08, 1.0) == pytest.approx(-0.44)
    assert volt_var.q_target_mvar(1.05, 1.0) < 0


def test_volt_var_injects_at_low_voltage():
    assert volt_var.q_target_mvar(0.92, 1.0) == pytest.approx(0.44)
    assert volt_var.q_target_mvar(0.95, 1.0) > 0


def test_volt_var_curve_is_monotonic_decreasing():
    vs = [0.90, 0.94, 0.98, 1.00, 1.02, 1.05, 1.10]
    qs = [volt_var.q_target_mvar(v, 1.0) for v in vs]
    assert all(a >= b for a, b in zip(qs, qs[1:]))


def test_volt_var_solve_converges():
    net = feeders.build("suburban", load_scale=0.3)
    hc.place_der(net, {5: 1.0, 10: 1.0})
    result = volt_var.solve(net, enabled=True)
    assert result.converged


# --- screen semantics -------------------------------------------------------


def test_reverse_power_excluded_from_headline_capacity():
    """Regression guard on the taxonomy.

    If reverse_power ever gets folded back into PHYSICAL_SCREENS, every
    feeder's hosting capacity collapses to its minimum daytime load and the
    model stops being informative. This test pins that decision.
    """
    assert "reverse_power" not in screens.PHYSICAL_SCREENS
    assert "reverse_power" in screens.OPERATIONAL_SCREENS


def test_paper_screens_are_not_physical():
    for name in screens.PAPER_SCREENS:
        assert name not in screens.PHYSICAL_SCREENS


def test_fast_track_threshold_is_15_percent():
    res = hc.search("suburban", tol_mw=0.1)
    assert res.limit_penetration_15_mw == pytest.approx(0.15 * res.peak_load_mw, rel=1e-6)


def test_min_daytime_limit_matches_spec():
    spec = feeders.SPECS["rural"]
    res = hc.search("rural", tol_mw=0.1)
    expected = spec.peak_load_mw * spec.min_daytime_load_frac
    assert res.limit_min_daytime_mw == pytest.approx(expected, rel=1e-3)


# --- allocation -------------------------------------------------------------


def test_distributed_allocation_conserves_total():
    alloc = hc.allocate([1, 2, 3, 4], 8.0, "distributed")
    assert sum(alloc.values()) == pytest.approx(8.0)
    assert len(alloc) == 4


def test_concentrated_allocation_uses_one_bus():
    alloc = hc.allocate([1, 2, 3, 4], 8.0, "concentrated_end")
    assert alloc == {4: 8.0}


def test_unknown_strategy_raises():
    with pytest.raises(ValueError):
        hc.allocate([1, 2], 1.0, "nonsense")


# --- physics of the result --------------------------------------------------


def test_end_siting_never_beats_mid_siting_on_weak_feeder():
    """Voltage rise scales with impedance to the point of injection."""
    end = hc.search("rural", "concentrated_end", tol_mw=0.05).hosting_capacity_mw
    mid = hc.search("rural", "concentrated_mid", tol_mw=0.05).hosting_capacity_mw
    assert end < mid


def test_volt_var_does_not_hurt_a_voltage_limited_feeder():
    off = hc.search("suburban", "distributed", use_volt_var=False, tol_mw=0.05)
    on = hc.search("suburban", "distributed", use_volt_var=True, tol_mw=0.05)
    assert off.binding_screen == "voltage"
    assert on.hosting_capacity_mw > off.hosting_capacity_mw


def test_urban_feeder_is_thermally_limited():
    res = hc.search("urban", "distributed", tol_mw=0.05)
    assert res.binding_screen == "thermal"


def test_hosting_capacity_ordering_follows_feeder_stiffness():
    caps = {
        name: hc.search(name, "distributed", tol_mw=0.05).hosting_capacity_mw
        for name in ("rural", "suburban", "urban")
    }
    assert caps["rural"] < caps["suburban"] < caps["urban"]


def test_nodal_capacity_decreases_with_distance():
    """On a radial feeder, farther from the substation means weaker."""
    nodal = hc.nodal_map("suburban", tol_mw=0.1)
    buses = sorted(nodal)
    first, last = nodal[buses[0]], nodal[buses[-1]]
    assert last < first


@pytest.mark.parametrize("name", list(feeders.SPECS))
def test_bisection_assumption_holds(name):
    assert hc.verify_monotonic(name, upper_mw=8.0, steps=20)
