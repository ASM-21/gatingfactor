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

**Outcome must come from status, not dates.** Only 48.3% of withdrawn projects
carry a withdrawal date, and only about half of operational projects carry a
commercial operation date. Classifying outcomes from date presence would move
roughly half of all withdrawn projects into a "still waiting" bucket and
understate the withdrawal rate about twofold. Status is complete; dates are
not. Rates therefore use every row, and timing statistics state the dated
subset they rest on. (An earlier version of this README said 27.8% of withdrawn
projects carry a date. That figure is the share of *all* rows with a withdrawal
date, not of withdrawn ones; the conclusion it supported was unaffected.)

A third, smaller quirk: 17 rows carry negative capacity. Those are capacity
*decrease* requests, a real queue product, and they are flagged rather than
dropped so they cannot net silently into a total.

## The headline finding

**There is no median wait for a project entering the queue, and the median
people quote instead describes the minority that finished.**

Median time-to-interconnect is normally computed over projects that reached
operation. That statistic is conditioned on success. It is a fair description
of the completers, but a developer entering the queue wants to know how long
*their* project will wait, and in this dataset most projects never finish.

| Cohort | Projects | Reached operation | Withdrew | Still open | Median of completers |
|---|---|---|---|---|---|
| 1995-99 | 258 | 34.1% | 61.6% | 4.3% | 3.75 yr |
| 2000-04 | 1,720 | 27.2% | 71.2% | 1.7% | 2.31 yr |
| 2005-09 | 4,422 | 21.6% | 76.6% | 1.8% | 2.87 yr |
| 2010-14 | 4,441 | 22.2% | 75.8% | 2.0% | 3.44 yr |
| 2015-19 | 8,927 | 13.8% | 67.3% | 18.9% | 3.87 yr |
| 2020-24 | 15,862 | 1.6% | 41.5% | 56.9% | 2.56 yr |

No cohort entering from 1995 through 2019 has had more than 34.1% of its
requests reach operation, and none can reach half: if every project from those
cohorts still waiting were to complete, the highest any of them could finish at
is 38.4%. When more than half of a cohort never completes, the median time to
completion for an entrant does not exist. The completed-only median still
returns a comfortable-looking number, which is the problem. These shares come
from status alone, which covers every row, so they rest on no assumption about
missing dates.

**Read before a cohort resolves, the completed-only median is also truncated.**
A recent cohort has only had time to produce its fast completions; its slow ones
are still in the queue. The size of that effect is measured directly by
re-reading three fully resolved cohorts at earlier record end dates:

| Cohort | Read at close of entry window | +1 yr | +5 yr | Fully resolved |
|---|---|---|---|---|
| 2000-04 | 1.49 yr | 1.48 yr | 2.07 yr | 2.31 yr |
| 2005-09 | 1.39 yr | 1.66 yr | 2.59 yr | 2.87 yr |
| 2010-14 | 1.81 yr | 1.95 yr | 3.24 yr | 3.44 yr |

Read at the close of the entry window, the completed-only median ran
**1.55x to 2.06x** below its eventual value. The 2020-24 cohort, read at the end
of 2024, sits exactly there, and its 2.56 yr reads as a speed-up from the
2015-19 cohort's 3.87 yr. That is the direction truncation pushes. A slowing
queue measured this way can look like it is getting faster.

**Prior art.** Berkeley Lab's own *Queued Up* report (2025 edition) presents
durations computed over projects that reached each milestone, indexed mostly by
the year projects came online, and does not use survival or competing-risks
methods. Indexing by completion year avoids the truncation shown above but is
still a statistic about completers. Nothing here suggests the report's figures
are wrong; they answer a narrower question than the one usually asked of them.

> **Retracted.** An earlier version of this README reported a "Kaplan-Meier
> median" of 15.06 yr for the 2005-09 cohort and called the 2.87 yr completed-only
> median a 5.2x understatement. That fit treated withdrawn projects as censored,
> which estimates time to completion in a hypothetical queue where nobody
> withdraws. Withdrawal is a competing risk, not censoring, so the 15.06 yr
> figure described no real project. The corrected finding above replaces it. See
> FINDINGS.md.

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
  A 2022 cohort has had about two years to resolve and a 2010 cohort fourteen.
- **Maturity filter.** Cohorts within 5 years of the record end are excluded
  from rate statistics. Without it, recent years show an apparent collapse in
  throughput that is entirely an artifact of insufficient elapsed time.
- **Withdrawal is a competing risk, not censoring.** A withdrawn project can
  never complete. Cumulative incidence is computed as P(outcome) from status
  times P(time by t | outcome) from the dated subset of that outcome, assuming
  dates are missing at random within an outcome. Applying Kaplan-Meier to
  completion while censoring withdrawals would estimate a queue with no
  withdrawals; that is the error retracted above.

## Figures

- `outputs/interconnection-analytics/cohort_outcomes.png` lifetime outcome shares, no cohort reaches half
- `outputs/interconnection-analytics/realtime_backtest.png` the completed-only median read before resolution
- `outputs/interconnection-analytics/completion_trend.png` outcome shares by entry year
- `outputs/interconnection-analytics/completion_by_resource.png` completion by resource
- `outputs/interconnection-analytics/pjm_cumulative_incidence.png` PJM competing risks
- `outputs/interconnection-analytics/queue_growth.png` request and capacity volume

## Limitations

1. Timing statistics rest on dated projects: about half of completions and of
   withdrawals. The real-time backtest and the medians assume dates are missing
   at random among completers. If projects with recorded dates are
   systematically better-administered, durations here are optimistic. The
   headline shares (34.1%, 38.4%) need no dates and do not depend on this.
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
    analysis.py   outcome resolution, cohort outcomes, competing-risks
                  incidence, real-time backtest
  run_analysis.py tables and figures
```
