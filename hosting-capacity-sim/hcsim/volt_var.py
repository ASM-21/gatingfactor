"""Smart inverter volt-var control, IEEE 1547-2018 Category B default curve.

The curve is piecewise linear in per-unit voltage, with reactive power given as
a fraction of inverter nameplate apparent power:

    V <= 0.92        Q = +0.44   (inject vars, hold voltage up)
    0.92 -> 0.98     ramp to 0
    0.98 -> 1.02     Q = 0       (deadband)
    1.02 -> 1.08     ramp to -0.44
    V >= 1.08        Q = -0.44   (absorb vars, pull voltage down)

Sign convention matches pandapower sgen: positive q_mvar injects reactive power.

**The apparent-power limit is enforced.** An inverter rated S kVA producing P kW
can supply at most sqrt(S^2 - P^2) kvar. Real power has priority (the DER
output is fixed by the scenario), so the curve's commanded Q is clipped to that
headroom. An earlier version of this module documented this constraint but
never applied it, and every inverter in the published volt-var result ran up to
2.4% over its kVA rating. That inflated the headline uplift; see FINDINGS.md.

**Default sizing is the Category B minimum.** To deliver the full 44% var
absorption at rated real power, an inverter needs S/P of at least
1 / sqrt(1 - 0.44^2) = 1.1136. That is arithmetic from the Category B
capability in IEEE 1547-2018 Table 7, not an empirical assumption, and it is
the smallest sizing at which "Category B volt-var" means what it says. At
S/P = 1.0 the inverter has no var headroom at full output and volt-var cannot
do anything, which `run_analysis.py --stage sizing` shows directly.

Because Q depends on voltage and voltage depends on Q, this needs an outer
iteration around the power flow. A damped fixed-point iteration is used, which
is what real quasi-static time-series tools do and is stable for the feeders
here. Oscillation is possible on very weak feeders, so convergence is reported
rather than assumed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandapower as pp

# (voltage_pu, q_fraction_of_nameplate)
CATEGORY_B_CURVE: tuple[tuple[float, float], ...] = (
    (0.92, 0.44),
    (0.98, 0.00),
    (1.02, 0.00),
    (1.08, -0.44),
)

CATEGORY_B_Q_FRACTION = 0.44

# Smallest S/P at which the full Category B var capability is available at
# rated real power: P^2 + (0.44 S)^2 <= S^2  =>  S/P >= 1/sqrt(1 - 0.44^2).
CATEGORY_B_MIN_OVERSIZE = 1.0 / math.sqrt(1.0 - CATEGORY_B_Q_FRACTION**2)


@dataclass
class VoltVarResult:
    converged: bool
    iterations: int
    max_q_change_mvar: float
    # Max over inverters of sqrt(P^2 + Q^2) / S. Must never exceed 1.
    max_s_utilization: float = 0.0


def q_target_mvar(vm_pu: float, s_rated_mva: float) -> float:
    """Reactive output commanded by the Category B curve at a given voltage.

    This is the curve alone, before the apparent-power limit is applied.
    """
    volts = [pt[0] for pt in CATEGORY_B_CURVE]
    fracs = [pt[1] for pt in CATEGORY_B_CURVE]
    frac = float(np.interp(vm_pu, volts, fracs))
    return frac * s_rated_mva


def q_available_mvar(p_mw: np.ndarray, s_rated_mva: np.ndarray) -> np.ndarray:
    """Reactive headroom left after real power: sqrt(S^2 - P^2), floored at 0."""
    p = np.asarray(p_mw, dtype=float)
    s = np.asarray(s_rated_mva, dtype=float)
    return np.sqrt(np.clip(s**2 - p**2, 0.0, None))


def s_utilization(net, inverter_oversize: float) -> float:
    """Worst-case apparent power over rating across all sgens on a solved net."""
    if len(net.sgen) == 0:
        return 0.0
    p = net.sgen["p_mw"].to_numpy()
    q = net.sgen["q_mvar"].to_numpy()
    s_rated = p * inverter_oversize
    with np.errstate(divide="ignore", invalid="ignore"):
        util = np.where(s_rated > 0, np.sqrt(p**2 + q**2) / s_rated, 0.0)
    return float(util.max())


def solve(
    net,
    enabled: bool = True,
    inverter_oversize: float = CATEGORY_B_MIN_OVERSIZE,
    damping: float = 0.5,
    tol_mvar: float = 1e-5,
    max_iter: int = 40,
) -> VoltVarResult:
    """Run power flow, optionally with volt-var control on all sgens.

    ``inverter_oversize`` is inverter nameplate apparent power as a multiple of
    the DER's rated real power. At 1.0 the inverter is sized exactly to its real
    output and has no reactive headroom at full power, so volt-var is inert. The
    default is the Category B minimum, 1.1136.
    """
    if inverter_oversize < 1.0:
        raise ValueError("inverter_oversize must be >= 1.0; an inverter cannot be rated below its real output")

    if len(net.sgen) == 0 or not enabled:
        if len(net.sgen):
            net.sgen.loc[:, "q_mvar"] = 0.0
        pp.runpp(net, calculate_voltage_angles=True, init="flat")
        return VoltVarResult(converged=True, iterations=1, max_q_change_mvar=0.0)

    p = net.sgen["p_mw"].to_numpy()
    s_rated = p * inverter_oversize
    q_cap = q_available_mvar(p, s_rated)

    net.sgen.loc[:, "q_mvar"] = 0.0
    pp.runpp(net, calculate_voltage_angles=True, init="flat")

    max_change = float("inf")
    for it in range(1, max_iter + 1):
        buses = net.sgen["bus"].to_numpy()
        vm = net.res_bus.loc[buses, "vm_pu"].to_numpy()
        target = np.array([q_target_mvar(v, s) for v, s in zip(vm, s_rated)])
        target = np.clip(target, -q_cap, q_cap)

        current = net.sgen["q_mvar"].to_numpy()
        updated = current + damping * (target - current)
        max_change = float(np.max(np.abs(updated - current))) if len(updated) else 0.0

        net.sgen.loc[:, "q_mvar"] = updated
        pp.runpp(net, calculate_voltage_angles=True, init="results")

        if max_change < tol_mvar:
            return VoltVarResult(
                converged=True,
                iterations=it,
                max_q_change_mvar=max_change,
                max_s_utilization=s_utilization(net, inverter_oversize),
            )

    return VoltVarResult(
        converged=False,
        iterations=max_iter,
        max_q_change_mvar=max_change,
        max_s_utilization=s_utilization(net, inverter_oversize),
    )
