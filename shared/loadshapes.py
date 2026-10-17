"""Parameterized load and generation shapes.

These are **synthetic**. NREL ResStock and ComStock were not reachable from the
build environment, so archetype shapes are constructed from parameterized
diurnal and seasonal forms rather than measured data. Every function here
returns hourly energy in kWh and normalizes to a stated annual total, so the
shapes are useful for comparing *rate structures* against each other even
though the absolute levels are stylized.

What that means in practice: conclusions of the form "TOU shifts this archetype's
bill relative to that one" are sound, because they depend on shape. Conclusions
of the form "the average PA household would pay $X" are not, because they
depend on level. Swap in ResStock when it is reachable.

``residential()`` is the canonical implementation of the household profile that
``carbon-aware-der`` uses. It is here rather than there so the two tracks cannot
drift apart.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

HOURS_PER_YEAR = 8760.0


def _decompose(timestamps: pd.Series) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ts = pd.DatetimeIndex(timestamps)
    return ts.hour.to_numpy(), ts.dayofyear.to_numpy(), ts.dayofweek.to_numpy()


def _normalize(raw: np.ndarray, annual_kwh: float, n: int) -> np.ndarray:
    years = max(n / HOURS_PER_YEAR, 1e-9)
    total = raw.sum()
    if total <= 0:
        return np.zeros_like(raw)
    return raw * (annual_kwh * years) / total


def _noise(n: int, seed: int, sigma: float = 0.06) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(1.0, sigma, size=n).clip(0.75, 1.3)


def residential(
    timestamps: pd.Series,
    annual_kwh: float = 10_500.0,
    seed: int = 20260726,
) -> np.ndarray:
    """Baseline single-family household: morning bump, larger evening peak.

    Seasonal response has a summer cooling peak and a smaller winter one, which
    is the gas-heat case. See ``all_electric`` for the heat pump variant.
    """
    hour, doy, _ = _decompose(timestamps)
    diurnal = (
        0.62
        + 0.30 * np.exp(-0.5 * ((hour - 7.5) / 1.8) ** 2)
        + 0.62 * np.exp(-0.5 * ((hour - 19.5) / 2.4) ** 2)
    )
    summer = 0.34 * np.exp(-0.5 * ((doy - 200) / 45) ** 2)
    winter = 0.20 * np.exp(-0.5 * (np.minimum(doy, 365 - doy) / 40) ** 2)
    raw = diurnal * (1.0 + summer + winter) * _noise(len(hour), seed)
    return _normalize(raw, annual_kwh, len(hour))


def all_electric(
    timestamps: pd.Series,
    annual_kwh: float = 16_000.0,
    seed: int = 20260727,
) -> np.ndarray:
    """Heat pump household: winter-dominant, with a cold-morning ramp.

    The winter peak is what makes this archetype interesting under TOU, since
    heating demand lands in the morning and evening peak windows rather than
    the afternoon window that cooling load drives.
    """
    hour, doy, _ = _decompose(timestamps)
    diurnal = (
        0.60
        + 0.55 * np.exp(-0.5 * ((hour - 6.5) / 2.0) ** 2)
        + 0.70 * np.exp(-0.5 * ((hour - 19.0) / 2.6) ** 2)
    )
    winter = 0.95 * np.exp(-0.5 * (np.minimum(doy, 365 - doy) / 45) ** 2)
    summer = 0.30 * np.exp(-0.5 * ((doy - 200) / 45) ** 2)
    raw = diurnal * (1.0 + winter + summer) * _noise(len(hour), seed)
    return _normalize(raw, annual_kwh, len(hour))


def ev_charging(
    timestamps: pd.Series,
    daily_kwh: float = 12.0,
    power_kw: float = 11.5,
    plug_in_hour: int = 18,
    managed: bool = False,
    off_peak_start: int = 23,
    seed: int = 20260728,
) -> np.ndarray:
    """Daily EV charging session.

    ``managed=False`` charges flat out on plug-in, which is the unmanaged
    default and the case that stresses the evening peak. ``managed=True``
    defers the start to ``off_peak_start``, the behavior a TOU rate is meant to
    induce. The gap between the two is the whole argument for TOU on EV load.
    """
    ts = pd.DatetimeIndex(timestamps)
    hour = ts.hour.to_numpy()
    rng = np.random.default_rng(seed)
    out = np.zeros(len(ts))

    start = off_peak_start if managed else plug_in_hour
    day_index = ts.normalize()
    for day in pd.unique(day_index):
        mask = day_index == day
        idx = np.flatnonzero(mask)
        if len(idx) == 0:
            continue
        need = daily_kwh * rng.uniform(0.75, 1.25)
        # Charge from `start` forward, wrapping into later hours of the block.
        order = [i for i in idx if hour[i] >= start] + [i for i in idx if hour[i] < start]
        for i in order:
            if need <= 1e-9:
                break
            take = min(power_kw, need)
            out[i] += take
            need -= take
    return out


def pv_generation(
    timestamps: pd.Series,
    capacity_kw: float = 7.0,
    annual_kwh_per_kw: float = 1_250.0,
    seed: int = 20260729,
) -> np.ndarray:
    """Rooftop PV output, returned as a positive generation series.

    Day length varies sinusoidally over the year for a mid-latitude site
    (roughly 9.2 to 15.0 hours, appropriate for eastern Pennsylvania). Output
    within the day follows a half-sine between sunrise and sunset. Normalized
    to ``annual_kwh_per_kw``, which is a typical PA specific yield.
    """
    ts = pd.DatetimeIndex(timestamps)
    hour = ts.hour.to_numpy().astype(float)
    doy = ts.dayofyear.to_numpy()

    day_length = 12.1 + 2.9 * np.cos(2 * np.pi * (doy - 172) / 365.0)
    sunrise = 12.0 - day_length / 2.0
    sunset = 12.0 + day_length / 2.0

    frac = (hour - sunrise) / np.maximum(sunset - sunrise, 1e-6)
    shape = np.where((frac > 0) & (frac < 1), np.sin(np.pi * np.clip(frac, 0, 1)), 0.0)
    # Clear-sky intensity is also seasonal, beyond the day-length effect.
    intensity = 1.0 + 0.25 * np.cos(2 * np.pi * (doy - 172) / 365.0)
    rng = np.random.default_rng(seed)
    weather = rng.uniform(0.35, 1.0, size=len(ts)) ** 0.4  # skewed toward clear

    raw = shape * intensity * weather
    return _normalize(raw, capacity_kw * annual_kwh_per_kw, len(ts))


def commercial_daytime(
    timestamps: pd.Series,
    annual_kwh: float = 120_000.0,
    seed: int = 20260730,
) -> np.ndarray:
    """Small commercial with a weekday daytime peak, low nights and weekends."""
    hour, doy, dow = _decompose(timestamps)
    occupied = (hour >= 8) & (hour < 18) & (dow < 5)
    diurnal = np.where(occupied, 1.0, 0.28)
    diurnal = diurnal + 0.35 * np.exp(-0.5 * ((hour - 14.0) / 3.0) ** 2) * (dow < 5)
    cooling = 0.40 * np.exp(-0.5 * ((doy - 200) / 50) ** 2)
    raw = diurnal * (1.0 + cooling) * _noise(len(hour), seed, sigma=0.05)
    return _normalize(raw, annual_kwh, len(hour))


def commercial_flat(
    timestamps: pd.Series,
    annual_kwh: float = 120_000.0,
    seed: int = 20260731,
) -> np.ndarray:
    """Small commercial running near-continuously, e.g. refrigerated storage.

    High load factor. This archetype is the one that benefits most from a
    demand charge and least from TOU, and it exists in the set to make that
    contrast visible.
    """
    hour, doy, _ = _decompose(timestamps)
    diurnal = 0.90 + 0.14 * np.exp(-0.5 * ((hour - 14.0) / 5.0) ** 2)
    cooling = 0.18 * np.exp(-0.5 * ((doy - 200) / 55) ** 2)
    raw = diurnal * (1.0 + cooling) * _noise(len(hour), seed, sigma=0.04)
    return _normalize(raw, annual_kwh, len(hour))


def hourly_index(year: int = 2021, tz: str = "US/Eastern") -> pd.Series:
    """A full year of hourly timestamps, for archetypes built without real data."""
    idx = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h", tz=tz)
    return pd.Series(idx, name="timestamp")
