# Findings

The citable summary. Each finding is numbered, scoped, and paired with the
code that recomputes it. `python tools/check_claims.py` fails the build if any
figure here drifts from the committed results.

---

## The argument

Distributed energy resources are usually discussed as a control problem: how
well does the scheduler dispatch, how smart is the inverter, how good is the
forecast. Four independent studies here, each with its own data and method,
converge on the same structural answer.

**What gates a DER project's value is its context, not the sophistication of
the control layered on top.** Across all four tracks, the context variable
dominates by a margin that control improvements cannot close:

| Track | Context variable | Spread it produces |
|---|---|---|
| 1 | whether the project survives the queue at all | 68.0% withdraw vs 23.8% complete in PJM |
| 2 | which feeder it connects to | 5.7x to 17.1x gap between screen and physics |
| 3 | which rate structure the utility picked | 69 percentage point swing on one customer |
| 6 | which carbon signal the controller reads | sign flip: -2.9% becomes +10.5% |

This is not a claim that control does not matter. It is a claim about
ordering: in each case the context term is first-order and the control term is
second-order, and a project team optimizing the second while taking the first
as given is working on the wrong variable.

---

## Scope conditions (shared by all findings)

These bound every number below. They are stated once here rather than repeated.

1. **Region.** Tracks 1 and 6 are PJM-specific in their headline numbers.
   Track 1 reports all nine US balancing areas but the PPL and PJM cuts are
   the ones emphasized. Nothing here establishes behavior in other RTOs.
2. **Synthetic models where stated.** Track 2's feeders and track 3's load
   shapes are parameterized archetypes, not measured circuits or metered
   customers. Their *relative* comparisons hold; their absolute levels do not
   transfer.
3. **Estimated, not measured, marginal emissions.** Track 6's marginal factors
   come from a regression on system-level fuel mix, not from observed dispatch
   response.
4. **Three archetypes are not a population.** Tracks 2 and 3 each rest on a
   small hand-picked set of archetypes. Direction is better supported than
   magnitude. See "Known weaknesses" below.
5. **Point-in-time data.** LBNL Queued Up runs through end of 2024; CarbonCast
   covers 2020-2021; the PJM queue snapshot is a single 2026-05-05 export.

---

## 1. The standard time-to-interconnect statistic understates the wait

**Claim.** Median time-to-interconnect computed over completed projects
understates the true wait by up to **5.2x**, and for recent cohorts the
statistic does not exist at all.

**Mechanism.** Computing a median over projects that reached operation is
conditioned on success. A project that entered in 2015 and is still waiting
contributes nothing. When queues slow, slow projects stay unfinished and leave
the sample, so the measured median gets *faster*. The bias runs opposite to the
trend it is meant to measure.

**Evidence.** Kaplan-Meier with right-censoring, over 36,441 LBNL requests.
The 2005-09 cohort: naive median **2.87 yr**, corrected **15.06 yr**. For the
2015-19 and 2020-24 cohorts the KM median is undefined, because under half of
each cohort will ever complete.

**Falsified if.** A cohort is found where the KM median is both defined and
below the naive median, or where the completion-conditioned sample is shown to
be representative of the full cohort.

**Code.** `interconnection-analytics/iqueue/analysis.py`,
`naive_vs_survival_duration()`.

---

## 2. Withdrawal is the modal outcome everywhere

**Claim.** In PJM, **68.0%** of mature-cohort requests withdraw against
**23.8%** completing. No region in the dataset completes more than 29%.
PPL's own queue (**470 requests**, 49.5 GW) tracks the PJM pattern at
**67.7%** withdrawal and **15.5%** completion, so it is not an outlier.

**Scope.** Mature cohorts only: requests entering within 5 years of the record
end are excluded, because they have not had time to resolve and their inclusion
reads as a throughput collapse that is purely an artifact of elapsed time.

**Code.** `interconnection-analytics/iqueue/analysis.py`, `by_region()`.

---

## 3. The Fast Track 15% screen is far more conservative than the physics

**Claim.** On three synthetic feeder archetypes, the FERC SGIP Fast Track
15%-of-peak-load screen binds between **5.7x** (rural) and **17.1x** (urban)
below the voltage and thermal limit, and the gap *widens* on stiffer feeders.

**Why it matters.** The screen is most conservative exactly where the circuit
can most easily absorb DER. Failing it routes an application from Fast Track
into Supplemental Review; it does not mean the interconnection is infeasible.

**Known weakness.** Three archetypes are not a population, and a sibling audit
repo that sampled a continuous feeder parameter space found the direction held
but the magnitude range was roughly 4x wider than three points suggested. Treat
the direction as supported and the specific multiples as illustrative.

**Falsified if.** A feeder is found where the 15% screen binds at or above the
voltage/thermal limit.

**Code.** `hosting-capacity-sim/hcsim/hosting_capacity.py`, `search()`.

---

## 4. Volt-var control helps only where voltage binds

