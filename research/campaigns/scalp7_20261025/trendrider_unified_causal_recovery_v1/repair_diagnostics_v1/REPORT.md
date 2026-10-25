# Unified TrendRider one-axis repair after S4 failure: economic feasibility filter

2026-10-25. Historical USED-DEV replay only, zero orders and zero newly downloaded source. Inputs are the exact immutable saved Liquid6+Delayed signal union from the parent research.

## Actual root-cause decomposition

S4 original 121 accepted / Net2 +1752.48 summed modeled trade-bps / PF2 1.294 / DD2 2225.86 trade-bps / max streak14. Long legs 121 total +1083.58, reversal SHORT legs 71 total +668.90 with only32 profitable, 39 losing; large loss reversal under previously described S4 13 initially >=1R losing opportunities now net-positive, 8 reach net +1R, but many losses persist.

Stress: +20 new instrument bp per ALL legs => Net2 +472.48, +40 bp => -807.52; one-hour SHORT arrival delay => +236.84; re-run without 1000PEPE => -752.27; omit short => -176.83; omit early bearish bail => -695.93. This is structural sensitivity, not solved by increasing position risk. Trading cost/quote and historical signed short funding unavailable.

## ONE new frozen source-only rule, no grid

Candidate has entry-time original sealed stop-price R instrument bps >= 2 x previously published original modeled instrument roundtrip cost; otherwise exclude. This is a native economic admissibility prior, independent of *realized* profit labels, not a hindsight winner/date filter. The exact rule was written to MECHANISM_FIX_FREEZE.json BEFORE the only outcome evaluation.

| Economic | Original S4 | Feasibility filter |
|---|---:|---:|
| Completed opportunities | 121 | 118 |
| Net2 summed trade-bps | +1752.48 | +1107.46 |
| PF2 | 1.294 | 1.183 |
| Realized DD2 | 2225.86 | 2623.50 |
| Max consecutive losses | 14 | 14 |
| October Net2 | +99.92 | -545.10 |

Original source candidates filtered=4; 1 previously accepted winning opportunity was lost. Leave-one-1000PEPE-out filter economics -688.62 bps / PF0.892. **REJECT this exact source cost-vs-stop filter:** economic Net2/PF/DD/regime degradation and no streak improvement. Do not threshold-sweep on this consumed source.

## Separation of further work and authority

C owns original strategy merge / shadow contract but MUST NOT retune used dataset. B can read-only source quality, actual timestamp, signed side-specific funding and intrabar native quote/5m or1m witness ownership WITHOUT new ingestion or orders. A remains sole global-heavy official economic owner and no new FULL. A distinct source audit may validate original fill/stop/gap and side-cost fields without touching strategy rule. All work must originate with existing A/B/C owner, no new top-level project.

The current code simulates admissions only from the original two saved completed signal lists; it does NOT rebuild unobserved strategy entry events after a position ends sooner. The S4 return comparison could be selection-effect driven because accepted trade membership changes when exit time/cooldown changes. One verified independent chronological replay with real prospective as-of and all eligible signals, completed long/short slippage/funding and fixed same-symbol ownership is required before promoting any rescue result. H4 placebo / H5 concentration and truly untouched OOS remain pending.
