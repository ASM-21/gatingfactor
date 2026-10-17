# pjm-market-tools (not yet built)

LMP congestion analysis for the PPL zone, plus a capacity auction (RPM)
clearing price forecast framed as a prediction market question.

**Blocked on network egress.** `dataminer2.pjm.com` was unreachable.

## To build it

- Real-time and day-ahead LMP with energy / congestion / loss decomposition
- Historical RPM base residual auction clearing prices
- Fundamentals: reserve margin, load forecast, announced retirements

Note for the forecasting module: report a probability-weighted range with
stated assumptions and confidence bands, not a point estimate. RPM clearing
prices are famously regime-dependent (rule changes have repeatedly broken
historical relationships), so a regression on price history alone will be
overconfident. Say so in the README rather than burying it.

`data/raw/pjm/` already holds hourly PJM generation-by-fuel for 2019 to 2021
from the CarbonCast pull, which is a usable fundamentals input.
