# Contributing

The most useful thing you can do here is attack a number.

Four of these findings rest on data or models that could be better, and three
specific claims have no independent corroboration at all. Those are listed
first because they are where this repository is most likely to be wrong.

## Attack a claim

Each of these has a finish line. You do not need to read the whole repo.

**1. The three uncorroborated numbers.** In rough order of how load-bearing
they are:

| Claim | Where | Why it is shaky |
|---|---|---|
| Volt-var gives 2.41x on a voltage-limited feeder | `hosting-capacity-sim` | One archetype's value reported as if typical. A sampled population would likely show a much lower median |
| Load factor predicts demand-charge impact at r = -0.59 | `tariff-explorer` | Five archetypes is not a sample. The correlation is driven by which five were picked |
| The 5.2x survivorship ratio | `interconnection-analytics` | Rests on the 62.8% of rows with a usable terminal date. If those differ systematically from the rest, the ratio moves |

Finish line: a script under `tools/` that recomputes the claim a different way
and either corroborates it or does not, plus a line in FINDINGS.md.

**2. Run track 2 against a real feeder.** Every feeder in
`hosting-capacity-sim/hcsim/feeders.py` is synthetic. An IEEE 34-bus or 123-bus
test feeder, or any published real circuit model, would turn the strongest
caveat in the repo into a validated result. Start at `feeders.SPECS` and add a
loader beside it.

Finish line: one real feeder's hosting capacity computed by the same screens,
compared to the three archetypes.

**3. Replace track 3's synthetic load shapes.** `shared/loadshapes.py` is
parameterized, not measured, because NREL ResStock was unreachable from the
build environment. Swapping in real ResStock or ComStock profiles would make
every dollar figure in `tariff-explorer` quotable rather than illustrative.

Finish line: `build_archetypes()` reading real profiles, and the revenue-neutral
table regenerated.

**4. Run track 3 on a filed tariff.** The rate levels are representative, not
real. An OpenEI URDB key and a parser would fix this.

Finish line: one real filed residential tariff priced through
`texplorer/tariffs.py`.

**5. Unblock track 4 or 5.** Both need network access this build environment did
not have. Track 4 needs PJM Data Miner LMP and RPM auction history; track 5
needs the PA PUC e-filing site. Each track's README states the target schema.

Finish line: a working ingest that lands in `data/raw/` and a canonical frame
in `data/processed/`.

**6. Interchange-adjust the marginal emissions estimate.** CarbonCast has
generation by fuel but no demand column, so total generation is a load proxy
net of interchange. EIA-930 interchange data would fix it, and import-heavy
regions are where the current estimate is weakest.

Finish line: `cader/marginal.py` using net load rather than generation, and the
pooled MEF recomputed.

## Ground rules

- **Every number in prose must recompute.** If you add a figure to a README,
  add it to `tools/check_claims.py` with code that derives it from committed
  results. `make claims` must pass.
- **Every headline needs a test** that fails on drift.
- **Say what is real and what is modeled**, per data series, at the top of the
  module. The repo's whole credibility rests on that line being accurate.
- **Do not add any non-public data.** CI greps for named utilities, internal
  document markers, and committed credentials.
- Run `make test && make claims` before opening a PR.

## Setup

```bash
pip install -r requirements.txt     # or requirements-lock.txt for exact pins
make test
make claims
```
