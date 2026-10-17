"""Battery and EV dispatch as a MILP, solved per 24 hour horizon with PuLP/CBC.

Decision variables per hour t:
    ch[t]   battery charge, kWh drawn from the house node
    dis[t]  battery discharge, kWh delivered to the house node
    soc[t]  battery state of charge at end of hour, kWh
    ev[t]   EV charging energy, kWh
    y[t]    binary, 1 if charging. This is the integer part of the MILP.

Grid draw is  net[t] = base[t] + ch[t] - dis[t] + ev[t],  constrained >= 0.
No export is allowed, which is the common residential case and also keeps the
carbon accounting honest: exported energy would need a separate avoided-
emissions assumption that this model does not want to make.

Objective is a normalized weighted sum:

    minimize  w * (cost / cost_ref)  +  (1 - w) * (carbon / carbon_ref)

with w = 1 pure cost minimization and w = 0 pure carbon minimization. The
reference values are the two single-objective optima for that same day, so w
sweeps a genuine Pareto frontier rather than an arbitrary units mixture. Without
that normalization the weight would just express the ratio of $/kWh to kg/kWh
and would not be interpretable.

Two constraints that matter more than they look:

* **Terminal SOC.** ``soc[T-1] >= soc_init`` prevents the optimizer from
  draining the battery over the horizon and booking the stored energy as free
  savings. Omitting this is the most common way a result like this gets
  inflated.
* **Charge/discharge exclusivity** via the binary. With a round-trip efficiency
  below 1 and no exclusivity, simultaneous charge and discharge is never
  optimal anyway, so relaxing the binary usually gives the same answer far
  faster. ``relax=True`` exposes that, and the test suite checks the two agree.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pulp


@dataclass(frozen=True)
class Battery:
    capacity_kwh: float = 13.5
    power_kw: float = 5.0
    efficiency_roundtrip: float = 0.90
    soc_min_frac: float = 0.10
    soc_init_frac: float = 0.50

    @property
    def eta(self) -> float:
        """One-way efficiency, applied on both charge and discharge."""
        return float(np.sqrt(self.efficiency_roundtrip))

    @property
    def soc_min(self) -> float:
        return self.soc_min_frac * self.capacity_kwh

    @property
    def soc_init(self) -> float:
        return self.soc_init_frac * self.capacity_kwh


@dataclass(frozen=True)
class EV:
    """Overnight charging session on a noon-to-noon horizon.

    Default: plugs in at 18:00 (index 6) and must be full by 07:00 (index 19).
    """

    energy_kwh: float = 12.0
    power_kw: float = 11.5
    plug_in_index: int = 6
    deadline_index: int = 19

    def window(self, horizon: int) -> list[int]:
        return [t for t in range(horizon) if self.plug_in_index <= t <= self.deadline_index]

    def feasible(self, horizon: int) -> bool:
        return len(self.window(horizon)) * self.power_kw >= self.energy_kwh


@dataclass
class DispatchResult:
    status: str
    cost: float
    carbon_kg: float
    grid_kwh: float
    battery_charge: np.ndarray = field(repr=False)
    battery_discharge: np.ndarray = field(repr=False)
    ev_charge: np.ndarray = field(repr=False)
    soc: np.ndarray = field(repr=False)
    net_load: np.ndarray = field(repr=False)

    @property
    def solved(self) -> bool:
        return self.status == "Optimal"


def unmanaged(
    base_load: np.ndarray,
    price: np.ndarray,
    carbon: np.ndarray,
    ev: EV | None = None,
) -> DispatchResult:
    """Do-nothing reference: battery idle, EV charges flat out on plug-in.

    This is the baseline every saving in this module is measured against. It is
    what actually happens without a controller.
    """
    horizon = len(base_load)
    ev_profile = np.zeros(horizon)
    if ev is not None:
        remaining = ev.energy_kwh
        for t in ev.window(horizon):
            take = min(ev.power_kw, remaining)
            ev_profile[t] = take
            remaining -= take
            if remaining <= 1e-9:
                break
    net = base_load + ev_profile
    return DispatchResult(
        status="Optimal",
        cost=float(np.dot(price, net)),
        carbon_kg=float(np.dot(carbon, net)),
        grid_kwh=float(net.sum()),
        battery_charge=np.zeros(horizon),
        battery_discharge=np.zeros(horizon),
        ev_charge=ev_profile,
        soc=np.zeros(horizon),
        net_load=net,
    )


def dispatch(
    base_load: np.ndarray,
    price: np.ndarray,
    carbon: np.ndarray,
    battery: Battery | None = None,
    ev: EV | None = None,
    weight_cost: float = 1.0,
    cost_ref: float | None = None,
    carbon_ref: float | None = None,
    relax: bool = False,
    allow_export: bool = False,
) -> DispatchResult:
    """Solve one horizon. ``weight_cost`` of 1 is pure cost, 0 is pure carbon."""
    horizon = len(base_load)
    battery = battery if battery is not None else Battery()
    if ev is not None and not ev.feasible(horizon):
        raise ValueError("EV cannot meet its energy requirement inside the plug-in window")

    cat = "Continuous" if relax else "Binary"
    prob = pulp.LpProblem("carbon_aware_dispatch", pulp.LpMinimize)

    ch = pulp.LpVariable.dicts("ch", range(horizon), 0, battery.power_kw)
    dis = pulp.LpVariable.dicts("dis", range(horizon), 0, battery.power_kw)
    soc = pulp.LpVariable.dicts("soc", range(horizon), battery.soc_min, battery.capacity_kwh)
    y = pulp.LpVariable.dicts("y", range(horizon), 0, 1, cat=cat)

    ev_window = ev.window(horizon) if ev is not None else []
    evv = pulp.LpVariable.dicts("ev", range(horizon), 0, None)
    for t in range(horizon):
        evv[t].upBound = ev.power_kw if (ev is not None and t in ev_window) else 0.0
    if ev is not None:
        prob += pulp.lpSum(evv[t] for t in ev_window) == ev.energy_kwh, "ev_energy"

    # Battery dynamics.
    for t in range(horizon):
        prior = battery.soc_init if t == 0 else soc[t - 1]
        prob += soc[t] == prior + battery.eta * ch[t] - dis[t] / battery.eta, f"soc_{t}"
        prob += ch[t] <= battery.power_kw * y[t], f"ch_excl_{t}"
        prob += dis[t] <= battery.power_kw * (1 - y[t]), f"dis_excl_{t}"

    # No free energy across the horizon boundary.
    prob += soc[horizon - 1] >= battery.soc_init, "terminal_soc"

    net = {t: base_load[t] + ch[t] - dis[t] + evv[t] for t in range(horizon)}
    if not allow_export:
        for t in range(horizon):
            prob += net[t] >= 0, f"no_export_{t}"

    cost_expr = pulp.lpSum(price[t] * net[t] for t in range(horizon))
    carbon_expr = pulp.lpSum(carbon[t] * net[t] for t in range(horizon))

    c_ref = cost_ref if cost_ref and cost_ref > 0 else 1.0
    e_ref = carbon_ref if carbon_ref and carbon_ref > 0 else 1.0
    prob += weight_cost * (cost_expr / c_ref) + (1.0 - weight_cost) * (carbon_expr / e_ref)

    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    status = pulp.LpStatus[prob.status]

    def vals(d):
        return np.array([float(d[t].value() or 0.0) for t in range(horizon)])

    ch_v, dis_v, ev_v, soc_v = vals(ch), vals(dis), vals(evv), vals(soc)
    net_v = base_load + ch_v - dis_v + ev_v

    return DispatchResult(
        status=status,
        cost=float(np.dot(price, net_v)),
        carbon_kg=float(np.dot(carbon, net_v)),
        grid_kwh=float(net_v.sum()),
        battery_charge=ch_v,
        battery_discharge=dis_v,
        ev_charge=ev_v,
        soc=soc_v,
        net_load=net_v,
    )


def anchors(
    base_load: np.ndarray,
    price: np.ndarray,
    carbon: np.ndarray,
    battery: Battery | None = None,
    ev: EV | None = None,
    **kw,
) -> tuple[DispatchResult, DispatchResult]:
    """Single-objective optima: (cost-minimizing, carbon-minimizing)."""
    cost_opt = dispatch(base_load, price, carbon, battery, ev, weight_cost=1.0, **kw)
    carbon_opt = dispatch(base_load, price, carbon, battery, ev, weight_cost=0.0, **kw)
    return cost_opt, carbon_opt
