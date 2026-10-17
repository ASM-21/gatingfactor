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

1. The 2.41x volt-var uplift (`hosting-capacity-sim`) is one archetype's value
   reported as if typical.
2. The r = -0.59 load factor correlation (`tariff-explorer`) rests on five
   hand-picked archetypes.
3. The 5.2x survivorship ratio (`interconnection-analytics`) rests on the 62.8%
   of rows that carry a usable terminal date.

See CONTRIBUTING.md for finish lines on each.
