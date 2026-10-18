# gatingfactor

[![CI](https://github.com/ASM-21/gatingfactor/actions/workflows/ci.yml/badge.svg)](https://github.com/ASM-21/gatingfactor/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Citation](https://img.shields.io/badge/cite-CITATION.cff-green.svg)](CITATION.cff)

**What actually gates distributed energy resource value: four studies of
interconnection queues, hosting capacity screens, retail rate structures, and
grid carbon signals.**

DER is usually discussed as a control problem. Four independent studies here,
each with its own data and method, land on the same structural answer: the
context a project sits in dominates the control layered on top, and it is not
close.

| Track | Context variable | Spread it produces |
|---|---|---|
| 1 interconnection queues | whether the project survives the queue | 68% withdraw vs 24% complete in PJM |
| 2 hosting capacity | which feeder it connects to | 5.7x to 17.1x gap between screen and physics |
| 3 tariff design | which rate structure the utility picked | 69 point bill swing on one customer |
| 6 carbon-aware dispatch | which carbon signal the controller reads | sign flip: -2.9% becomes +10.5% |

Full numbered argument with scope conditions and falsification criteria:
**[FINDINGS.md](FINDINGS.md)**.

> **Disclaimer.** This is an independent personal project. It is not
> affiliated with, reviewed by, or endorsed by any employer. It uses public
> data and synthetic models only. No non-public, proprietary, customer, or
> utility-internal data appears in this repository or its history, and it was
> not produced on employer time or systems.

## Quickstart

```bash
pip install -r requirements.txt
make test                       # 155 tests
make claims                     # 170 prose checks, recomputed from results
make report                     # regenerate every figure and table
make dashboard                  # tariff-explorer Streamlit app
```

The `pulp<4` bound in `requirements.txt` is load-bearing. PuLP 4.0 is a
rustcore rewrite that removed `LpVariable.dicts` and `PULP_CBC_CMD` and ships
no bundled solver; installing it silently breaks every MILP in
`carbon-aware-der`. `requirements-lock.txt` has the exact versions of the last
green run.

## Why you can trust the numbers

- **Every quoted figure recomputes.** `tools/check_claims.py` pairs each number
  in the prose with code that derives it from the committed results and exits
  non-zero on drift. Changing a number in a README without rerunning the
  pipeline fails the build; so does changing the pipeline without updating the
  prose.
- **Caveats are enforced, not decorative.** Deleting the synthetic-data
  caveats, the data attributions, or the disclaimer above breaks the build.
- **Overclaiming is blocked.** The guard rejects `proves`, `guaranteed`,
  `for the first time` and similar in every markdown file. It ignores phrases
  inside backticks, so the ban can be documented without tripping itself.
- **Every headline is pinned by a test** that fails on drift, not just by the
  prose guard.
- **Retracted claims stay visible.** Three earlier claims were wrong: that the
  average carbon signal was merely "conservative" (track 6), a 2.41x volt-var
  uplift that came from inverters running over their kVA rating (track 2), and
  a 5.2x queue-wait understatement from a survival fit that treated
  withdrawals as censoring (track 1). All three are listed in FINDINGS.md and
  corrected in place, not quietly deleted. All three had the same cause, prose
  describing a property the code did not have, which is what the guards above
  exist to catch.

## Status

| # | Track | Status | Notes |
|---|---|---|---|
| 1 | `interconnection-analytics` | **Complete** | LBNL Queued Up 2025, 36,441 real requests. 32 tests, 6 figures |
| 2 | `hosting-capacity-sim` | **Complete** | pandapower, 3 synthetic feeder archetypes. 41 tests, 5 figures |
| 3 | `tariff-explorer` | **Complete** | 5 structures x 5 archetypes, Streamlit app. 27 tests, 4 figures |
| 4 | `pjm-market-tools` | Not built | Blocked: needs PJM Data Miner LMP and RPM auction data |
| 5 | `docket-tracker` | Not built | Blocked: needs the PA PUC e-filing site |
| 6 | `carbon-aware-der` | **Complete** | Real PJM carbon data, MILP dispatch. 35 tests, 6 figures |

**The blocker, stated once.** `pjm.com` and `puc.pa.gov` return HTTP 403 at the
egress proxy of the environment this was built in, so tracks 4 and 5 cannot be
validated against real data. They carry status READMEs describing exactly what
to fetch and the target schema, rather than fabricated ingest code. Tracks 1
and 6 were unblocked by finding their primary sources mirrored on GitHub, which
is documented per track and in [NOTICE](NOTICE).

## Findings

**Interconnection queues (track 1).** There is no median wait for a project
entering the queue. No cohort entering from 1995 through 2019 has had more than
34.1% of its requests reach operation, so the quoted time-to-interconnect
median, computed over completed projects, describes the minority that finished.
Read before a cohort resolves, that median is also truncated: re-reading three
fully resolved cohorts at earlier dates, it ran 1.55x to 2.06x low at the close
of the entry window. Withdrawal is the modal outcome in every region: PJM sees
68.0% withdraw against 23.8% completing, and PPL's own queue (470 requests,
49.5 GW) tracks that closely at 67.7% and 15.5%. An earlier version reported a
5.2x understatement from a survival fit that treated withdrawals as censoring;
it is retracted in FINDINGS.md.

**Hosting capacity (track 2).** The FERC SGIP Fast Track 15%-of-peak-load
screen binds 5.7x to 17.1x below the voltage and thermal limit across three
feeder archetypes, and the gap *widens* on stiffer feeders. Which screen binds
is a property of the archetype: rural and suburban are voltage-limited, urban
thermal-limited. IEEE 1547 Category B volt-var buys 2.64x on a voltage-limited
feeder and nothing (0.99x) on a thermally-limited one, where absorbing vars
adds current to an already current-limited circuit. That uplift exists only if
the inverter has kVA headroom: sized exactly to its real output (S/P = 1.00) it
gives 1.00x everywhere, and 2% of oversizing recovers most of it.

**Tariff design (track 3).** Holding revenue constant within customer class,
the rooftop solar archetype is the *best* performer under TOU (-32.6%) and the
*worst* under a demand charge (+36.2%): a 69 percentage point swing on the same
customer from two structures both defensible on cost-causation grounds. Solar
offsets 83.3% of annual energy but only 4.9% of peak, because the net peak
lands at 20:00 when PV output is zero. Load factor predicts demand-charge
impact at only r = -0.59, with solar the outlier precisely because net metering
decouples energy from peak.

**Carbon-aware DER (track 6).** Which carbon signal a controller reads matters
more than how well it optimizes. Scheduling a home battery and EV against PJM's
*published average* carbon intensity scores -2.9% on the average yardstick and
is a **10.5% increase** on the marginal one, on 359 of 364 days. The two
signals are anti-correlated across the day (r = -0.66) and the marginal signal
swings 4.1x harder, peaking overnight exactly where cheap TOU prices pull load.
An estimated marginal signal delivers a real 6.7% reduction while still costing
4.8% less than no control at all, so it is free.

## Shared conventions

Every track imports from `shared/`, so a number from one track can sit beside a
number from another without a units conversation.

```python
from shared import paths, units, plotting, io, loadshapes

paths.raw("pjm", "file.csv")          # data/raw/pjm/file.csv
paths.processed("track", "x.parquet") # data/processed/track/x.parquet
paths.output("track", "fig.png")      # outputs/track/fig.png
```

- **Power in MW, energy in MWh** at the analysis layer, because that is what
  pandapower and RTO data both speak. Tariff math converts to kW/kWh at the
  edges only.
- **Prices in $/MWh** internally, converted at the customer-facing edge.
- **Emissions in kg CO2e/MWh**, numerically identical to the gCO2/kWh that most
  public carbon sources publish.
- **Per-unit voltages** referenced to ANSI C84.1.
- **Raw pulls are written once and never mutated.** Derived data goes to
  parquet under `data/processed/`, so a warm cache needs no network.
- **Load shapes live in `shared/loadshapes.py`** so tracks 3 and 6 cannot drift
  on what "a household" means. A test asserts the two produce identical arrays.

## Data provenance policy

Every track states, per data series, whether it is real, a representative
structure, or synthetic. This is not boilerplate: track 6's conclusions rest
entirely on the carbon series being real, while its cost percentages rest on a
representative TOU structure that should be swapped for a filed tariff before
anyone quotes them.

Where a primary source was unreachable the workaround is documented rather than
papered over. See [NOTICE](NOTICE) for the full third-party data inventory and
licensing.

## Layout

```
gatingfactor/
  FINDINGS.md               the numbered argument, with scope and falsification
  data/raw/                 cached source pulls, never mutated
  data/processed/           derived parquet, regenerated by `make report`
  outputs/<track>/          figures, CSVs, summaries
  shared/                   paths, units, plotting theme, cached I/O, load shapes
  tests/                    155 tests: 135 across the four tracks, 20 on the guards
  tools/check_claims.py     prose guard: recomputes every quoted figure
  <track>/                  one directory per track, each with its own README
```

## Contributing

Scoped first contributions, ordered by value, are in
[CONTRIBUTING.md](CONTRIBUTING.md). The highest-value ones attack the numbers
that nothing else corroborates.

## Citing

See [CITATION.cff](CITATION.cff), or cite FINDINGS.md directly.

Licensed under Apache-2.0. Third-party data keeps its own license; see
[NOTICE](NOTICE).
