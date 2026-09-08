# D1 sixth-close progress requalification — actual reused DEV

origin_half AND (delayed_half OR (close6 > origin_high AND close6 > ema20_6 > ema50_6)); next open; exact D reference and exit anchors

One new candidate46, two actual FULL evaluations65/66. KR3 and D results reused, not rerun.
All figures are equal fixed-notional trade-bps; no account-return claim. Both periods are USED_DEV and all inherited research cost-proxy limitations apply.

|Period|Rule|Closed/open|Win%|Payoff|PF|Terminal net|All-cost2|Marked DD|
|---|---|---:|---:|---:|---:|---:|---:|---:|
|DEV2025|KR3|202/1|41.09|1.825|1.273|10265.00|5744.23|11727.79|
|DEV2025|D|108/0|45.37|2.326|1.932|16354.20|13904.99|5227.94|
|DEV2025|D1|141/0|40.43|1.900|1.289|8559.14|5395.12|9883.68|
|SEEN2026|KR3|75/4|33.33|2.853|1.426|4746.58|3002.13|4093.69|
|SEEN2026|D|34/2|26.47|1.854|0.667|-2333.54|-3111.36|3044.35|
|SEEN2026|D1|51/2|25.49|1.748|0.598|-4544.43|-5714.82|5121.91|

## Prespecified development checks
{
  "DEV2025": {
    "positive_terminal_net": true,
    "positive_all_cost2": true,
    "net_not_worse_D": false,
    "cost2_not_worse_D": false,
    "DD_not_worse_D": false
  },
  "SEEN2026": {
    "positive_terminal_net": false,
    "positive_all_cost2": false,
    "net_not_worse_D": false,
    "cost2_not_worse_D": false,
    "DD_not_worse_D": false
  }
}

G5A HOLD and formal credit0 remain. Code/CI completion is not economic pass. No parameter retry, no new source/OOS/provider calls/orders.
Full original-signal attribution, lost/restored winners, reopened losses, exposure and symbol concentration: ACCOUNTING.json.
The prior missing HYPE/SOL winners were discovery diagnostics only; no per-symbol or historical outcome rules were used. Remote completion/merge is recorded separately.
