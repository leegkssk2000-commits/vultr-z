# KR3 profit-zone preservation — two USED_DEV periods

Original KR3 signal, entry, EMA4*n, reference clock and exits retained. Arm on held completed close>EMA20>EMA50 and EMA20>entry*(1+decision-time research roundtrip fee/spread/impact/elapsed absolute funding/floor /10000). No arming-bar exit. Track running max of completed EMA20 after arming. Later close below the line known through the previous bar queues next open. Original timeout, EMA, allowed-low and runner exits retain priority. Next-open gaps are actual path prices; outside-window intents stay pending.

**Verdict: DEVELOPMENT_GOAL_MET**. User joint development goal requires WR/net/cost2 strictly higher AND daily marked DD strictly lower in each period.
Equal notional trade-bps including hypothetical open marks, not account returns. Both periods USED_DEV; no independent or formal credit.
Single candidate51, two FULL evaluations81/82. KR3/D/D2/candidate50 are stored comparators only; no parent/FIXED economic replay.

|Period|Rule|Closed/open|WR%|Avg win|Avg loss|Payoff|PF|Terminal net|All-cost2|Daily marked DD|
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|DEV2025|KR3|202/1|41.09|581.35|-318.58|1.825|1.273|10265.00|5744.23|11727.79|
|DEV2025|PROFIT_ZONE|202/1|42.57|556.13|-300.43|1.851|1.372|12900.53|8420.93|11267.44|
|DEV2025|D|108/0|45.37|691.81|-297.36|2.326|1.932|16354.20|13904.99|5227.94|
|DEV2025|D2|108/0|45.37|691.81|-281.64|2.456|2.040|17281.86|14841.86|4566.41|
|DEV2025|CANDIDATE50|202/1|38.12|605.46|-310.83|1.948|1.200|7690.49|3190.08|12547.56|
|SEEN2026|KR3|75/4|33.33|717.76|-251.61|2.853|1.426|4746.58|3002.13|4093.69|
|SEEN2026|PROFIT_ZONE|75/4|36.00|662.26|-254.66|2.601|1.463|5040.20|3300.67|3997.48|
|SEEN2026|D|34/2|26.47|535.65|-288.95|1.854|0.667|-2333.54|-3111.36|3044.35|
|SEEN2026|D2|34/2|26.47|535.65|-280.21|1.912|0.688|-2115.15|-2883.77|2911.34|
|SEEN2026|CANDIDATE50|75/4|32.00|724.84|-244.29|2.967|1.396|4320.50|2591.46|4721.79|

Prespecified strict checks: {"DEV2025": {"WR_up": true, "cost2_up": true, "daily_DD_down": true, "terminal_net_up": true}, "SEEN2026": {"WR_up": true, "cost2_up": true, "daily_DD_down": true, "terminal_net_up": true}}

Full common/new/removed/closed-open attribution, loss-to-win/win-to-loss, ordinary and large winner damage, loss streaks, exposure and symbol/event concentration are in SUMMARY.json and period ACCOUNTING.json.
Original entry rules and signal/reference pool are preserved; identical FULL admission sets are not assumed. Changed occupancy is included in attribution.
Research activation cost uses fee/spread/impact plus funding elapsed at decision close and a20bps floor. Final trade funding is never supplied as an earlier decision feature. Cost estimates are historical DEV proxies, not actual fills or live fee/funding evidence.
Protection triggers at completed close against the prior line; exit is next open, including adverse gaps. A protected line is not a guaranteed execution price. No next open inside the window means pending/censored.
Daily DD is based on the frozen daily marked aggregate; no intrabar liquidation or worst intrabar account-DD claim. Open marks are hypothetical and excluded from win rate/PF and winner labels.
No G5 or operating SSOT change, live promotion, new collection, OOS or paid AI. No parameter retry or auto follow-up trial.
This result report precedes final review/CI/merge closure; closing checks read saved outputs and synthetic tests only.