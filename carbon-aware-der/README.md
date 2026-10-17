# carbon-aware-der

Carbon-aware dispatch of residential DER (home battery, EV charging) against
**real hourly PJM grid carbon intensity**. This extends carbon-aware scheduling
from the manufacturing load-scheduling setting into grid-facing distributed
energy resources.

The headline result: **which carbon signal you optimize against matters more
than how well you optimize.** Scheduling a home battery and EV against PJM's
published *average* carbon intensity looks like a 2.9% emissions reduction and
is actually a **10.5% increase** in marginal emissions, on 359 of 364 days.
Switching to an estimated *marginal* signal turns that into a genuine 6.7%
reduction, and does so while still costing 4.8% less than no control at all.

## Running it

```bash
pip install -r ../requirements.txt
python run_analysis.py --stage annual     # full year, both objective extremes
python run_analysis.py --stage frontier   # weight sweep
python run_analysis.py --stage figures
```

## Data provenance

Stated per series, because they differ and it matters:

| Series | Status | Source |
|---|---|---|
| Hourly carbon intensity | **Real** | [CarbonCast](https://github.com/carbonfirst/CarbonCast) (Apache-2.0), EIA-derived. 2020-2021, 17,544 rows, no gaps |
| Retail price | **Representative structure** | TOU schedule with realistic mid-Atlantic shape and levels. Not a filed tariff |
| Household base load | **Synthetic** | Parameterized residential shape scaled to ~10,500 kWh/yr |

The carbon series is the load-bearing input and it is real. The price signal is
a stand-in because no LMP or retail rate source was reachable; swap in a real
tariff before drawing conclusions about a specific rate. Base load is the
lowest-stakes of the three: with no demand charge and no export, it moves the
totals but barely moves the dispatch decision, which is driven by the price and
carbon *shapes*.

**Average vs marginal emissions.** Marginal emissions are the theoretically
correct signal for a dispatch decision, since what matters is which generator
moves when you shift a kWh. Average intensity is what is published hourly.

An earlier version of this README claimed the average signal was merely
conservative here. **That was wrong**, and `cader/marginal.py` now shows why:
in PJM the two signals are anti-correlated across the day (r = -0.66), and the
marginal signal swings 4.1x harder. Using average intensity does not understate
the answer, it points the controller in the wrong direction. See "The signal
matters more than the optimizer" below.

## Method

A MILP per 24 hour horizon (noon to noon, so the overnight EV window does not
wrap), solved with PuLP/CBC over all 364 days of 2021.

Decision variables: battery charge, discharge, state of charge, and EV charging
energy, with a binary enforcing charge/discharge exclusivity. Grid draw is
`base + charge - discharge + ev`, constrained non-negative (no export).

Objective is a normalized weighted sum:

```
minimize  w * (cost / cost_ref)  +  (1 - w) * (carbon / carbon_ref)
```

where the reference values are that same day's two single-objective optima.
Without normalization, `w` would just encode the ratio of $/kWh to kg/kWh and
would not be interpretable across days.

Two constraints that matter more than they look:

- **Terminal SOC** (`soc[T-1] >= soc_init`) stops the optimizer draining the
  battery over the horizon and booking stored energy as free savings. Omitting
  this is the most common way a result like this gets inflated.
- **No export**, which avoids needing an avoided-emissions assumption for
  exported energy.

The baseline everything is measured against is **unmanaged** dispatch: battery
idle, EV charges flat out on plug-in. That is what happens without a controller.

## Findings

### 1. The carbon signal in PJM is too weak to act on

Within-day carbon intensity spread averages **40 gCO2/kWh** (p10 25, p90 57)
against a ~300 gCO2/kWh base. Diurnal swing is 10.1% of the mean; annual
max/min ratio is only 1.97.

Achievable daily carbon saving correlates with that day's within-day spread at
**r = 0.79**. The constraint is the signal, not the optimizer.

### 2. Annual results, 2021

Baseline: $2,316 and 4,663 kg CO2.

| Objective | Cost vs unmanaged | Carbon vs unmanaged |
|---|---|---|
| Cost-optimal | **-34.0%** | +0.02% |
| Carbon-optimal | -22.1% | **-2.94%** |

Both beat doing nothing on cost, because a TOU spread of 0.09 to 0.24 $/kWh is
a much stronger signal than anything carbon provides. Cost optimization is
carbon-*neutral* on the year, but that average hides the real behavior:

### 3. Cost optimization increases emissions on 48% of days

On **175 of 364 days**, minimizing cost against the TOU rate raised emissions
relative to unmanaged dispatch. It nets to roughly zero over the year, which
means a TOU rate is not a carbon proxy in PJM. It is close to a coin flip.

This is the finding with policy content. Rate designs justified partly on
emissions grounds should be checked against the actual regional carbon shape
rather than assumed to align.

### 4. The frontier is nearly degenerate

Sweeping `w` from 1.0 down to 0.25 changes almost nothing (cost moves by $0.04
over 52 sampled days). Essentially the entire tradeoff lives between w = 0.1
and w = 0:

| Segment | Cost premium | Carbon avoided | Implied abatement cost |
|---|---|---|---|
| w=1 to w=0.1 | +4.9% | 13.3 kg | ~$840/tonne |
| w=0.1 to w=0 | +13.1% | 2.5 kg | ~$11,800/tonne |
| Full, annual | +18.0% | 138 kg | **~$1,985/tonne** |

For reference, the social cost of carbon is commonly put in the $50 to $200 per
tonne range. Even the cheapest segment is roughly 4x the top of that range.

### 5. The signal matters more than the optimizer

Everything above scores dispatch against **average** carbon intensity, which is
what is published hourly. That turns out to be the wrong yardstick, and it
inverts the conclusion.

`cader/marginal.py` estimates hourly **marginal** emissions factors from PJM
fuel-mix data by regressing hourly changes in emissions on hourly changes in
generation, within hour-of-day by season bins. A naive fit conflates load
following with renewable ramping, so a renewable-ramp regressor is added; that
lifts pooled R2 from 0.878 to 0.937, puts the pooled marginal factor at
437.8 kg/MWh against an average of 310, and gives the renewable coefficient
the expected negative sign (-472 kg/MWh).

The two signals do not agree:

| | Average (published) | Marginal (estimated) |
|---|---|---|
| Annual mean | 310 kgCO2/MWh | 430 kgCO2/MWh |
| Diurnal swing | 8.8% of mean | **36.2% of mean** |
| Peak hour | evening | **overnight** |

They are **anti-correlated across the day, r = -0.66**, and the marginal signal
is **4.1x stronger**. Marginal emissions are highest overnight, which is exactly
where both cheap TOU prices and slightly-lower average intensity push a
controller.

Running four strategies over 2021 and scoring all of them on marginal
emissions, the yardstick that reflects what actually changes:

| Strategy | Cost | Avg-carbon score | **Marginal-carbon score** |
|---|---|---|---|
| unmanaged | 0.0% | 0.0% | 0.0% |
| cost only | -34.0% | +0.0% | +9.0% |
| avg signal | -22.1% | **-2.9%** | **+10.5%** |
| marginal signal | -4.8% | +3.9% | **-6.7%** |

The average-signal controller helps on the average score and hurts on the
marginal score on **359 of 364 days**. It is not slightly less effective than
it appears; it is pointed the wrong way.

The economics change with it. On the marginal yardstick, moving from
cost-optimal to marginal-optimal implies **$713/tonne**, still high but a third
of the earlier figure. More importantly, marginal-aware dispatch versus doing
nothing is **cheaper by 4.8% and lower carbon by 6.7% simultaneously**. There is
no tradeoff to trade off: it is free.

This independently reproduces a finding from the sibling `oss-lca-toolkit`
project, where scheduling manufacturing load on PJM's average signal likewise
flipped sign when scored on marginal.

**Caveats on the marginal estimate.** It assumes observed hourly deltas are
dominated by load following rather than unit commitment or transmission
constraints, cannot see intra-hour dispatch, and resolves a single system-wide
factor with no locational detail. It is an estimate, not a measurement. But the
sign and magnitude of the disagreement with the average signal are far too
large to be explained by estimator error.

### 6. What this implies

Residential carbon-aware DER dispatch **is** worth doing in PJM, but only
against a marginal signal. Built on the published average signal, which is what
a developer would reach for first because it is the data that exists, it is
actively counterproductive. This is a regional statement in its specifics:
the same method in a region with strong diurnal carbon variation (high solar
penetration, so a deep midday trough and steep evening ramp) should produce a
far better result. Regional carbon-signal strength, not optimizer
sophistication, is the variable that decides whether this is worth doing.

That is the natural framing for a paper: the manufacturing carbon-aware
scheduling literature largely reports method improvements. The more actionable
question is where the method is worth applying at all, and the answer is
strongly region-dependent.

## Figures

- `outputs/carbon-aware-der/carbon_vs_price.png` carbon shape vs TOU price shape
- `outputs/carbon-aware-der/tradeoff_frontier.png` the cost/carbon frontier
- `outputs/carbon-aware-der/monthly_savings.png` cost vs carbon savings by month
- `outputs/carbon-aware-der/example_day.png` dispatch traces for one day
- `outputs/carbon-aware-der/signal_profiles.png` average vs marginal, the anti-correlation
- `outputs/carbon-aware-der/signal_choice.png` four strategies on both yardsticks

## Limitations

1. The marginal factor is a regression estimate from system-level fuel mix, not a measured dispatch response. See the caveats in finding 5.
2. Price signal is a representative structure, not a filed tariff. Cost
   percentages will move with a real rate; the carbon conclusions will not.
3. Perfect foresight over each 24 hour horizon. A real controller works from a
   forecast, so these are upper bounds on achievable savings.
4. Synthetic household base load.
5. No degradation cost on the battery. Including it would make carbon-aware
   dispatch look worse still, since it cycles the battery harder.
6. Single home. No aggregation or distribution-network feedback, and no
   coupling to the feeder constraints modeled in `hosting-capacity-sim`.

## Layout

```
carbon-aware-der/
  cader/
    data.py        carbon / price / load assembly, provenance documented per series
    optimizer.py   MILP formulation, unmanaged baseline, single-objective anchors
    frontier.py    annual rollup and weighted-sum Pareto sweep
    marginal.py    marginal emissions estimation with renewable-ramp control
    signal_choice.py  four-strategy comparison scored on both yardsticks
  run_analysis.py  staged, resumable pipeline
```
