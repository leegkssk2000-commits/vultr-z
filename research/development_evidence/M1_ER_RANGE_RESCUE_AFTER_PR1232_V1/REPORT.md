# M1 ER or prior squeeze-range escape — USED_DEV comparison

Original M1 is direct parent; rejected C62 is diagnostic only. Fixed notional trade-bps, original open marks, not account returns or independent/G5 evidence.

|Period|Rule|Closed/open|WR%|Mean win|Mean loss|Payoff|PF|Terminal net|Cost2|Daily DD|
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|DEV2025|M1|104/4|37.50|760.12|-388.32|1.96|1.17|4130.89|1665.88|8585.34|
|DEV2025|C62|91/4|38.46|771.75|-409.51|1.88|1.18|3805.54|1622.09|7236.25|
|DEV2025|C63|98/4|37.76|784.35|-395.24|1.98|1.20|4638.62|2301.59|7864.04|
|SEEN2026|M1|28/5|46.43|1362.29|-273.63|4.98|4.31|11492.23|10705.03|3642.33|
|SEEN2026|C62|24/5|50.00|1473.26|-273.53|5.39|5.39|12283.75|11581.93|3642.33|
|SEEN2026|C63|24/5|50.00|1473.26|-273.53|5.39|5.39|12283.75|11581.93|3642.33|

PARTIAL_IMPROVEMENT

All retained C62 eligibility is preserved, but added actual occupancy can displace later trades: inspect full attribution rather than assuming monotone trade sets. No year/symbol exceptions, buffer search, exit/sizing change or automatic next candidate.
