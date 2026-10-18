# hosting-capacity-sim

DER hosting capacity screening on synthetic distribution feeders, built on
[pandapower](https://pandapower.readthedocs.io). The point of the module is to
make the screening logic underneath Fast Track and Supplemental Review explicit
and runnable, so you can see which screen actually binds and by how much.

> **This is an educational model.** The feeders are synthetic archetypes built
> from typical US overhead distribution parameters. They are not calibrated to
> any real circuit, contain no utility data, and must not be used for an actual
> interconnection decision.

## Running it

```bash
pip install -r ../requirements.txt
python run_analysis.py                      # everything
python run_analysis.py --stage results      # one stage at a time
python run_analysis.py --stage nodal --feeder rural
```

Stages cache to `data/processed/hosting-capacity-sim/` and are resumable, which
matters because the volt-var nodal maps take a few minutes each.

## The screens, and how they map to real practice

Five screens are evaluated, deliberately kept in three separate categories.

| Screen | Category | Threshold | What it corresponds to |
|---|---|---|---|
| `voltage` | physical | 0.95 to 1.05 pu | ANSI C84.1 Range A steady-state service voltage |
| `thermal` | physical | 100% of ampacity | Conductor rating |
| `reverse_power` | operational | net export at substation | Station-level backfeed, a study trigger for relay coordination and LTC control |
| `penetration_15` | paper | 15% of line section peak load | The classic FERC SGIP Fast Track penetration screen |
| `min_daytime` | paper | 100% of minimum daytime load | The Supplemental Review penetration test |

**The headline hosting capacity number is voltage and thermal only.** That
matches how published utility hosting capacity maps define the term, and the
separation is load-bearing rather than cosmetic:

- Bundling `reverse_power` into the headline number would force every radial
  feeder's hosting capacity to equal its minimum daytime load, because on a
  radial circuit net export begins at almost exactly the point where DER
  exceeds load. That would hide all of the voltage and thermal behavior the
  model exists to study. It is reported as its own limit instead.
- The paper screens are administrative. Failing `penetration_15` routes an
  application out of Fast Track and into Supplemental Review. It does not make
  the interconnection infeasible, and conflating the two is the single most
  common way this analysis gets misread.

Hosting capacity is assessed at **minimum daytime load** (default 30% of peak,
the common proxy when measured minimum daytime load is unavailable), because
that is the condition under which net export and therefore voltage rise is
worst.

## Feeder archetypes

| Archetype | Buses | Length | Peak load | Conductor |
|---|---|---|---|---|
| rural | 30 | 46.2 km | 1.03 MW | 336 ACSR tapering to 1/0 |
| suburban | 20 | 16.0 km | 3.00 MW | 477 then 336 ACSR |
| urban | 12 | 3.9 km | 6.60 MW | 477 ACSR throughout |

All at 12.47 kV, substation bus held at 1.02 pu.

## Findings

**1. The Fast Track 15% screen is 6x to 17x more conservative than the physics.**

| Feeder | Voltage/thermal limit | Fast Track 15% threshold | Ratio |
|---|---|---|---|
| rural | 0.87 MW | 0.15 MW | 5.7x |
| suburban | 6.02 MW | 0.45 MW | 13.4x |
| urban | 16.94 MW | 0.99 MW | 17.1x |

The gap widens as the feeder gets stiffer, which is the opposite of what you
would want from a screen: the 15% rule is most conservative exactly where the
circuit can most easily absorb DER. This is a known criticism of the screen in
the literature, and it reproduces cleanly here. The screen is doing its job as
a cheap conservative filter, but a project that fails it is not close to a real
limit on any of these three feeders.

**2. Which screen binds is a property of the archetype, not the penetration.**

Rural and suburban feeders are voltage-limited. The urban feeder is
thermal-limited, and it is the only one where the substation reverse-power
trigger is not the first thing to trip. That distinction drives what the fix
costs: a voltage-limited feeder can often be addressed with inverter settings
or a regulator, while a thermal-limited one needs reconductoring.

**3. Volt-var helps only where voltage binds, and only if the inverter has
headroom.**

With inverters sized at the Category B minimum (S/P = 1.1136, defined below):

| Feeder | Volt-var off | Volt-var on | Uplift | Binding screen, off -> on |
|---|---|---|---|---|
| rural | 0.87 MW | 1.08 MW | 1.24x | voltage -> voltage |
| suburban | 6.02 MW | 15.86 MW | 2.64x | voltage -> thermal |
| urban | 16.94 MW | 16.76 MW | 0.99x | thermal -> thermal |

The conditional structure is the robust part. Where voltage binds, volt-var
raises hosting capacity; where current binds, it very slightly lowers it,
because absorbing vars to pull voltage down adds current on a circuit that was
already current-limited. On the suburban feeder volt-var buys enough voltage
headroom that the binding screen flips to thermal, which is why the uplift
stops there.

**The uplift is a cliff in inverter sizing, not a slope.** At S/P = 1.00, an
inverter running at full real output has no reactive headroom, and volt-var
gives exactly 1.00x on all three feeders. Two percent of oversizing recovers
most of the benefit (suburban 2.30x at S/P = 1.02), and it saturates by about
S/P = 1.06 once the thermal limit takes over. See
`outputs/hosting-capacity-sim/inverter_sizing.png`.

> **Correction.** An earlier version of this README reported a 2.41x suburban
> uplift with `inverter_oversize=1.0`, and described that setting as the
> conservative case in which vars compete with real power headroom. The code
> never enforced that constraint. At the reported hosting capacity all 20
> inverters were running up to 2.4% over their kVA rating, and the uplift came
> from that violation: enforced correctly, S/P = 1.00 gives exactly 1.00x.
> `volt_var.solve` now clips reactive output to sqrt(S^2 - P^2), and a test
> asserts no inverter ever exceeds its rating. The corrected number at the
> Category B minimum happens to be larger, 2.64x, because a compliant inverter
> has more var headroom than the old model's 44% of real power.

**4. Siting matters more than anything else on a weak feeder.**

Concentrating the same nameplate at the end of the rural feeder rather than at
its midpoint costs 3.35x of hosting capacity (0.32 MW vs 1.06 MW). On the urban
feeder the same choice only costs 1.23x. Locational value of DER is real and it
scales with feeder impedance.

## Figures

- `outputs/hosting-capacity-sim/screen_comparison.png` where each screen binds
- `outputs/hosting-capacity-sim/nodal_hosting_capacity.png` capacity vs distance from substation
- `outputs/hosting-capacity-sim/voltage_rise_sweep.png` voltage rise vs penetration
- `outputs/hosting-capacity-sim/siting_strategy.png` siting strategy comparison
- `outputs/hosting-capacity-sim/inverter_sizing.png` volt-var uplift vs inverter S/P

## Modeling assumptions

Stated here rather than buried, because every one of them moves the answer:

1. **Balanced positive-sequence.** Single-phase laterals are not modeled. Real
   unbalanced hosting capacity is generally *lower* than reported here.
2. **No voltage regulators or switched capacitors mid-feeder.** This is the
   conservative "no active voltage support" case. A mid-feeder regulator
   materially raises voltage-limited capacity.
3. **Constant-power loads at 0.95 lagging.** No ZIP or voltage-dependent load
   modeling, which would slightly relax voltage limits.
4. **Static snapshot at minimum daytime load**, not an 8760 quasi-static
   time series. A full QSTS run would catch tap-changer and capacitor
   interactions this misses.
5. **Inverters sized at the Category B minimum, S/P = 1.1136, with real power
   priority.** Category B requires 44% of nameplate kVA as var capability.
   Delivering that at rated real power needs P^2 + (0.44 S)^2 <= S^2, so
   S/P >= 1/sqrt(1 - 0.44^2) = 1.1136. That is arithmetic from the capability
   table, not an empirical assumption. Reactive output is always clipped to the
   headroom sqrt(S^2 - P^2). Because the result depends so sharply on this
   choice near S/P = 1, every result row records its `inverter_oversize`, and
   the `sizing` stage reports the full sensitivity.
6. **Bisection assumes monotonicity** of the pass/fail boundary in DER size.
   `verify_monotonic()` brute-force checks this rather than assuming it, and it
   passes for all three archetypes.

## Layout

```
hosting-capacity-sim/
  hcsim/
    feeders.py           archetype construction, conductor library
    screens.py           screen definitions and the three-way taxonomy
    volt_var.py          IEEE 1547-2018 Category B curve, apparent-power limit,
                         damped fixed point
    hosting_capacity.py  bisection search, nodal maps, sweeps
  run_analysis.py        staged, resumable pipeline
```
