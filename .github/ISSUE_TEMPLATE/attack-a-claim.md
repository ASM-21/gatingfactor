---
name: Attack a claim
about: Challenge a number in FINDINGS.md
title: "[claim] "
labels: claim-challenge
---

**Which claim** (finding number from FINDINGS.md, or the README line):

**Why you think it is wrong or unsupported:**

**What you ran, if anything:**

---

Three claims in this repo have no independent corroboration and are the most
likely to be wrong. If you are looking for somewhere to start:

1. The 2.64x volt-var uplift (`hosting-capacity-sim`) is one archetype's value
   at one inverter sizing. An earlier version of it was already wrong once.
2. The r = -0.59 load factor correlation (`tariff-explorer`) rests on five
   hand-picked archetypes.
3. The 1.55x to 2.06x real-time truncation (`interconnection-analytics`) rests
   on three backtested cohorts and on the dated half of completions. An earlier
   version of this claim was also wrong once.

See CONTRIBUTING.md for finish lines on each.
