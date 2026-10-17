"""Which carbon signal should a controller optimize against?

This is the experiment that decides whether the rest of this track's headline
number means anything. Four strategies are run over a full year and all four
are scored on the **same** yardstick, marginal emissions, because marginal is
what actually changes when a controller shifts a kWh:

    unmanaged        no control at all, the baseline
    cost             minimize cost only
    avg_signal       minimize the published average carbon intensity
    marginal_signal  minimize estimated marginal emissions

The comparison that matters is ``avg_signal`` versus ``marginal_signal``. If
optimizing on the average signal raises marginal emissions, then a controller
built on public hourly carbon data is not merely less effective than it looks,
it is pointed the wrong way.

Scoring on marginal is a deliberate choice and it is the honest one. Scoring an
average-signal controller on the average signal is circular: it will always
look good against the objective it was handed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import data as cd
from . import marginal as cm
from . import optimizer as op

STRATEGIES = ("unmanaged", "cost", "avg_signal", "marginal_signal")


def _score(net: np.ndarray, price: np.ndarray, avg: np.ndarray, mrg: np.ndarray) -> dict:
    return {
        "cost": float(np.dot(price, net)),
        "avg_carbon_kg": float(np.dot(avg, net)),
        "marginal_carbon_kg": float(np.dot(mrg, net)),
        "grid_kwh": float(net.sum()),
    }


def run_year(
    dataset: pd.DataFrame | None = None,
    battery: op.Battery | None = None,
    ev: op.EV | None = None,
    year: int = 2021,
    progress_every: int = 60,
) -> pd.DataFrame:
    """Run all four strategies on every day and score each on both signals."""
    if dataset is None:
        dataset = cm.attach_marginal(cd.build_dataset(year))
    battery = battery or op.Battery()
    ev = ev or op.EV()

    rows = []
    blocks = cd.daily_horizons(dataset)
    for i, block in enumerate(blocks):
        base = block.base_load_kwh.to_numpy()
        price = block.price_per_kwh.to_numpy()
        avg = block.carbon_kg_per_kwh.to_numpy()
        mrg = block.marginal_kg_per_kwh.to_numpy()

        runs = {
            "unmanaged": op.unmanaged(base, price, avg, ev),
            "cost": op.dispatch(base, price, avg, battery, ev, weight_cost=1.0),
            # weight_cost=0 puts all weight on the carbon term; swapping which
            # series is passed as `carbon` is what changes the signal.
            "avg_signal": op.dispatch(base, price, avg, battery, ev, weight_cost=0.0),
            "marginal_signal": op.dispatch(base, price, mrg, battery, ev, weight_cost=0.0),
        }
        if not all(r.solved for r in runs.values()):
            continue

        for name, res in runs.items():
            rows.append(
                {
                    "date": block.timestamp.iloc[0].date(),
                    "month": block.timestamp.iloc[0].month,
                    "strategy": name,
                    **_score(res.net_load, price, avg, mrg),
                }
            )
        if progress_every and (i + 1) % progress_every == 0:
            print(f"    day {i + 1}/{len(blocks)}", flush=True)

    return pd.DataFrame(rows)


def summarize(results: pd.DataFrame) -> pd.DataFrame:
    """Annual totals and change versus unmanaged, on both carbon yardsticks."""
    tot = results.groupby("strategy")[
        ["cost", "avg_carbon_kg", "marginal_carbon_kg", "grid_kwh"]
    ].sum()
    base = tot.loc["unmanaged"]
    out = tot.copy()
    out["cost_change_pct"] = 100 * (tot.cost - base.cost) / base.cost
    out["avg_carbon_change_pct"] = (
        100 * (tot.avg_carbon_kg - base.avg_carbon_kg) / base.avg_carbon_kg
    )
    out["marginal_carbon_change_pct"] = (
        100 * (tot.marginal_carbon_kg - base.marginal_carbon_kg) / base.marginal_carbon_kg
    )
    order = [s for s in STRATEGIES if s in out.index]
    return out.loc[order]


def sign_flip_days(results: pd.DataFrame) -> dict:
    """How often the average-signal controller helps on average but hurts on marginal."""
    wide_avg = results.pivot(index="date", columns="strategy", values="avg_carbon_kg")
    wide_mrg = results.pivot(index="date", columns="strategy", values="marginal_carbon_kg")
    helps_avg = wide_avg["avg_signal"] < wide_avg["unmanaged"]
    hurts_marginal = wide_mrg["avg_signal"] > wide_mrg["unmanaged"]
    return {
        "days": int(len(wide_avg)),
        "helps_on_average": int(helps_avg.sum()),
        "hurts_on_marginal": int(hurts_marginal.sum()),
        "helps_avg_but_hurts_marginal": int((helps_avg & hurts_marginal).sum()),
    }
