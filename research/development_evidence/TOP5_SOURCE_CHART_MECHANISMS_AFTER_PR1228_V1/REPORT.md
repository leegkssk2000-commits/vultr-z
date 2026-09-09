# Source chart mechanisms — actual USED_DEV results

Equal fixed research notional; trade-bps sums. Open marks include hypothetical modeled liquidation costs; they are not actual exits. Marked DD is a same-calendar sum of fixed-notional trade marks, not an account return. The two windows are not a continuous account curve.

|Period|Lane|Closed/open|WR %|Avg win|Avg loss|Payoff|PF|Closed net|Open mark|Total net|Cost ×2|Marked DD|
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|DEV2025|C54|191/0|43.46|557.01|-301.53|1.85|1.42|13666.60|0.00|13666.60|9445.52|10452.80|
|DEV2025|T1|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|
|DEV2025|M1|104/4|37.50|760.12|-388.32|1.96|1.17|4403.80|-272.90|4130.89|1665.88|8585.34|
|DEV2025|R1|22/0|54.55|382.35|-463.16|0.83|0.99|-43.44|0.00|-43.44|-529.20|3479.20|
|DEV2025|F1|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|
|DEV2025|F0|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|
|SEEN2026|C54|69/2|37.68|684.66|-246.02|2.78|1.68|7222.38|-23.67|7198.71|5634.99|3997.48|
|SEEN2026|T1|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|
|SEEN2026|M1|28/5|46.43|1362.29|-273.63|4.98|4.31|13605.24|-2113.01|11492.23|10705.03|3642.33|
|SEEN2026|R1|3/0|100.00|219.32|NA|NA|NA|657.96|0.00|657.96|595.12|131.67|
|SEEN2026|F1|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|
|SEEN2026|F0|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|NOT_RUN|

## Frozen goal and two-window interpretation

{"F0": "BLOCKED_OR_NOT_RUN", "F1": "BLOCKED_OR_NOT_RUN", "M1": "REJECT_NO_ECONOMIC_IMPROVEMENT", "R1": "REJECT_NO_ECONOMIC_IMPROVEMENT", "T1": "BLOCKED_OR_NOT_RUN"}

The eight existing conditions are WR up, terminal net up, cost ×2 up and marked DD down in each window. Equality does not pass. M1/R1 are standalone signal pools and their results cannot be added to C54 as an improvement. T1/F1/F0 full common/new/removed/closed-open accounting is preserved per cell.

|Lane|Combined closed wins/trades|Weighted WR %|
|---|---:|---:|
|C54|109/260|41.92|
|M1|52/132|39.39|
|R1|15/25|60.00|

## Risk, attribution and selection limits

SUMMARY.json preserves all per-window metrics, symbol/event concentration, ten largest winners/losses, maximum-trade concentration, exposure and grouped loss streaks. T/F accounting preserves every winner harmed, large-winner damage and eight exhaustive common/new/removed/state-transition groups. No period DD is summed.

F1/F0 use one frozen equal-width interval each. Differences are descriptive USED_DEV evidence; a profitable F1 alone does not establish golden-ratio causality. CHARTS contains the earliest win/loss/open/excluded observation by decision timestamp, symbol and original index, with explicit missing-category records. All signals remain machine-readable in RAW and RESULT events, including excluded signals. These post-outcome plots are not blind OOS evidence.

Costs are the inherited research model, including its floor, spread/impact and funding proxy. No new actual fill, tick-volume, exchange-resident stop or live-futures execution is claimed. No initial SL, TP, leverage, sizing, source collection, unused OOS, paid AI, orders or deployment was authorized by these results.

## Deterministic source charts

- [M1/DEV2025/BCH-USDT/82/1735790400000 — WIN](CHARTS/M1_DEV2025_WIN.png)
- [M1/DEV2025/1000PEPE-USDT/73/1735660800000 — LOSS](CHARTS/M1_DEV2025_LOSS.png)
- [M1/DEV2025/1000PEPE-USDT/2241/1766880000000 — OPEN](CHARTS/M1_DEV2025_OPEN.png)
- [M1/DEV2025/BTC-USDT/1636/1758168000000 — EXCLUDED](CHARTS/M1_DEV2025_EXCLUDED.png)
- [R1/DEV2025/ETH-USDT/154/1736827200000 — WIN](CHARTS/R1_DEV2025_WIN.png)
- [R1/DEV2025/1000PEPE-USDT/486/1741608000000 — LOSS](CHARTS/R1_DEV2025_LOSS.png)
- [M1/SEEN2026/SOL-USDT/3255/1781481600000 — WIN](CHARTS/M1_SEEN2026_WIN.png)
- [M1/SEEN2026/BCH-USDT/3044/1778443200000 — LOSS](CHARTS/M1_SEEN2026_LOSS.png)
- [M1/SEEN2026/1000PEPE-USDT/3739/1788451200000 — OPEN](CHARTS/M1_SEEN2026_OPEN.png)
- [R1/SEEN2026/LINK-USDT/3157/1780070400000 — WIN](CHARTS/R1_SEEN2026_WIN.png)
- [R1/SEEN2026/BTC-USDT/3123/1779580800000 — EXCLUDED](CHARTS/R1_SEEN2026_EXCLUDED.png)

## Result interpretation and blocked scope

M1 improves all four comparisons in SEEN2026, including total net +4293.52 bps, but DEV2025 total net falls by9535.71 bps and win rate falls. Its frozen REJECT label means failure of the BOTH-period joint objective; it does not mean no positive result exists anywhere. R1 SEEN2026 has only3 completed trades and one trade supplies91.48% of its positive net. Its100% WR is not robust profitability evidence. The original C54 remains preserved.

T1/F1/F0 never ran, consumed no candidate or execution, and have no attribution or Fibonacci efficacy result. Source-volume semantics are the precise remaining blocker. M1/R1 have different signal pools: C54 winner damage or common-origin repair cannot be causally assigned to them. Their full win/loss distributions and concentration are in SUMMARY.json, with exact common-calendar drawdown windows in SAME_CALENDAR_RISK.json. No standalone profit is added to C54.

New candidates2 / FULL4; cumulative59/98. No new market collection, unused OOS, paid AI, orders or deployment. The6 unused FULL slots are not scheduled or retried. Own economics have ended; required CI/review/merge closure is tracked in PR1229.
