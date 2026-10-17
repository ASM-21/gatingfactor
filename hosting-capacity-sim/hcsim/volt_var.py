"""Smart inverter volt-var control, IEEE 1547-2018 Category B default curve.

The curve is piecewise linear in per-unit voltage, with reactive power given as
a fraction of inverter nameplate apparent power:

    V <= 0.92        Q = +0.44   (inject vars, hold voltage up)
    0.92 -> 0.98     ramp to 0
    0.98 -> 1.02     Q = 0       (deadband)
    1.02 -> 1.08     ramp to -0.44
    V >= 1.08        Q = -0.44   (absorb vars, pull voltage down)

Sign convention matches pandapower sgen: positive q_mvar injects reactive power.

Because Q depends on voltage and voltage depends on Q, this needs an outer
iteration around the power flow. A damped fixed-point iteration is used, which
is what real quasi-static time-series tools do and is stable for the feeders
here. Oscillation is possible on very stiff curves, so the damping factor is
exposed and convergence is reported rather than assumed.
"""

from __future__ import annotations

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


@dataclass
class VoltVarResult:
    converged: bool
    iterations: int
    max_q_change_mvar: float


def q_target_mvar(vm_pu: float, s_rated_mva: float) -> float:
    """Reactive output commanded by the Category B curve at a given voltage."""
    volts = [pt[0] for pt in CATEGORY_B_CURVE]
    fracs = [pt[1] for pt in CATEGORY_B_CURVE]
    frac = float(np.interp(vm_pu, volts, fracs))
    return frac * s_rated_mva


def solve(
    net,
    enabled: bool = True,
    inverter_oversize: float = 1.0,
    damping: float = 0.5,
    tol_mvar: float = 1e-5,
    max_iter: int = 40,
) -> VoltVarResult:
    """Run power flow, optionally with volt-var control on all sgens.

    ``inverter_oversize`` sets nameplate apparent power as a multiple of rated
    real power. 1.0 means the inverter can only produce vars by backing off
    real power headroom it does not have, which is the conservative assumption;
    1.1 or so reflects a typical oversized inverter that can supply vars at
    full real output.
    """
    if len(net.sgen) == 0 or not enabled:
        pp.runpp(net, calculate_voltage_angles=True, init="flat")
        if len(net.sgen) and not enabled:
            net.sgen.loc[:, "q_mvar"] = 0.0
            pp.runpp(net, calculate_voltage_angles=True, init="flat")
        return VoltVarResult(converged=True, iterations=1, max_q_change_mvar=0.0)

    s_rated = net.sgen["p_mw"].to_numpy() * inverter_oversize
    net.sgen.loc[:, "q_mvar"] = 0.0
    pp.runpp(net, calculate_voltage_angles=True, init="flat")

    max_change = float("inf")
    for it in range(1, max_iter + 1):
        buses = net.sgen["bus"].to_numpy()
        vm = net.res_bus.loc[buses, "vm_pu"].to_numpy()
        target = np.array([q_target_mvar(v, s) for v, s in zip(vm, s_rated)])

        current = net.sgen["q_mvar"].to_numpy()
        updated = current + damping * (target - current)
        max_change = float(np.max(np.abs(updated - current))) if len(updated) else 0.0

        net.sgen.loc[:, "q_mvar"] = updated
        pp.runpp(net, calculate_voltage_angles=True, init="results")

        if max_change < tol_mvar:
            return VoltVarResult(converged=True, iterations=it, max_q_change_mvar=max_change)

    return VoltVarResult(converged=False, iterations=max_iter, max_q_change_mvar=max_change)