**Claim.** IEEE 1547-2018 Category B volt-var gives **2.41x** hosting capacity
on the voltage-limited suburban feeder and **0.99x** on the thermally-limited
urban one, where it very slightly *hurts*.

**Mechanism.** Absorbing reactive power to pull voltage down adds current to a
circuit that was already current-limited. Volt-var is not free on a thermally
constrained feeder.

**Known weakness.** The 2.41x figure is one archetype's value, not a typical
one. The conditional structure (voltage-limited gains, thermal-limited does
not) is the robust part of this finding; the multiple is not.

**Code.** `hosting-capacity-sim/hcsim/volt_var.py`.

---

## 5. Siting dominates on weak feeders

**Claim.** Concentrating the same nameplate at the end of the rural feeder
rather than its midpoint costs **3.35x** of hosting capacity. On the urban
feeder the same choice costs only 1.23x.

**Implication.** Locational value of DER is real and scales with feeder
impedance.

**Code.** `hosting-capacity-sim/hcsim/hosting_capacity.py`, `nodal_map()`.

---

## 6. Rate structure swings a solar customer's bill by more than their array size

**Claim.** Holding revenue constant within customer class, the rooftop solar
archetype is the **best** performer under TOU (**-32.6%**) and the **worst**
under a demand charge (**+36.2%**): a **69 percentage point** swing on the same
customer, from two structures both defensible on cost-causation grounds.

**Mechanism.** Solar offsets **83.3%** of annual energy but only 4.9% of peak
demand, because the net peak lands at 20:00 when PV output is zero.

**Secondary.** Load factor predicts demand-charge impact at only **r = -0.59**.
Solar is the outlier precisely because net metering decouples energy from peak,
so the simplest screen for who a demand charge helps fails for exactly the
customers who generate the most controversy. The EV archetype pays **+28.8%**
under a demand charge, the second-worst outcome in the set.

**Design call.** Revenue neutrality is enforced *within* customer class.
Scaling one structure across residential and commercial together produces an
~18% apparent cross-subsidy that is a modeling artifact, since no utility
applies a residential inclining block rate to a 120,000 kWh/yr account.

**Prior art.** The commercial demand-charge result replicates Darghouth et al.,
*Energy Policy* 146:111766 (2020), who report a 7% median demand reduction from
PV against this repo's 6%.

**Code.** `tariff-explorer/texplorer/archetypes.py`,
`revenue_neutral_comparison()`.

---

## 7. The carbon signal a controller reads flips the sign of its result

**Claim.** Scheduling a home battery and EV against PJM's *published average*
carbon intensity scores **-2.9%** on the average yardstick and **+10.5%** on
the marginal one. It helps on average and hurts on marginal on **359 of 364**
days.

**Mechanism.** The two signals are anti-correlated across the day
(**r = -0.66**) and the marginal signal swings **4.1x** harder. Marginal
emissions peak overnight, exactly where cheap TOU prices pull load.

**Resolution.** Optimizing on an estimated marginal signal instead delivers
**-6.7%** marginal emissions while still costing **4.8% less** than no control
at all. There is no cost/carbon tradeoff to negotiate: it is free. The implied
abatement cost from cost-optimal to marginal-optimal is **$713/tonne**.

**Method note.** A naive marginal regression conflates load following with
renewable ramping. Adding a renewable-ramp regressor lifts pooled R2 from
**0.878 to 0.937** and gives the renewable coefficient the expected negative
sign.

**Prior art.** This corroborates rather than discovers. Jiang, Huber, Ferris &
Roald (arXiv:2504.07248, ACM e-Energy 2025) and ACM e-Energy 2024
(DOI 10.1145/3632775.3661953) both showed average-signal load shifting can be
counterproductive; Electricity Maps (2024) reports the symmetric result.

**Falsified if.** The marginal estimate is shown to be an artifact of the
regression rather than of dispatch, or a direct measurement of PJM marginal
units contradicts the overnight peak.

**Code.** `carbon-aware-der/cader/marginal.py`,
`carbon-aware-der/cader/signal_choice.py`.

---

## Retracted

**An earlier version of this repository claimed that using average rather than
marginal carbon intensity was "conservative" and that track 6's conclusion was
"robust" to the choice.** That was wrong. The two signals are anti-correlated
in PJM, so the average signal does not understate the achievable saving, it
points the controller in the wrong direction. The claim was corrected in place
rather than quietly deleted, and finding 7 above is the replacement. This block
is the only place in the repository where a superseded claim is stated, and the
claim guard permits scope-reversing language here and nowhere else.

---

## What would change my mind

- Track 1: evidence that projects with recorded terminal dates (62.8% of rows)
  differ systematically from those without.
- Track 2: a sampled feeder population, rather than three archetypes, showing
  the screen binding above the physical limit.
- Track 3: real metered load shapes replacing the synthetic archetypes, and a
  filed tariff replacing the representative rate levels.
- Track 6: measured marginal dispatch response for PJM, or interchange-adjusted
  generation data, replacing the system-level regression.
