# Exact PR1213 D: reused 2026 expansion

Exactly one new FULL: D-SEEN2026. D-DEV2025 and both KR3 periods are saved results, not rerun.
Equal-notional trade-bps, not account returns. Both periods are reused DEV; no independent OOS or G5A PASS.
Original D admission, sixth observed-bar recheck, shifted reference/exit anchors and no initial SL/fixed TP are unchanged.

|Period|Rule|Closed/open|Win %|Payoff|PF|Terminal net|All-cost2|Marked DD|
|---|---|---:|---:|---:|---:|---:|---:|---:|
|DEV2025|KR3|202/1|41.09|1.825|1.273|10265.00|5744.23|11727.79|
|DEV2025|D|108/0|45.37|2.326|1.932|16354.20|13904.99|5227.94|
|SEEN2026|KR3|75/4|33.33|2.853|1.426|4746.58|3002.13|4093.69|
|SEEN2026|D|34/2|26.47|1.854|0.667|-2333.54|-3111.36|3044.35|

Full origin-state/winner/open/concentration/same-calendar reconciliation is in ACCOUNTING.json. No costs are added twice.
Candidate hypotheses45 preserved; actual evaluations63→64. Selecting an already tested D as development parent does not rewrite the PR1213 diagnostic record.
New market requests0, unused OOS reads0, paid provider calls0, orders0. Formal G5A/G5B states unchanged.
Remote CI/merge closure is recorded separately; this measured report does not claim those are already complete.
