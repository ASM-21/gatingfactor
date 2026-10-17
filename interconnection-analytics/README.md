# interconnection-analytics

Interconnection queue outcomes from Berkeley Lab's *Queued Up* dataset:
36,441 requests across nine US balancing areas, 1970 through 2024.

```bash
pip install -r ../requirements.txt
python run_analysis.py
```

## Data provenance

| Source | Status | Notes |
|---|---|---|
| LBNL Queued Up 2025 release | **Real** | 36,441 project-level requests through end of 2024 |
| PJM queue snapshot 2026-05-05 | **Real** | 9,251 rows with study-milestone columns LBNL lacks |

Berkeley Lab publishes Queued Up at `emp.lbl.gov/queues`. That host was not
reachable from the build environment, so the workbook was obtained from a
GitHub mirror. The file is Berkeley Lab's own published dataset; the mirroring
repository carries no license and none of its code was used here. The analysis
in this module is written independently from the raw workbook.

## Two ingest traps

Both of these silently corrupt results rather than raising an error, so both
have tests pinning them.

**Excel serial dates.** Every date column arrives as a float day-count from
1899-12-30, not a datetime. Read naively they come through as `float64` and
every duration calculation yields `NaN`, which looks like missing data rather
than a parsing bug.

**Outcome must come from status, not dates.** Only 27.8% of withdrawn projects
carry a withdrawal date and only 8.1% of the dataset has a commercial operation
date. Classifying outcomes from date presence would move roughly half of all
withdrawn projects into a "still waiting" bucket and understate the withdrawal
rate about twofold. Status is complete; dates are not. Rates therefore use
every row, and timing statistics use the 62.8% subset where a terminal date
exists.

A third, smaller quirk: 17 rows carry negative capacity. Those are capacity
*decrease* requests, a real queue product, and they are flagged rather than
dropped so they cannot net silently into a total.

## The headline finding

**The usual time-to-interconnect statistic understates the wait by up to 5x,
and for recent cohorts the statistic does not exist at all.**

Median time-to-interconnect is normally computed over projects that reached
operation. That statistic is conditioned on success. A project that entered in 2015 and is
still waiting contributes nothing, so when queues slow down, slow projects stay
unfinished and leave the sample, and the measured median gets *faster*. The
bias runs opposite to the trend it is meant to measure.

Correcting with Kaplan-Meier, which lets every project contribute the time it
was actually observed and right-censors the unresolved ones:

| Cohort | Projects | Naive median | Kaplan-Meier median | Completion rate |
|---|---|---|---|---|
| 1995-99 | 258 | 3.75 yr | 5.00 yr | 34.1% |
| 2000-04 | 1,720 | 2.31 yr | 5.62 yr | 27.2% |
| 2005-09 | 4,422 | 2.87 yr | **15.06 yr** | 21.6% |
| 2010-14 | 4,441 | 3.44 yr | 7.01 yr | 22.2% |
| 2015-19 | 8,927 | 3.87 yr | **undefined** | 13.8% |
| 2020-24 | 15,862 | 2.56 yr | **undefined** | 1.6% |

For the 2005-09 cohort the quoted figure is 2.87 years and the correct one is
15.06, a **5.2x understatement**. For 2015 onward the Kaplan-Meier median is
undefined because fewer than half of those cohorts will ever complete: there is
no median wait when the modal outcome is never finishing. The naive statistic
still returns a comfortable-looking number, which is precisely the problem.

## Other findings

**Withdrawal is the modal outcome everywhere.** Across mature cohorts, 68% of
PJM requests withdraw against 24% completing. No region completes more than 29%.

| Region | Projects | Completion | Withdrawal |
|---|---|---|---|
| ISO-NE | 692 | 28.8% | 63.2% |
| ERCOT | 1,252 | 28.0% | 56.4% |
| PJM | 4,893 | 23.8% | 68.0% |
| MISO | 2,528 | 19.4% | 68.6% |
| CAISO | 1,758 | 12.7% | 78.4% |

**Completion rate by resource splits along dispatchability.** Nuclear completes
at 59.1% and gas at 31.0%, while solar completes at 14.1%, storage at 8.7%, and
offshore wind at 3.0%. Some of that is real project risk and some is that newer
technologies are concentrated in recent cohorts, which the maturity filter
mitigates but cannot fully remove.

**PPL specifically:** 470 requests, 49.5 GW, 15.5% completion, 67.7%
withdrawal. Close to the PJM-wide pattern, so PPL's queue is not an outlier in
either direction.

## Method notes

- **Cohort framing throughout.** Outcomes are never pooled across entry years.
  A 2022 cohort has had three years to resolve and a 2010 cohort fifteen.
- **Maturity filter.** Cohorts within 5 years of the record end are excluded
  from rate statistics. Without it, recent years show an apparent collapse in
  throughput that is entirely an artifact of insufficient elapsed time.
- **Competing risks.** Withdrawal and completion are not independent censoring
  events; a withdrawn project can never complete. Cumulative incidence is
  computed against the shared at-risk pool rather than applying Kaplan-Meier to
  one outcome while censoring the other, which would overstate completion.

## Figures

- `outputs/interconnection-analytics/survivorship_bias.png` naive vs corrected median
- `outputs/interconnection-analytics/completion_trend.png` outcome shares by entry year
- `outputs/interconnection-analytics/completion_by_resource.png` completion by resource
- `outputs/interconnection-analytics/pjm_cumulative_incidence.png` PJM competing risks
- `outputs/interconnection-analytics/queue_growth.png` request and capacity volume

## Limitations

1. Timing statistics rest on the 62.8% of rows with a usable terminal date.
   Whether that subset is representative is not established; if projects with
   recorded dates are systematically better-administered, durations here are
   optimistic.
2. LBNL harmonizes heterogeneous RTO queue postings, so cross-region
   comparisons carry the residual of that harmonization.
3. No study-cost data. The original plan called for cost-per-MW trends; those
   columns are not in the public release.
4. The PJM snapshot is a single point in time, so it supports a current-state
   cut but not a time series.
5. Resource-type completion rates are confounded with cohort age even after
   the maturity filter, since solar and storage barely existed in early cohorts.

## Layout

```
interconnection-analytics/
  iqueue/
    ingest.py     LBNL and PJM loaders, canonical schema, coverage report
    analysis.py   outcome resolution, Kaplan-Meier, competing risks, cohorts
  run_analysis.py tables and figures
```
