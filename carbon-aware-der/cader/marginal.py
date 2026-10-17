"""Marginal emissions factors for PJM, estimated from hourly fuel-mix data.

Why this module exists: the rest of this track originally scheduled against
**average** grid carbon intensity, because that is what is published hourly.
Average intensity answers "what is the mean emissions rate of everything
running right now." A dispatch decision needs a different answer: "which
generator moves if I add or remove a kWh right now." That is the **marginal**
emissions factor, and in PJM the two signals point in opposite directions.

Method follows the standard Siler-Evans style regression of hourly changes:

    d(emissions) = MEF * d(generation) + e

fit within hour-of-day by season bins so the factor can vary across the day.
A naive fit conflates two different things, though. When wind or solar output
ramps, total generation and emissions both move for a reason that has nothing
to do with a marginal load change, which biases the estimated factor toward the
renewable mix rather than the dispatchable unit that actually responds. Adding
a renewable-ramp regressor separates them:

    d(emissions) = MEF * d(generation) + b * d(solar + wind) + c

On this dataset the control raises pooled R2 from 0.878 to 0.937 and the
renewable coefficient comes out strongly negative (about -472 kg/MWh), which is
the expected sign: a MWh of renewable ramp displaces a fossil MWh.

The estimate is still an estimate. It assumes the observed hourly deltas are
dominated by load following rather than by unit commitment or transmission
constraints, it cannot see intra-hour dispatch, and it attributes everything to
a single system-wide factor with no locational resolution. Those are real
limitations and they are repeated in the README.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import data as cd

FUELS = ("coal", "nat_gas", "nuclear", "oil", "hydro", "solar", "wind", "other")
RENEWABLE = ("solar", "wind")
MIN_BIN_SAMPLES = 50


@dataclass
class MEFFit:
    """Estimated marginal factors, indexed by (hour, season)."""

    table: pd.DataFrame  # hour, season, mef_kg_per_mwh, r2, n
    pooled_mef: float
    pooled_r2: float
    pooled_r2_uncontrolled: float
    renewable_coef: float

    def lookup(self, hours: np.ndarray, seasons: np.ndarray) -> np.ndarray:
        idx = self.table.set_index(["hour", "season"]).mef_kg_per_mwh
        out = np.array(
            [idx.get((int(h), int(s)), self.pooled_mef) for h, s in zip(hours, seasons)]
        )
        return out


def _season(month: pd.Series) -> pd.Series:
    """0 winter, 1 spring, 2 summer, 3 fall."""
    return (month % 12) // 3


def load_fuel_mix(year: int | None = None) -> pd.DataFrame:
    """Hourly PJM generation by fuel plus average carbon intensity, Eastern time."""
    src = cd.paths.raw("pjm", cd.CARBON_FILE)
    raw = pd.read_csv(src)
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(raw["UTC time"])
            .dt.tz_localize("UTC")
            .dt.tz_convert(cd.LOCAL_TZ),
            "avg_kg_per_mwh": raw["carbon_intensity"].astype(float),
        }
    )
    for fuel in FUELS:
        df[fuel] = raw[fuel].astype(float)
    df["total_mw"] = df[list(FUELS)].sum(axis=1)
    df["renewable_mw"] = df[list(RENEWABLE)].sum(axis=1)
    # avg_kg_per_mwh is gCO2/kWh, numerically kg/MWh, so this is kg over one hour.
    df["emissions_kg"] = df.avg_kg_per_mwh * df.total_mw
    df["hour"] = df.timestamp.dt.hour
    df["season"] = _season(df.timestamp.dt.month)
    if year is not None:
        df = df[df.timestamp.dt.year == year]
    return df.reset_index(drop=True)


def _fit(dgen: np.ndarray, drenew: np.ndarray, demis: np.ndarray, control: bool):
    cols = [dgen, drenew, np.ones(len(dgen))] if control else [dgen, np.ones(len(dgen))]
    A = np.column_stack(cols)
    coef, *_ = np.linalg.lstsq(A, demis, rcond=None)
    pred = A @ coef
    ss_res = float(((demis - pred) ** 2).sum())
    ss_tot = float(((demis - demis.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return coef, r2


def estimate(df: pd.DataFrame | None = None, control_renewables: bool = True) -> MEFFit:
    """Fit marginal emissions factors by hour-of-day and season."""
    df = load_fuel_mix() if df is None else df

    deltas = df[["total_mw", "renewable_mw", "emissions_kg"]].diff()
    deltas["hour"] = df["hour"]
    deltas["season"] = df["season"]
    deltas = deltas.dropna()

    dgen = deltas.total_mw.to_numpy()
    drenew = deltas.renewable_mw.to_numpy()
    demis = deltas.emissions_kg.to_numpy()

    coef, pooled_r2 = _fit(dgen, drenew, demis, control_renewables)
    _, r2_uncontrolled = _fit(dgen, drenew, demis, False)

    rows = []
    for (hour, season), g in deltas.groupby(["hour", "season"]):
        if len(g) < MIN_BIN_SAMPLES:
            continue
        c, r2 = _fit(
            g.total_mw.to_numpy(),
            g.renewable_mw.to_numpy(),
            g.emissions_kg.to_numpy(),
            control_renewables,
        )
        rows.append(
            {
                "hour": int(hour),
                "season": int(season),
                "mef_kg_per_mwh": float(c[0]),
                "r2": float(r2),
                "n": int(len(g)),
            }
        )

    return MEFFit(
        table=pd.DataFrame(rows),
        pooled_mef=float(coef[0]),
        pooled_r2=float(pooled_r2),
        pooled_r2_uncontrolled=float(r2_uncontrolled),
        renewable_coef=float(coef[1]) if control_renewables else float("nan"),
    )


def attach_marginal(dataset: pd.DataFrame, fit: MEFFit | None = None) -> pd.DataFrame:
    """Add a ``marginal_kg_per_kwh`` column to a cader dataset frame.

    Units: the fit is in kg/MWh, the dispatch model works in kWh, so divide by
    1000 to match the existing ``carbon_kg_per_kwh`` column.
    """
    fit = estimate() if fit is None else fit
    out = dataset.copy()
    seasons = _season(out.timestamp.dt.month).to_numpy()
    mef = fit.lookup(out.timestamp.dt.hour.to_numpy(), seasons)
    out["marginal_kg_per_kwh"] = mef / 1000.0
    return out


def signal_comparison(dataset: pd.DataFrame) -> dict:
    """How the average and marginal signals differ. The core diagnostic."""
    avg = dataset.carbon_kg_per_kwh.to_numpy() * 1000.0
    mrg = dataset.marginal_kg_per_kwh.to_numpy() * 1000.0
    hourly = dataset.assign(a=avg, m=mrg).groupby("hour").agg(a=("a", "mean"), m=("m", "mean"))

    def swing(x):
        return float(x.max() - x.min()), float(100 * (x.max() - x.min()) / x.mean())

    a_swing, a_pct = swing(hourly.a)
    m_swing, m_pct = swing(hourly.m)
    return {
        "avg_mean_kg_per_mwh": float(avg.mean()),
        "marginal_mean_kg_per_mwh": float(mrg.mean()),
        "marginal_over_average": float(mrg.mean() / avg.mean()),
        "hourly_correlation": float(np.corrcoef(avg, mrg)[0, 1]),
        "profile_correlation": float(np.corrcoef(hourly.a, hourly.m)[0, 1]),
        "avg_diurnal_swing_kg_per_mwh": a_swing,
        "avg_diurnal_swing_pct": a_pct,
        "marginal_diurnal_swing_kg_per_mwh": m_swing,
        "marginal_diurnal_swing_pct": m_pct,
        "signal_strength_ratio": float(m_pct / a_pct),
    }
