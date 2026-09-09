# Price-only C54 retracement comparison

New FIB/SHIFTED hypotheses without AVWAP, not the old blocked T1/F1/F0. USED_DEV, equal-notional trade-bps including open marks, no independent/G5/live claim.

|Period|Rule|Closed/open|WR%|Payoff|PF|Terminal net|Cost2|Daily DD|Delta vs C54|
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
|DEV2025|C54|191/0|43.46|1.85|1.42|13666.60|9445.52|10452.80|0.00|
|DEV2025|FIB|16/0|56.25|2.53|3.26|4673.11|4302.02|982.89|-8993.49|
|DEV2025|SHIFTED|13/0|53.85|2.19|2.55|2803.07|2515.56|982.89|-10863.53|
|SEEN2026|C54|69/2|37.68|2.78|1.68|7198.71|5634.99|3997.48|0.00|
|SEEN2026|FIB|6/0|16.67|19.21|3.84|1767.48|1629.05|668.05|-5431.23|
|SEEN2026|SHIFTED|4/0|25.00|16.01|5.34|1941.64|1848.90|447.67|-5257.07|

{"FIB": "REJECT_KEEP_C54", "SHIFTED": "REJECT_KEEP_C54"}

No parameter calibration/automatic next candidate. Old AVWAP source block persists; no volume used by these two variants. M1 diagnostics regroup unchanged original net amounts, never hypothetical recovery profits.
