"""Hosting capacity search.

The headline number reported here is the voltage- and thermal-limited hosting
capacity: the largest aggregate DER nameplate, in MW, that can be added before
a real equipment limit is exceeded. That matches how published utility hosting
capacity maps define the term.

Every other screen is reported as its own limit alongside it, rather than being
folded into a single pass/fail. Which screen binds first is the interesting
engineering result, and the screens have genuinely different meanings: a feeder
that trips only the 15%-of-peak Fast Track threshold is a scheduling and
paperwork problem, while one that trips a thermal limit is a capital problem.

Method is bisection on total DER MW. Bisection assumes the pass/fail boundary
is monotonic in DER size, which holds for voltage and thermal screens on a
radial feeder. ``verify_monotonic`` checks that assumption by brute-force sweep
rather than trusting it silently.

Hosting capacity is assessed at minimum daytime load, the condition under which
net export and therefore voltage rise is worst. This matches utility practice.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field

import numpy as np
import pandapower as pp

from . import feeders, screens, volt_var

STRATEGIES = ("distributed", "concentrated_end", "concentrated_mid")


@dataclass
class CapacityResult:
    """Hosting capacity for one (feeder, strategy, volt-var) configuration."""

    feeder: str
    strategy: str
    volt_var: bool
    # Headline: limited by voltage and thermal only.
    hosting_capacity_mw: float
    binding_screen: str
    # Per-screen limits, so the caller can see the full ordering.
    limit_voltage_mw: float
    limit_thermal_mw: float
    limit_reverse_power_mw: float
    limit_penetration_15_mw: float
    limit_min_daytime_mw: float
    peak_load_mw: float
    min_daytime_load_mw: float
    max_vm_pu: float
    max_line_loading_pct: float
    penetration_of_peak: float
    penetration_of_min_daytime: float

    def to_row(self) -> dict:
        return asdict(self)


def allocate(buses: list[int], total_mw: float, strategy: str) -> dict[int, float]:
    """Split a total DER nameplate across candidate buses."""
    if not buses or total_mw <= 0:
        return {}
    if strategy == "distributed":
        share = total_mw / len(buses)
        return {b: share for b in buses}
    if strategy == "concentrated_end":
        return {buses[-1]: total_mw}
    if strategy == "concentrated_mid":
        return {buses[len(buses) // 2]: total_mw}
    raise ValueError(f"unknown siting strategy: {strategy!r}")


def place_der(net, allocation: dict[int, float]) -> None:
    """Replace all static generation on the net with the given allocation."""
    net.sgen = net.sgen.iloc[0:0]
    for bus, p_mw in allocation.items():
        if p_mw > 0:
            pp.create_sgen(net, bus=bus, p_mw=float(p_mw), q_mvar=0.0, name=f"der_{bus}")


class FeederProbe:
    """Reusable solver for one feeder at a fixed load condition.

    The network is built once and only its static generation is swapped between
    evaluations, which keeps a bisection to one power flow per step.
    """

    def __init__(
        self,
        spec: feeders.FeederSpec | str,
        use_volt_var: bool = False,
        load_scale: float | None = None,
        buses: list[int] | None = None,
    ) -> None:
        self.spec = feeders.SPECS[spec] if isinstance(spec, str) else spec
        self.use_volt_var = use_volt_var
        self.load_scale = (
            self.spec.min_daytime_load_frac if load_scale is None else load_scale
        )
        self.net = feeders.build(self.spec, load_scale=self.load_scale)
        self.buses = buses if buses is not None else feeders.load_buses(self.net)
        self.min_daytime_load_mw = self.spec.peak_load_mw * self.spec.min_daytime_load_frac

    def evaluate(self, total_mw: float, strategy: str = "distributed"):
        """Solve at a given penetration and score every screen. None if diverged."""
        place_der(self.net, allocate(self.buses, total_mw, strategy))
        try:
            volt_var.solve(self.net, enabled=self.use_volt_var)
        except pp.LoadflowNotConverged:
            return None
        return screens.evaluate(
            self.net,
            der_mw=total_mw,
            peak_load_mw=self.spec.peak_load_mw,
            min_daytime_load_mw=self.min_daytime_load_mw,
        )


def evaluate_penetration(
    spec: feeders.FeederSpec | str,
    total_mw: float,
    strategy: str = "distributed",
    use_volt_var: bool = False,
    load_scale: float | None = None,
    buses: list[int] | None = None,
):
    """One-shot evaluation at a single penetration.

    Convenience wrapper around FeederProbe for callers that only need one
    point. Use FeederProbe directly for sweeps and searches, since it reuses
    the built network instead of reconstructing it per call.
    """
    probe = FeederProbe(spec, use_volt_var=use_volt_var, load_scale=load_scale, buses=buses)
    return probe.evaluate(total_mw, strategy)


def _limit_for(probe: FeederProbe, strategy: str, screen: str, upper_mw: float, tol_mw: float) -> float:
    """Bisect for the largest DER MW at which a single named screen still passes."""

    def ok(mw: float) -> bool:
        res = probe.evaluate(mw, strategy)
        return res is not None and res.as_dict()[screen]

    if ok(upper_mw):
        return float(upper_mw)  # never binds inside the search range
    if not ok(0.0):
        return 0.0

    lo, hi = 0.0, upper_mw
    while hi - lo > tol_mw:
        mid = 0.5 * (lo + hi)
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return lo


def search(
    spec: feeders.FeederSpec | str,
    strategy: str = "distributed",
    use_volt_var: bool = False,
    upper_mw: float = 60.0,
    tol_mw: float = 0.01,
    buses: list[int] | None = None,
) -> CapacityResult:
    """Find the limiting DER MW for every screen on one feeder configuration."""
    if isinstance(spec, str):
        spec = feeders.SPECS[spec]

    probe = FeederProbe(spec, use_volt_var=use_volt_var, buses=buses)

    limits = {
        name: _limit_for(probe, strategy, name, upper_mw, tol_mw)
        for name in ("voltage", "thermal", "reverse_power")
    }
    # Paper screens are analytic, no power flow needed.
    limits["penetration_15"] = screens.FAST_TRACK_PENETRATION * spec.peak_load_mw
    limits["min_daytime"] = probe.min_daytime_load_mw

    headline = min(limits["voltage"], limits["thermal"])
    binding = min(screens.PHYSICAL_SCREENS, key=lambda n: limits[n])
    if headline >= upper_mw:
        binding = "none_in_range"

    at_limit = probe.evaluate(headline, strategy)

    return CapacityResult(
        feeder=spec.name,
        strategy=strategy,
        volt_var=use_volt_var,
        hosting_capacity_mw=round(headline, 3),
        binding_screen=binding,
        limit_voltage_mw=round(limits["voltage"], 3),
        limit_thermal_mw=round(limits["thermal"], 3),
        limit_reverse_power_mw=round(limits["reverse_power"], 3),
        limit_penetration_15_mw=round(limits["penetration_15"], 3),
        limit_min_daytime_mw=round(limits["min_daytime"], 3),
        peak_load_mw=round(spec.peak_load_mw, 3),
        min_daytime_load_mw=round(probe.min_daytime_load_mw, 3),
        max_vm_pu=round(at_limit.max_vm_pu, 4) if at_limit else float("nan"),
        max_line_loading_pct=round(at_limit.max_line_loading_pct, 2) if at_limit else float("nan"),
        penetration_of_peak=round(headline / spec.peak_load_mw, 3),
        penetration_of_min_daytime=round(headline / probe.min_daytime_load_mw, 3),
    )


def nodal_map(
    spec: feeders.FeederSpec | str,
    use_volt_var: bool = False,
    upper_mw: float = 60.0,
    tol_mw: float = 0.02,
) -> dict[int, float]:
    """Per-bus hosting capacity: max MW sited at that single bus alone.

    This is the map a planner actually wants, since it answers "how large a
    project can this specific customer build" rather than a feeder-wide total.
    """
    if isinstance(spec, str):
        spec = feeders.SPECS[spec]
    scaffold = feeders.build(spec, load_scale=spec.min_daytime_load_frac)
    out: dict[int, float] = {}
    for bus in feeders.load_buses(scaffold):
        probe = FeederProbe(spec, use_volt_var=use_volt_var, buses=[bus])
        v = _limit_for(probe, "distributed", "voltage", upper_mw, tol_mw)
        t = _limit_for(probe, "distributed", "thermal", upper_mw, tol_mw)
        out[bus] = round(min(v, t), 3)
    return out


def verify_monotonic(
    spec: feeders.FeederSpec | str,
    strategy: str = "distributed",
    use_volt_var: bool = False,
    upper_mw: float = 20.0,
    steps: int = 40,
) -> bool:
    """Check that pass/fail flips exactly once as DER grows.

    If this returns False the bisection result is not trustworthy and the sweep
    should be read directly instead.
    """
    if isinstance(spec, str):
        spec = feeders.SPECS[spec]
    probe = FeederProbe(spec, use_volt_var=use_volt_var)
    flags = []
    for mw in np.linspace(0.0, upper_mw, steps):
        res = probe.evaluate(float(mw), strategy)
        flags.append(res is not None and screens.passes(res, screens.PHYSICAL_SCREENS))
    transitions = sum(1 for a, b in zip(flags, flags[1:]) if a != b)
    return transitions <= 1


def sweep(
    spec: feeders.FeederSpec | str,
    strategy: str = "distributed",
    use_volt_var: bool = False,
    upper_mw: float = 6.0,
    steps: int = 60,
):
    """Penetration sweep returning voltage, loading, and substation flow traces."""
    if isinstance(spec, str):
        spec = feeders.SPECS[spec]
    probe = FeederProbe(spec, use_volt_var=use_volt_var)
    rows = []
    for mw in np.linspace(0.0, upper_mw, steps):
        res = probe.evaluate(float(mw), strategy)
        if res is None:
            continue
        rows.append(
            {
                "der_mw": float(mw),
                "max_vm_pu": res.max_vm_pu,
                "min_vm_pu": res.min_vm_pu,
                "max_line_loading_pct": res.max_line_loading_pct,
                "substation_p_mw": res.substation_p_mw,
            }
        )
    return rows
