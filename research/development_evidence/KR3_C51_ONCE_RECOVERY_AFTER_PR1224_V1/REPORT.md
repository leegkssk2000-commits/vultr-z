# Candidate51 one-close recovery child — measured result

REJECT_NO_CUMULATIVE_ADOPTION

Same fixed nominal trade-bps. Both periods USED_DEV; opens marked with original costs. No account returns or G5 PASS.
C51 is the direct parent, KR3 the original cumulative control. No prior strategy was rerun.

|Period|Rule|Closed/open|WR %|Mean win|Mean loss|Payoff|PF|Terminal net|Cost2|Daily marked DD|
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|DEV2025|KR3|202/1|41.09|581.35|-318.58|1.825|1.273|10265.00|5744.23|11727.79|
|DEV2025|C51|202/1|42.57|556.13|-300.43|1.851|1.372|12900.53|8420.93|11267.44|
|DEV2025|C52|202/1|44.06|539.47|-314.95|1.713|1.349|12346.59|7863.95|11143.80|
|SEEN2026|KR3|75/4|33.33|717.76|-251.61|2.853|1.426|4746.58|3002.13|4093.69|
|SEEN2026|C51|75/4|36.00|662.26|-254.66|2.601|1.463|5040.20|3300.67|3997.48|
|SEEN2026|C52|75/4|36.00|662.26|-257.46|2.572|1.447|4905.97|3164.40|4093.69|

One nonpositive-mark breach may wait exactly one completed close; all original exits retain priority. This can enlarge losses. No assured recovery, stop price or positive fill.
Loss/winner, new/removed and open-state bridge: per-period ACCOUNTING_C51.json and ACCOUNTING_KR3.json.
Candidate51 stays preserved; no operational adoption follows this report. Counts52/84 include actual attempts; prior51/82 and all failures remain unchanged.
CI/merge closure is separate. Completed scope must become verify-only; no retry or automatic successor.
