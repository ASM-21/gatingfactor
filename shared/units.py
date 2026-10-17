"""Unit conventions and conversions shared across gatingfactor tracks.

Convention used throughout the repo, stated once here so no track has to guess:

* Power is stored in **MW** (and MVAr for reactive) at the analysis layer,
  because that is what pandapower and RTO data both speak. Customer-facing
  tariff math converts to kW at the edges only.
* Energy is stored in **MWh**. Tariff and bill math converts to kWh at the edge.
* Prices are **$/MWh** internally. Retail rates are quoted in $/kWh by
  convention, so `dollars_per_kwh` / `dollars_per_mwh` exist to move between.
* Emissions intensity is **kg CO2e/MWh**. US sources frequently publish
  lb CO2/MWh, so `lb_per_mwh_to_kg_per_mwh` is provided.
* Per-unit voltages follow ANSI C84.1, referenced against nominal.
"""

from __future__ import annotations

# --- power / energy ---------------------------------------------------------

KW_PER_MW = 1_000.0
W_PER_KW = 1_000.0


def kw_to_mw(kw: float) -> float:
    return kw / KW_PER_MW


def mw_to_kw(mw: float) -> float:
    return mw * KW_PER_MW


def kwh_to_mwh(kwh: float) -> float:
    return kwh / KW_PER_MW


def mwh_to_kwh(mwh: float) -> float:
    return mwh * KW_PER_MW


# --- price ------------------------------------------------------------------


def dollars_per_kwh(price_per_mwh: float) -> float:
    """$/MWh -> $/kWh."""
    return price_per_mwh / KW_PER_MW


def dollars_per_mwh(price_per_kwh: float) -> float:
    """$/kWh -> $/MWh."""
    return price_per_kwh * KW_PER_MW


# --- emissions --------------------------------------------------------------

KG_PER_LB = 0.45359237


def lb_per_mwh_to_kg_per_mwh(lb_per_mwh: float) -> float:
    """EPA eGRID and most US sources publish lb CO2/MWh; normalize to kg."""
    return lb_per_mwh * KG_PER_LB


def kg_to_metric_tons(kg: float) -> float:
    return kg / 1_000.0


# --- ANSI C84.1 service voltage limits (per unit) ---------------------------

ANSI_RANGE_A_MIN = 0.95
ANSI_RANGE_A_MAX = 1.05
ANSI_RANGE_B_MIN = 0.9167
ANSI_RANGE_B_MAX = 1.058


def in_range_a(v_pu: float) -> bool:
    """True if a per-unit voltage sits inside ANSI C84.1 Range A."""
    return ANSI_RANGE_A_MIN <= v_pu <= ANSI_RANGE_A_MAX


# --- power factor -----------------------------------------------------------


def q_from_p_and_pf(p_mw: float, power_factor: float, lagging: bool = True) -> float:
    """Reactive power (MVAr) implied by a real power and displacement PF."""
    import math

    if not 0 < power_factor <= 1:
        raise ValueError("power_factor must be in (0, 1]")
    tan_phi = math.sqrt(1.0 - power_factor**2) / power_factor
    q = p_mw * tan_phi
    return q if lagging else -q
