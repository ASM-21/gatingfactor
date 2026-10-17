# tariff-explorer

Residential and small commercial tariff structures with monthly bill impact
modeling across five customer archetypes, plus a Streamlit dashboard for
adjusting rate parameters live.

```bash
pip install -r ../requirements.txt
python run_analysis.py        # regenerate tables and figures
streamlit run app.py          # interactive dashboard
```

## Data provenance

| Series | Status | Notes |
|---|---|---|
| Archetype load shapes | **Synthetic** | NREL ResStock and ComStock unreachable. Parameterized diurnal and seasonal forms in `shared/loadshapes.py` |
| Rate levels | **Representative** | Realistic mid-Atlantic levels, not filed tariffs |
| Rate structures | **Real forms** | Flat, inclining block, TOU, demand charge, and hybrid are the actual structures in use |

The distinction that matters: conclusions of the form "TOU shifts *this*
archetype's bill relative to *that* one" are sound, because they depend on
shape and structure. Conclusions of the form "a PA household would pay $X" are
not, because they depend on level. Swap in ResStock and a filed tariff before
quoting any dollar figure.

## Structures modeled

| Structure | What it prices |
|---|---|
| `flat` | Nothing beyond volume. The reference case |
| `tiered` | Monthly volume, via inclining blocks that reset each month |
| `tou` | Timing, via on/mid/off peak windows with weekends off-peak |
| `demand` | Peak, via a monthly maximum kW charge plus a lower energy rate |
| `hybrid_tou_demand` | Both timing and peak |

Billing is **monthly**, which is not a detail. Tiers reset monthly, demand is
assessed on a monthly maximum, and minimum bills apply per month. Computing an
annual bill as twelve times an average month throws away exactly the effects
this module exists to measure. There is a test pinning each of those three.

Export is credited either at full retail (net energy metering) or at a
specified net billing rate. This single choice moves the solar archetype's bill
more than any structural choice between TOU and tiered.

## Revenue neutrality

Every comparison holds **total revenue constant within customer class**. This
matters twice over.

Without it, a tariff comparison mostly measures which structure happened to be
written with higher rates, not how it allocates cost. Rate design arguments are
about allocation, so the scale factor has to be solved out first.

And *within class* rather than across, because scaling one structure across
both residential and commercial archetypes produces a large apparent
cross-subsidy that is purely a modeling artifact: real tariffs are
class-specific, and no utility applies a residential inclining block rate to a
120,000 kWh/year commercial account. Running it that way makes tiered rates look
like they shift 18% of cost from residential to commercial, which says nothing
about tiered rates and everything about a category error.

## Findings

Bill change versus a flat rate, at equal revenue within class, sorted by load
factor:

| Archetype | Load factor | tiered | tou | demand | hybrid |
|---|---|---|---|---|---|
| Home with EV | 0.13 | -0.3% | +8.7% | **+28.8%** | +24.7% |
| Small commercial, daytime | 0.32 | 0.0% | +8.7% | +7.6% | +12.4% |
| Home with rooftop solar | 0.31 | -8.7% | **-32.6%** | **+36.2%** | +3.5% |
| All-electric home | 0.44 | +1.7% | -3.0% | **-32.7%** | -23.6% |
| Small commercial, flat | 0.74 | 0.0% | -8.7% | -7.6% | -12.4% |

**1. A demand charge prices load factor, and solar customers get hit hardest.**

The solar archetype offsets **83.3% of annual energy but only 4.9% of peak
demand**, because its net peak lands at 20:00 when PV output is exactly zero.
Under a demand charge at equal revenue it pays **36.2% more** than under a flat
rate, despite consuming the least net energy of any archetype in the set.

This is the mechanism behind a live and contested question in rate design.
Utilities argue demand charges recover fixed costs that volumetric rates miss
from solar customers; solar advocates argue they nullify the value of the
investment. Both descriptions are of the same arithmetic, and it is reproduced
here from first principles rather than asserted.

**2. TOU and demand charges point in opposite directions for the same customer.**

The solar archetype is the best performer under TOU (-32.6%, because generation
lands squarely in the on-peak window) and the worst under a demand charge
(+36.2%). A 69 percentage point swing on the same customer, from two structures
that are both defensible on cost-causation grounds. Which structure a utility
picks is a larger determinant of a solar customer's economics than the size of
their array.

**3. Load factor predicts demand-charge impact, imperfectly.**

Correlation across the five archetypes is **r = -0.59**. It would be much
stronger without the solar archetype, which is the outlier precisely because
net metering decouples its energy from its peak. Load factor is a good first
screen for who a demand charge helps, but it fails for exactly the customers
who generate the most controversy.

**4. Inclining block rates do nothing once everyone is in the top tier.**

Both commercial archetypes show a 0.0% change under tiered rates. At 120,000
kWh/year they are entirely in the third tier, so the structure is
indistinguishable from a flat rate for them. Tiered rates only differentiate
customers whose usage straddles a threshold, which is a real constraint on
using them as a conservation signal for large accounts.

## Figures

- `outputs/tariff-explorer/bill_change_heatmap.png` who wins and loses, at equal revenue
- `outputs/tariff-explorer/load_factor_vs_impact.png` load factor vs bill impact
- `outputs/tariff-explorer/archetype_shapes.png` net load shapes, average day
- `outputs/tariff-explorer/bill_composition.png` bill stack by component

## Limitations

1. Synthetic load shapes. Shape-driven conclusions hold; level-driven ones do not.
2. Representative rather than filed rates.
3. Hourly intervals, so demand is a 60 minute average. Real demand charges
   often use a 15 or 30 minute integration window, which would raise measured
   peaks for the EV archetype in particular.
4. No seasonal rate differentiation, which most real TOU tariffs have.
5. One year, one weather realization. No weather normalization.
6. The EV archetype charges unmanaged. `shared.loadshapes.ev_charging` supports
   `managed=True`, and comparing the two under TOU is the obvious next cut.

## Layout

```
tariff-explorer/
  texplorer/
    tariffs.py      structures, monthly billing, export compensation
    archetypes.py   five archetypes, bill matrix, revenue-neutrality solver
  run_analysis.py   tables and figures
  app.py            Streamlit dashboard
```

Load shapes live in `shared/loadshapes.py` so this track and `carbon-aware-der`
cannot drift on what "a household" means. There is a test asserting the two
produce identical arrays.
