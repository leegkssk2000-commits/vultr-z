# C63 / R / R_B20 — first two FULL results

Two disjoint USED_DEV windows; fixed notional trade-bps, modeled costs and hypothetical unfinished marks. No continuous account/compound return or independent/G5 claim.

|Window|Rule|Closed/open|WR %|Mean win|Mean loss|Payoff|PF|Terminal net|Full cost2|Daily marked DD|
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|DISJOINT SUM|C63|122/9|40.16|953.06|-375.23|2.54|1.70|16922.37|13883.52|—|
|DISJOINT SUM|R|122/9|39.34|926.93|-371.65|2.49|1.62|14604.76|11390.72|—|
|DISJOINT SUM|R_B20|122/9|40.16|942.78|-375.23|2.51|1.69|16418.37|13285.99|—|
|DEV2025|C63|98/4|37.76|784.35|-395.24|1.98|1.20|4638.62|2301.59|7864.04|
|DEV2025|R|98/4|36.73|725.83|-390.64|1.86|1.08|1637.59|-830.02|8604.54|
|DEV2025|R_B20|98/4|37.76|756.42|-395.24|1.91|1.16|3605.24|1200.09|8125.35|
|SEEN2026|C63|24/5|50.00|1473.26|-273.53|5.39|5.39|12283.75|11581.93|3642.33|
|SEEN2026|R|24/5|50.00|1530.21|-273.53|5.59|5.59|12967.16|12220.73|4014.34|
|SEEN2026|R_B20|24/5|50.00|1517.37|-273.53|5.55|5.55|12813.13|12085.90|4360.18|

REJECT_KEEP_C63

## Per-window attribution and vulnerability

### DEV2025
C63 checks: {"WR_up": false, "net_up": false, "cost2_up": false, "DD_down": false}
- Versus C63: four-way delta {"closed_open_transitions": 0, "common_CC_OO": -1033.382481893807, "costs_already_in_net": true, "new": 0, "parity": "PASS", "removed": 0}
- Winner retention ordinary/top-decile: 0.88/0.96; largest positive origin share 0.47
- Versus R: four-way delta {"closed_open_transitions": 0, "common_CC_OO": 1967.6434526391345, "costs_already_in_net": true, "new": 0, "parity": "PASS", "removed": 0}
- Winner retention ordinary/top-decile: 0.98/0.85; largest positive origin share 0.16
- Closed loss streak 7; worst trade -1359.31bps; worst loss-decile mean -979.44bps.
- Exposure: {"calendar_days_by_simultaneous_symbols": {"0": 253.0, "1": 61.666666666666664, "2": 27.333333333333332, "3": 13.833333333333334, "4": 13.666666666666666, "5": 5.5}, "calendar_days_with_any_exposure": 122.0, "max_simultaneous_positions": 5, "max_simultaneous_symbols": 5, "maximum_holding_days_including_open": 6.666666666666667, "position_days": 240.0, "semantics": "ENTRY_INCLUSIVE_EXIT_OR_MARK_EXCLUSIVE; EQUAL_NOTIONAL_SLOTS; NOT_ACCOUNT_EXPOSURE", "symbol_days_union": 240.0}
### SEEN2026
C63 checks: {"WR_up": false, "net_up": true, "cost2_up": true, "DD_down": false}
- Versus C63: four-way delta {"closed_open_transitions": 0, "common_CC_OO": 529.3803901206156, "costs_already_in_net": true, "new": 0, "parity": "PASS", "removed": 0}
- Winner retention ordinary/top-decile: 0.91/0.97; largest positive origin share 0.41
- Versus R: four-way delta {"closed_open_transitions": 0, "common_CC_OO": -154.0346145817348, "costs_already_in_net": true, "new": 0, "parity": "PASS", "removed": 0}
- Winner retention ordinary/top-decile: 0.97/1.00; largest positive origin share 0.70
- Closed loss streak 5; worst trade -856.09bps; worst loss-decile mean -617.57bps.
- Exposure: {"calendar_days_by_simultaneous_symbols": {"0": 85.83333333333333, "1": 17.166666666666668, "2": 7.666666666666667, "3": 2.3333333333333335, "4": 0.6666666666666666, "5": 3.8333333333333335, "6": 2.5}, "calendar_days_with_any_exposure": 34.166666666666664, "max_simultaneous_positions": 6, "max_simultaneous_symbols": 6, "maximum_holding_days_including_open": 6.666666666666667, "position_days": 76.33333333333333, "semantics": "ENTRY_INCLUSIVE_EXIT_OR_MARK_EXCLUSIVE; EQUAL_NOTIONAL_SLOTS; NOT_ACCOUNT_EXPOSURE", "symbol_days_union": 76.33333333333333}

Full gross/cost/net/cost2 and CC/CO/OC/OO/new/removed bridges, reduced/worsened losses, damaged wins, loss groups and concentration are retained in ACCOUNTING_C63.json, ACCOUNTING_R.json and SUMMARY.json.
C63 and R are saved results only. The same raw signal pool does not imply the same FULL entry set. R_B20 is an internal ZEL repair, not a new external trader reproduction. Existing M1/C54/C63/C69/C70_LOCAL(reg71)/C72/G73/R74/GR75 history and public-tip limitations remain preserved.
No deployment. Rollback must preserve all rules, attempts, results, raw/cost/metric evidence and budgets. This scope closes REPORT_ONLY with no automatic successor.
