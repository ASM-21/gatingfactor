"""Roll the daily MILP up to a year, and trace the cost/carbon Pareto frontier.

Two separate runs, because they answer different questions:

``annual_summary`` solves every day at both single-objective extremes plus the
unmanaged baseline. That gives the headline "what is available" numbers over a
full year of real carbon data.

``frontier`` sweeps the objective weight on a sample of days to trace the
tradeoff curve. It is sampled rather than exhaustive because the curve's shape
is stable across days and a full-year sweep at every weight is a lot of CBC
invocations for no additional insight.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import data as cd
from . import optimizer as op

WEIGHTS = (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0)


def _arrays(block: pd.DataFrame):
    return (
        block.base_load_kwh.to_numpy(),
        block.price_per_kwh.to_numpy(),
        block.carbon_kg_per_kwh.to_numpy(),
    )


def annual_summary(
    df: pd.DataFrame,
    battery: op.Battery | None = None,
    ev: op.EV | None = None,
    progress_every: int = 60,
) -> pd.DataFrame:
    """Unmanaged, cost-optimal, and carbon-optimal dispatch for every day."""
    battery = battery or op.Battery()
    ev = ev or op.EV()
    rows = []
    blocks = cd.daily_horizons(df)
    for i, block in enumerate(blocks):
        base, price, carbon = _arrays(block)
        un = op.unmanaged(base, price, carbon, ev)
        cost_opt, carbon_opt = op.anchors(base, price, carbon, battery, ev)
        if not (cost_opt.solved and carbon_opt.solved):
            continue
        rows.append(
            {
                "date": block.timestamp.iloc[0].date(),
                "month": block.timestamp.iloc[0].month,
                "carbon_spread_g": float(
                    (carbon.max() - carbon.min()) * 1000.0
                ),
                "price_spread": float(price.max() - price.min()),
                "unmanaged_cost": un.cost,
                "unmanaged_carbon": un.carbon_kg,
                "cost_opt_cost": cost_opt.cost,
                "cost_opt_carbon": cost_opt.carbon_kg,
                "carbon_opt_cost": carbon_opt.cost,
                "carbon_opt_carbon": carbon_opt.carbon_kg,
            }
        )
        if progress_every and (i + 1) % progress_every == 0:
            print(f"    day {i + 1}/{len(blocks)}", flush=True)
    return pd.DataFrame(rows)


def frontier(
    df: pd.DataFrame,
    battery: op.Battery | None = None,
    ev: op.EV | None = None,
    every_n_days: int = 7,
    weights: tuple[float, ...] = WEIGHTS,
) -> pd.DataFrame:
    """Weighted-sum sweep tracing the cost/carbon tradeoff."""
    battery = battery or op.Battery()
    ev = ev or op.EV()
    rows = []
    blocks = cd.daily_horizons(df)[::every_n_days]
    for i, block in enumerate(blocks):
        base, price, carbon = _arrays(block)
        cost_opt, carbon_opt = op.anchors(base, price, carbon, battery, ev)
        if not (cost_opt.solved and carbon_opt.solved):
            continue
        c_ref, e_ref = cost_opt.cost, carbon_opt.carbon_kg
        for w in weights:
            res = op.dispatch(
                base,
                price,
                carbon,
                battery,
                ev,
                weight_cost=w,
                cost_ref=c_ref,
                carbon_ref=e_ref,
            )
            if not res.solved:
                continue
            rows.append(
                {
                    "date": block.timestamp.iloc[0].date(),
                    "weight_cost": w,
                    "cost": res.cost,
                    "carbon_kg": res.carbon_kg,
                    "cost_ref": c_ref,
                    "carbon_ref": e_ref,
                }
            )
        if (i + 1) % 10 == 0:
            print(f"    sample day {i + 1}/{len(blocks)}", flush=True)
    return pd.DataFrame(rows)


def summarize(annual: pd.DataFrame) -> dict:
    """Headline annual numbers, all relative to the unmanaged baseline."""
    tot = annual.sum(numeric_only=True)
    return {
        "days": int(len(annual)),
        "unmanaged_cost": float(tot.unmanaged_cost),
        "unmanaged_carbon_kg": float(tot.unmanaged_carbon),
        "cost_opt_saving_pct": 100.0
        * (tot.unmanaged_cost - tot.cost_opt_cost)
        / tot.unmanaged_cost,
        "cost_opt_carbon_change_pct": 100.0
        * (tot.cost_opt_carbon - tot.unmanaged_carbon)
        / tot.unmanaged_carbon,
        "carbon_opt_saving_pct": 100.0
        * (tot.unmanaged_carbon - tot.carbon_opt_carbon)
        / tot.unmanaged_carbon,
        "carbon_opt_cost_change_pct": 100.0
        * (tot.carbon_opt_cost - tot.unmanaged_cost)
        / tot.unmanaged_cost,
        # Cost premium of going from the cost optimum to the carbon optimum,
        # per kg of CO2 avoided. This is the implied abatement cost, and it is
        # the number that decides whether carbon-aware dispatch is worth doing.
        "implied_abatement_cost_per_kg": float(
            (tot.carbon_opt_cost - tot.cost_opt_cost)
            / max(tot.cost_opt_carbon - tot.carbon_opt_carbon, 1e-9)
        ),
    }
