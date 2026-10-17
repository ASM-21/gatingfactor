"""Retail tariff structures and bill computation.

Every structure bills **monthly**, because that is where the interesting
behavior lives: tiers reset monthly, demand charges are assessed on a monthly
maximum, and minimum bills apply per month. Computing an annual bill as
12 x (annual/12) throws away exactly the effects this module exists to study.

Billing determinants, in the order they are applied:

1. ``net[h] = load[h] - onsite_generation[h]`` at each hourly interval.
2. Positive ``net`` is billed at the structure's rate for that interval.
3. Negative ``net`` (export) is credited at ``export_rate``. Setting
   ``export_rate=None`` means net energy metering, where export is credited at
   the same retail rate that would have applied to consumption in that hour.
   A numeric rate means net billing at an avoided-cost style value.
4. Demand charges use the monthly maximum of ``net``, floored at zero, since
   the meter cannot register negative demand.
5. A minimum bill, if set, raises the month's total but is never a refund.

The export treatment is the single most consequential modeling choice here.
Full-retail NEM versus net billing at an avoided-cost rate changes the solar
archetype's bill far more than any choice between TOU and tiered structures,
which is a real result and not an artifact.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

MONTHS = list(range(1, 13))


@dataclass
class Bill:
    """One month, or one year when summed."""

    fixed: float = 0.0
    energy: float = 0.0
    demand: float = 0.0
    export_credit: float = 0.0
    minimum_adjustment: float = 0.0
    consumption_kwh: float = 0.0
    export_kwh: float = 0.0
    peak_kw: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.fixed
            + self.energy
            + self.demand
            - self.export_credit
            + self.minimum_adjustment
        )

    @property
    def effective_rate(self) -> float:
        """Total bill divided by net consumption. The number customers feel."""
        net = self.consumption_kwh - self.export_kwh
        return self.total / net if net > 1e-9 else float("nan")

    def __add__(self, other: "Bill") -> "Bill":
        return Bill(
            fixed=self.fixed + other.fixed,
            energy=self.energy + other.energy,
            demand=self.demand + other.demand,
            export_credit=self.export_credit + other.export_credit,
            minimum_adjustment=self.minimum_adjustment + other.minimum_adjustment,
            consumption_kwh=self.consumption_kwh + other.consumption_kwh,
            export_kwh=self.export_kwh + other.export_kwh,
            peak_kw=max(self.peak_kw, other.peak_kw),
        )


@dataclass
class Tariff:
    """Base structure. Subclasses supply ``rate_at`` and optionally demand terms."""

    name: str = "tariff"
    fixed_monthly: float = 12.00
    demand_rate_per_kw: float = 0.0
    minimum_monthly: float = 0.0
    export_rate: float | None = None  # None means full-retail NEM
    scale: float = 1.0  # multiplies volumetric rates, used by revenue-neutrality solver

    def rate_at(self, ts: pd.DatetimeIndex) -> np.ndarray:
        raise NotImplementedError

    # -- billing ------------------------------------------------------------

    def _energy_charge(
        self, ts: pd.DatetimeIndex, net: np.ndarray
    ) -> tuple[float, float]:
        """Return (charge on positive net, credit on negative net)."""
        rate = self.rate_at(ts) * self.scale
        consumed = np.clip(net, 0.0, None)
        exported = np.clip(-net, 0.0, None)
        charge = float(np.dot(rate, consumed))
        credit_rate = rate if self.export_rate is None else np.full(len(ts), self.export_rate)
        credit = float(np.dot(credit_rate, exported))
        return charge, credit

    def bill_month(self, ts: pd.DatetimeIndex, net: np.ndarray) -> Bill:
        charge, credit = self._energy_charge(ts, net)
        peak_kw = float(max(net.max(), 0.0))
        demand = self.demand_rate_per_kw * peak_kw
        b = Bill(
            fixed=self.fixed_monthly,
            energy=charge,
            demand=demand,
            export_credit=credit,
            consumption_kwh=float(np.clip(net, 0.0, None).sum()),
            export_kwh=float(np.clip(-net, 0.0, None).sum()),
            peak_kw=peak_kw,
        )
        if self.minimum_monthly and b.total < self.minimum_monthly:
            b.minimum_adjustment = self.minimum_monthly - b.total
        return b

    def bill_year(self, timestamps: pd.Series, net: np.ndarray) -> pd.DataFrame:
        """Monthly bills for a full year. Index is month number."""
        ts = pd.DatetimeIndex(timestamps)
        rows = []
        for month in MONTHS:
            mask = ts.month == month
            if not mask.any():
                continue
            b = self.bill_month(ts[mask], net[mask])
            rows.append(
                {
                    "month": month,
                    "fixed": b.fixed,
                    "energy": b.energy,
                    "demand": b.demand,
                    "export_credit": b.export_credit,
                    "minimum_adjustment": b.minimum_adjustment,
                    "total": b.total,
                    "consumption_kwh": b.consumption_kwh,
                    "export_kwh": b.export_kwh,
                    "peak_kw": b.peak_kw,
                }
            )
        return pd.DataFrame(rows)

    def annual(self, timestamps: pd.Series, net: np.ndarray) -> Bill:
        monthly = self.bill_year(timestamps, net)
        return Bill(
            fixed=monthly.fixed.sum(),
            energy=monthly.energy.sum(),
            demand=monthly.demand.sum(),
            export_credit=monthly.export_credit.sum(),
            minimum_adjustment=monthly.minimum_adjustment.sum(),
            consumption_kwh=monthly.consumption_kwh.sum(),
            export_kwh=monthly.export_kwh.sum(),
            peak_kw=monthly.peak_kw.max() if len(monthly) else 0.0,
        )

    def with_scale(self, scale: float) -> "Tariff":
        import copy

        clone = copy.deepcopy(self)
        clone.scale = scale
        return clone


@dataclass
class FlatRate(Tariff):
    """Single volumetric rate. The reference structure everything is compared to."""

    rate: float = 0.155
    name: str = "flat"

    def rate_at(self, ts: pd.DatetimeIndex) -> np.ndarray:
        return np.full(len(ts), self.rate)


@dataclass
class TieredRate(Tariff):
    """Inclining block rate. Tiers reset each month.

    ``tiers`` is a list of (monthly kWh threshold, rate). The final threshold is
    treated as unbounded. Because tiers depend on cumulative monthly
    consumption, the rate at an interval is path-dependent, so this overrides
    the energy charge rather than implementing ``rate_at`` pointwise.
    """

    tiers: list[tuple[float, float]] = field(
        default_factory=lambda: [(500.0, 0.125), (1000.0, 0.165), (float("inf"), 0.205)]
    )
    name: str = "tiered"

    def rate_at(self, ts: pd.DatetimeIndex) -> np.ndarray:
        # Reported for inspection only; billing uses the cumulative logic below.
        return np.full(len(ts), self.tiers[0][1])

    def _energy_charge(self, ts, net):
        consumed = np.clip(net, 0.0, None)
        cumulative = np.cumsum(consumed)
        charge = 0.0
        lower = 0.0
        for threshold, rate in self.tiers:
            in_tier = np.clip(np.minimum(cumulative, threshold) - lower, 0.0, None)
            block = np.diff(np.concatenate([[0.0], in_tier]))
            charge += rate * self.scale * block.sum()
            lower = threshold
            if not np.isfinite(threshold):
                break
        exported = np.clip(-net, 0.0, None)
        credit_rate = (
            self.tiers[0][1] * self.scale if self.export_rate is None else self.export_rate
        )
        return float(charge), float(credit_rate * exported.sum())


@dataclass
class TOURate(Tariff):
    """Time-of-use with on, mid, and off peak periods.

    Weekends are off-peak by default, which is near-universal in real TOU
    schedules and materially changes the comparison for commercial archetypes.
    """

    on_peak: float = 0.240
    mid_peak: float = 0.150
    off_peak: float = 0.090
    on_peak_hours: tuple[int, ...] = (14, 15, 16, 17, 18, 19)
    off_peak_hours: tuple[int, ...] = (23, 0, 1, 2, 3, 4, 5, 6)
    weekend_off_peak: bool = True
    name: str = "tou"

    def rate_at(self, ts: pd.DatetimeIndex) -> np.ndarray:
        hour = ts.hour.to_numpy()
        dow = ts.dayofweek.to_numpy()
        rates = np.full(len(ts), self.mid_peak)
        rates[np.isin(hour, self.on_peak_hours)] = self.on_peak
        rates[np.isin(hour, self.off_peak_hours)] = self.off_peak
        if self.weekend_off_peak:
            rates[dow >= 5] = self.off_peak
        return rates


@dataclass
class DemandChargeRate(Tariff):
    """Lower volumetric rate plus a monthly demand charge on peak kW.

    This is the structure that penalizes low load factor, so it is where the
    flat commercial archetype and the EV household diverge most sharply.
    """

    rate: float = 0.095
    demand_rate_per_kw: float = 12.00
    name: str = "demand"

    def rate_at(self, ts: pd.DatetimeIndex) -> np.ndarray:
        return np.full(len(ts), self.rate)


@dataclass
class HybridTOUDemand(TOURate):
    """TOU energy plus a demand charge. Increasingly common for C&I and EV rates."""

    on_peak: float = 0.180
    mid_peak: float = 0.115
    off_peak: float = 0.070
    demand_rate_per_kw: float = 8.00
    name: str = "hybrid_tou_demand"


DEFAULT_TARIFFS: tuple[Tariff, ...] = (
    FlatRate(),
    TieredRate(),
    TOURate(),
    DemandChargeRate(),
    HybridTOUDemand(),
)
