"""Customer archetypes and cross-tariff analysis.

Five archetypes chosen to span the two dimensions that rate design actually
trades off: **when** load happens (which TOU prices) and **how peaky** it is
(which demand charges price). Load factor is reported for every archetype
because it is the single best predictor of who wins and loses under a demand
charge.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from shared import loadshapes

from . import tariffs as tf


@dataclass
class Archetype:
    key: str
    label: str
    description: str
    load: np.ndarray = field(repr=False)
    generation: np.ndarray = field(repr=False)
    timestamps: pd.Series = field(repr=False)

    @property
    def net(self) -> np.ndarray:
        return self.load - self.generation

    @property
    def annual_kwh(self) -> float:
        return float(self.load.sum())

    @property
    def net_annual_kwh(self) -> float:
        return float(self.net.sum())

    @property
    def peak_kw(self) -> float:
        return float(max(self.net.max(), 0.0))

    @property
    def load_factor(self) -> float:
        """Average demand over peak demand. Low means peaky."""
        if self.peak_kw <= 0:
            return float("nan")
        return float(np.clip(self.net, 0, None).mean()) / self.peak_kw


def build_archetypes(year: int = 2021) -> dict[str, Archetype]:
    ts = loadshapes.hourly_index(year)
    zeros = np.zeros(len(ts))

    residential = loadshapes.residential(ts)
    ev_unmanaged = loadshapes.ev_charging(ts, managed=False)

    specs = {
        "all_electric": Archetype(
            key="all_electric",
            label="All-electric home",
            description="Heat pump heating and cooling, winter-dominant, no onsite generation",
            load=loadshapes.all_electric(ts),
            generation=zeros,
            timestamps=ts,
        ),
        "ev_home": Archetype(
            key="ev_home",
            label="Home with EV charging",
            description="Baseline household plus an unmanaged EV charging on plug-in at 18:00",
            load=residential + ev_unmanaged,
            generation=zeros,
            timestamps=ts,
        ),
        "solar_home": Archetype(
            key="solar_home",
            label="Home with rooftop solar",
            description="Baseline household with a 7 kW rooftop PV system",
            load=residential.copy(),
            generation=loadshapes.pv_generation(ts, capacity_kw=7.0),
            timestamps=ts,
        ),
        "commercial_daytime": Archetype(
            key="commercial_daytime",
            label="Small commercial, daytime peaked",
            description="Weekday 8-18 occupancy with an afternoon cooling peak",
            load=loadshapes.commercial_daytime(ts),
            generation=zeros,
            timestamps=ts,
        ),
        "commercial_flat": Archetype(
            key="commercial_flat",
            label="Small commercial, flat load",
            description="Near-continuous operation, high load factor",
            load=loadshapes.commercial_flat(ts),
            generation=zeros,
            timestamps=ts,
        ),
    }
    return specs


# --- analysis ---------------------------------------------------------------


def bill_matrix(
    archetypes: dict[str, Archetype],
    tariff_list: tuple[tf.Tariff, ...] = tf.DEFAULT_TARIFFS,
) -> pd.DataFrame:
    """Annual bill for every (archetype, tariff) pair."""
    rows = []
    for arch in archetypes.values():
        for tariff in tariff_list:
            b = tariff.annual(arch.timestamps, arch.net)
            rows.append(
                {
                    "archetype": arch.key,
                    "label": arch.label,
                    "tariff": tariff.name,
                    "annual_bill": b.total,
                    "energy": b.energy,
                    "demand": b.demand,
                    "fixed": b.fixed,
                    "export_credit": b.export_credit,
                    "minimum_adjustment": b.minimum_adjustment,
                    "consumption_kwh": b.consumption_kwh,
                    "export_kwh": b.export_kwh,
                    "net_kwh": arch.net_annual_kwh,
                    "peak_kw": arch.peak_kw,
                    "load_factor": arch.load_factor,
                    "effective_rate": b.effective_rate,
                }
            )
    return pd.DataFrame(rows)


def switching_impact(matrix: pd.DataFrame, baseline: str = "flat") -> pd.DataFrame:
    """Bill change for each archetype when moving off the baseline tariff.

    This is the table that matters in a rate case: who wins, who loses, and by
    how much, when a structure changes.
    """
    base = matrix[matrix.tariff == baseline].set_index("archetype").annual_bill
    out = matrix[matrix.tariff != baseline].copy()
    out["baseline_bill"] = out.archetype.map(base)
    out["change_dollars"] = out.annual_bill - out.baseline_bill
    out["change_pct"] = 100.0 * out.change_dollars / out.baseline_bill
    return out


def revenue_neutral_scale(
    tariff: tf.Tariff,
    archetypes: dict[str, Archetype],
    target_revenue: float,
    lo: float = 0.05,
    hi: float = 5.0,
    tol: float = 1e-7,
) -> float:
    """Volumetric scaling factor that makes a tariff collect ``target_revenue``.

    Bisection rather than a closed form, because tiers and minimum bills make
    revenue a piecewise-linear (and not strictly proportional) function of the
    scale factor. Revenue is monotonically non-decreasing in the scale factor,
    which is what makes bisection valid here.
    """

    def revenue(scale: float) -> float:
        scaled = tariff.with_scale(scale)
        return sum(
            scaled.annual(a.timestamps, a.net).total for a in archetypes.values()
        )

    if revenue(hi) < target_revenue:
        return hi
    if revenue(lo) > target_revenue:
        return lo
    while hi - lo > tol:
        mid = 0.5 * (lo + hi)
        if revenue(mid) < target_revenue:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def revenue_neutral_comparison(
    archetypes: dict[str, Archetype],
    tariff_list: tuple[tf.Tariff, ...] = tf.DEFAULT_TARIFFS,
    baseline: str = "flat",
) -> pd.DataFrame:
    """Re-run the bill matrix with every tariff scaled to collect equal revenue.

    Without this step a tariff comparison mostly measures which structure was
    written with higher rates, not which structure allocates cost differently.
    Holding total revenue fixed isolates the allocation effect, which is the
    thing rate design is actually arguing about.
    """
    base_tariff = next(t for t in tariff_list if t.name == baseline)
    target = sum(
        base_tariff.annual(a.timestamps, a.net).total for a in archetypes.values()
    )
    rows = []
    for tariff in tariff_list:
        scale = revenue_neutral_scale(tariff, archetypes, target)
        scaled = tariff.with_scale(scale)
        for arch in archetypes.values():
            b = scaled.annual(arch.timestamps, arch.net)
            rows.append(
                {
                    "archetype": arch.key,
                    "label": arch.label,
                    "tariff": tariff.name,
                    "scale": scale,
                    "annual_bill": b.total,
                    "effective_rate": b.effective_rate,
                    "load_factor": arch.load_factor,
                }
            )
    df = pd.DataFrame(rows)
    base = df[df.tariff == baseline].set_index("archetype").annual_bill
    df["baseline_bill"] = df.archetype.map(base)
    df["change_pct"] = 100.0 * (df.annual_bill - df.baseline_bill) / df.baseline_bill
    return df
