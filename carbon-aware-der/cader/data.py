"""Inputs for carbon-aware DER dispatch.

Provenance matters here, so it is stated per series rather than in a footnote:

* **Carbon intensity: REAL.** Hourly PJM average grid carbon intensity from the
  CarbonCast project (https://github.com/carbonfirst/CarbonCast, Apache-2.0),
  which derives it from EIA hourly generation-by-fuel data. 2020-2021, 17,544
  hourly rows, no gaps. Published in gCO2/kWh, which is numerically identical
  to kg/MWh, so it drops straight into the repo's kg CO2e/MWh convention.

* **Price: REPRESENTATIVE STRUCTURE, not a filed tariff.** No LMP or retail
  rate source is reachable from this environment. The TOU schedule below uses
  a realistic mid-Atlantic residential shape and level, but it is a stand-in.
  Swap in a real tariff before drawing any conclusion about a specific rate.

* **Household base load: SYNTHETIC.** ResStock is not reachable. The profile is
  a parameterized residential shape (morning and evening peaks, seasonal
  heating and cooling response) scaled to roughly the US average of 10,500
  kWh/year. This is the lowest-stakes of the three: with no demand charge and
  no export, base load shifts cost and carbon totals but barely moves the
  battery and EV dispatch decision, which is driven by the price and carbon
  *shapes*.

An important limitation, stated once and repeated in the README: this uses
**average** grid carbon intensity, not **marginal**. Marginal emissions are the
theoretically correct signal for a dispatch decision, since what matters is
which generator moves when you shift a kWh. Average intensity is what is
publicly available at hourly resolution. Average tends to understate the
achievable savings, so the numbers here are conservative in that direction.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from shared import loadshapes, paths

CARBON_FILE = "PJM_direct_emissions.csv"
LOCAL_TZ = "US/Eastern"

# Horizon starts at noon so the overnight EV window does not wrap a day boundary.
HORIZON_START_HOUR = 12
HOURS = 24


# --- carbon -----------------------------------------------------------------


def load_carbon(year: int | None = None) -> pd.DataFrame:
    """Hourly PJM carbon intensity, localized to Eastern.

    Returns columns: ``timestamp`` (tz-aware local), ``carbon_kg_per_kwh``,
    plus the raw ``carbon_g_per_kwh`` for reference.
    """
    src = paths.raw("pjm", CARBON_FILE)
    if not src.exists():
        raise FileNotFoundError(
            f"{src} missing. Fetch CarbonCast: "
            "https://github.com/carbonfirst/CarbonCast -> data/PJM/PJM_direct_emissions.csv"
        )
    df = pd.read_csv(src)
    ts = pd.to_datetime(df["UTC time"]).dt.tz_localize("UTC").dt.tz_convert(LOCAL_TZ)
    out = pd.DataFrame(
        {
            "timestamp": ts,
            "carbon_g_per_kwh": df["carbon_intensity"].astype(float),
        }
    )
    out["carbon_kg_per_kwh"] = out["carbon_g_per_kwh"] / 1000.0
    out = out.dropna().sort_values("timestamp").reset_index(drop=True)
    if year is not None:
        out = out[out.timestamp.dt.year == year].reset_index(drop=True)
    return out


# --- price ------------------------------------------------------------------


@dataclass(frozen=True)
class TOUTariff:
    """Representative residential time-of-use structure.

    Not a filed tariff. Levels are typical mid-Atlantic residential all-in
    rates including delivery.
    """

    on_peak: float = 0.24
    mid_peak: float = 0.15
    off_peak: float = 0.09
    on_peak_hours: tuple[int, ...] = (14, 15, 16, 17, 18, 19)
    off_peak_hours: tuple[int, ...] = (23, 0, 1, 2, 3, 4, 5, 6)
    weekend_is_off_peak: bool = True
    name: str = "representative_tou"

    def price(self, ts: pd.Timestamp) -> float:
        if self.weekend_is_off_peak and ts.dayofweek >= 5:
            return self.off_peak
        if ts.hour in self.on_peak_hours:
            return self.on_peak
        if ts.hour in self.off_peak_hours:
            return self.off_peak
        return self.mid_peak

    def series(self, timestamps: pd.Series) -> np.ndarray:
        return np.array([self.price(t) for t in timestamps], dtype=float)


@dataclass(frozen=True)
class FlatTariff:
    """Flat volumetric rate, for isolating what TOU structure alone contributes."""

    rate: float = 0.155
    name: str = "flat"

    def series(self, timestamps: pd.Series) -> np.ndarray:
        return np.full(len(timestamps), self.rate, dtype=float)


# --- household base load ----------------------------------------------------


@dataclass(frozen=True)
class HouseholdProfile:
    """Synthetic residential load shape.

    Thin wrapper over ``shared.loadshapes.residential``, which is the canonical
    implementation. It lives in shared/ so that this track and tariff-explorer
    cannot drift apart on what "a household" means.
    """

    annual_kwh: float = 10_500.0
    seed: int = 20260726

    def series(self, timestamps: pd.Series) -> np.ndarray:
        return loadshapes.residential(
            timestamps, annual_kwh=self.annual_kwh, seed=self.seed
        )


# --- assembly ---------------------------------------------------------------


def build_dataset(
    year: int = 2021,
    tariff: TOUTariff | FlatTariff | None = None,
    household: HouseholdProfile | None = None,
) -> pd.DataFrame:
    """Hourly frame of everything the optimizer needs for one year."""
    tariff = tariff or TOUTariff()
    household = household or HouseholdProfile()

    df = load_carbon(year=year)
    df["price_per_kwh"] = tariff.series(df.timestamp)
    df["base_load_kwh"] = household.series(df.timestamp)
    df["date"] = df.timestamp.dt.date
    df["hour"] = df.timestamp.dt.hour
    return df


def daily_horizons(df: pd.DataFrame) -> list[pd.DataFrame]:
    """Split into noon-to-noon 24 hour blocks, dropping any partial block."""
    start = df.index[df.hour == HORIZON_START_HOUR]
    blocks = []
    for i in start:
        block = df.iloc[i : i + HOURS]
        if len(block) == HOURS:
            blocks.append(block.reset_index(drop=True))
    return blocks
