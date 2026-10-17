"""Synthetic but realistic radial distribution feeder archetypes.

Three archetypes bracket the range a distribution planner actually sees:

* ``rural``     long, lightly loaded, small conductor at the tail. Voltage rise
                limited. This is where hosting capacity is usually worst.
* ``suburban``  moderate length and loading, the most common case.
* ``urban``     short, heavily loaded, large conductor. Thermal and reverse
                power limited well before voltage becomes an issue.

Conductor impedances are typical 60 Hz overhead values for ACSR at 12.47 kV
line-to-line, taken from standard conductor tables. Nothing here is calibrated
to a real circuit.

Modeling choices worth stating up front (all documented in the README too):

* Balanced positive-sequence three-phase equivalent. Real hosting capacity
  studies for single-phase laterals need an unbalanced solver; the asymmetry
  generally makes true hosting capacity *lower* than what this model reports.
* Loads are constant-power PQ at 0.95 lagging power factor.
* No voltage regulators or switched capacitors mid-feeder. Adding a regulator
  materially raises voltage-limited hosting capacity, so results here are the
  conservative "no active voltage support" case.
* Substation LTC is represented by holding the source bus at 1.02 pu, a typical
  distribution bus setpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandapower as pp

# --- conductor library ------------------------------------------------------
# name -> (r_ohm_per_km, x_ohm_per_km, max_i_ka, c_nf_per_km)
# Typical 60 Hz overhead ACSR values at 12.47 kV, 50 degC conductor temp.
CONDUCTORS: dict[str, tuple[float, float, float, float]] = {
    "ACSR_477": (0.131, 0.372, 0.670, 10.0),
    "ACSR_336": (0.186, 0.383, 0.530, 9.6),
    "ACSR_4/0": (0.367, 0.412, 0.340, 9.0),
    "ACSR_1/0": (0.735, 0.440, 0.230, 8.4),
}

NOMINAL_KV = 12.47
SOURCE_VM_PU = 1.02  # substation bus setpoint, representative LTC target
LOAD_PF = 0.95  # lagging


@dataclass(frozen=True)
class Segment:
    """One run of feeder: how many buses, how long each span, what conductor."""

    n_buses: int
    span_km: float
    conductor: str
    load_kw_per_bus: float


@dataclass(frozen=True)
class FeederSpec:
    name: str
    description: str
    segments: tuple[Segment, ...]
    # Minimum daytime load as a fraction of feeder peak. Utilities commonly use
    # 30% of peak when a measured minimum daytime load is unavailable; that
    # convention comes from the FERC Small Generator Interconnection
    # Procedures supplemental review practice.
    min_daytime_load_frac: float = 0.30
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def peak_load_mw(self) -> float:
        return sum(s.n_buses * s.load_kw_per_bus for s in self.segments) / 1000.0

    @property
    def total_length_km(self) -> float:
        return sum(s.n_buses * s.span_km for s in self.segments)


SPECS: dict[str, FeederSpec] = {
    "rural": FeederSpec(
        name="rural",
        description="Long lightly loaded radial feeder, conductor tapers to 1/0 at the tail",
        segments=(
            Segment(n_buses=8, span_km=1.2, conductor="ACSR_336", load_kw_per_bus=55.0),
            Segment(n_buses=10, span_km=1.5, conductor="ACSR_4/0", load_kw_per_bus=35.0),
            Segment(n_buses=12, span_km=1.8, conductor="ACSR_1/0", load_kw_per_bus=20.0),
        ),
        notes=("Expect voltage rise to bind first, far out on the 1/0 tail.",),
    ),
    "suburban": FeederSpec(
        name="suburban",
        description="Moderate length residential feeder, uniform 336 ACSR trunk",
        segments=(
            Segment(n_buses=10, span_km=0.7, conductor="ACSR_477", load_kw_per_bus=180.0),
            Segment(n_buses=10, span_km=0.9, conductor="ACSR_336", load_kw_per_bus=120.0),
        ),
        notes=("The common case. Voltage and reverse power tend to bind together.",),
    ),
    "urban": FeederSpec(
        name="urban",
        description="Short heavily loaded feeder on large conductor",
        segments=(
            Segment(n_buses=6, span_km=0.35, conductor="ACSR_477", load_kw_per_bus=620.0),
            Segment(n_buses=6, span_km=0.30, conductor="ACSR_477", load_kw_per_bus=480.0),
        ),
        notes=("Stiff circuit. Substation reverse power screen binds before voltage.",),
    ),
}


def _register_conductors(net) -> None:
    for name, (r, x, i_ka, c_nf) in CONDUCTORS.items():
        pp.create_std_type(
            net,
            {
                "r_ohm_per_km": r,
                "x_ohm_per_km": x,
                "c_nf_per_km": c_nf,
                "max_i_ka": i_ka,
                "type": "ol",
            },
            name=name,
            element="line",
        )


def build(spec: FeederSpec | str, load_scale: float = 1.0):
    """Construct a pandapower net for a feeder archetype.

    ``load_scale`` multiplies every load, so the same topology can be solved at
    peak (1.0) or at minimum daytime load (typically 0.30). Hosting capacity is
    assessed at minimum daytime load because that is the condition under which
    net export, and therefore voltage rise, is worst.
    """
    if isinstance(spec, str):
        spec = SPECS[spec]

    net = pp.create_empty_network(name=f"{spec.name}_feeder", sn_mva=10.0)
    _register_conductors(net)

    source = pp.create_bus(net, vn_kv=NOMINAL_KV, name="substation", type="b")
    pp.create_ext_grid(net, bus=source, vm_pu=SOURCE_VM_PU, name="substation_source")

    upstream = source
    hop = 0
    for seg in spec.segments:
        for _ in range(seg.n_buses):
            hop += 1
            bus = pp.create_bus(net, vn_kv=NOMINAL_KV, name=f"bus_{hop:02d}")
            pp.create_line(
                net,
                from_bus=upstream,
                to_bus=bus,
                length_km=seg.span_km,
                std_type=seg.conductor,
                name=f"line_{hop:02d}",
            )
            p_mw = (seg.load_kw_per_bus / 1000.0) * load_scale
            pp.create_load(
                net,
                bus=bus,
                p_mw=p_mw,
                q_mvar=_q_from_pf(p_mw, LOAD_PF),
                name=f"load_{hop:02d}",
            )
            upstream = bus

    return net


def _q_from_pf(p_mw: float, pf: float) -> float:
    import math

    return p_mw * math.sqrt(1.0 - pf**2) / pf


def load_buses(net) -> list[int]:
    """Candidate DER siting buses: everything except the substation bus."""
    return [int(b) for b in net.bus.index if b != 0]


def distance_km(net, spec: FeederSpec | str) -> dict[int, float]:
    """Cumulative circuit distance from the substation to each bus."""
    if isinstance(spec, str):
        spec = SPECS[spec]
    dist = {0: 0.0}
    for _, line in net.line.iterrows():
        dist[int(line.to_bus)] = dist[int(line.from_bus)] + float(line.length_km)
    return dist
