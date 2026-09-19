# Source-fidelity saved economic comparison

Four parent/child comparisons from five new FULL identities and three exact saved parents. No parent FULL replay. All bps are summed equal-original-notional trade diagnostics; account returns and MTM drawdown are N/A. Historical validation and rolling windows were already inspected. Fresh T = 0; promotion, orders and live remain blocked.

## Rolling — 245 calendar days

| Pair | T P→C | WR% P→C | Net bps P→C | DD bps P→C | Net 2x P→C | Winner profit retained | Strict gains /4 |
|---|---:|---:|---:|---:|---:|---:|---:|
| HG | 109→131 | 59.63→52.67 | 5947.63→2933.94 | 1609.47→4061.00 | 4308.32→972.98 | 76.76% | 1 |
| RSI | 2724→4269 | 37.04→36.66 | -46463.65→-71766.75 | 47717.78→72772.30 | -87200.25→-135650.33 | 13.31% | 1 |
| BREAK | 871→1145 | 25.95→25.33 | -15017.98→-20408.23 | 17139.63→23241.34 | -28028.36→-37488.99 | 87.91% | 1 |
| SR | 2224→2625 | 27.92→27.66 | -33160.37→-39182.70 | 34736.50→40665.36 | -66230.90→-78256.41 | 94.29% | 1 |

Strict gains count T↑, WR↑, Net↑ and realized DD↓. This is descriptive, not a promotion gate.

### HG: 30m

Parent: scalp7_keltner_hg_parent_utc30m_v2. Child: scalp7_hg_initial_qualification_pullback_30m_fidelity_v1.

| Side | T/day | Gross/T | Cost/T | Net/T | PF | Loss streak | ES5 all trades | Hold p50/p95 min | Unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| parent | 0.44 | 69.61 | 15.04 | 54.57 | 2.00 | 5 | -289.17 | 180.00/750.00 | 0 |
| child | 0.53 | 37.37 | 14.97 | 22.40 | 1.38 | 11 | -277.82 | 150.00/750.00 | 0 |

Net change -3013.69 = common-event change 0.00 + removed-parent contribution -2082.60 + added-child net -931.09. Event counts common/missed/added: 92/17/39.
Parent-winner group net change including missed winners: -2760.14; parent-loser observed loss saved: 677.55. Missing events contribute zero actual child PnL; their hypothetical PnL is not estimated.
Child-minus-unchanged-parent net after removing the largest child winner: -3994.23; after removing the largest added winner: -3472.25.
Exact-time same-direction losing clusters P/C: 3/6; worst cluster bps -892.53/-892.53.
Window outcomes positive/negative/nonempty-zero/empty P: {"empty": 0, "negative": 3, "nonempty_zero": 0, "positive": 6}; C: {"empty": 0, "negative": 5, "nonempty_zero": 0, "positive": 4}.
All emitted opportunity classifications P: {"BLOCKED_BY_COMPLETED_POSITION_OCCUPANCY": 8, "COMPLETED_INCLUDED": 109, "EMITTED_WITHOUT_SAVED_FILL_OR_OCCUPANCY_BLOCKER": 81}; C: {"BLOCKED_BY_COMPLETED_POSITION_OCCUPANCY": 9, "COMPLETED_INCLUDED": 131, "EMITTED_WITHOUT_SAVED_FILL_OR_OCCUPANCY_BLOCKER": 106}.

### RSI: 30m

Parent: rsi_swing_fail_30m_control_v2. Child: rsi_oscillator_failure_swing_30m_source_fidelity_v1.

| Side | T/day | Gross/T | Cost/T | Net/T | PF | Loss streak | ES5 all trades | Hold p50/p95 min | Unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| parent | 11.12 | -2.10 | 14.95 | -17.06 | 0.59 | 30 | -129.67 | 90.00/420.00 | 12 |
| child | 17.42 | -1.85 | 14.96 | -16.81 | 0.59 | 24 | -122.16 | 90.00/420.00 | 16 |

Net change -25303.10 = common-event change 0.00 + removed-parent contribution 37570.35 + added-child net -62873.44. Event counts common/missed/added: 389/2335/3880.
Parent-winner group net change including missed winners: -56790.02; parent-loser observed loss saved: 94360.37. Missing events contribute zero actual child PnL; their hypothetical PnL is not estimated.
Child-minus-unchanged-parent net after removing the largest child winner: -25665.06; after removing the largest added winner: -25665.06.
Exact-time same-direction losing clusters P/C: 316/503; worst cluster bps -880.21/-561.49.
Window outcomes positive/negative/nonempty-zero/empty P: {"empty": 0, "negative": 9, "nonempty_zero": 0, "positive": 0}; C: {"empty": 0, "negative": 9, "nonempty_zero": 0, "positive": 0}.
All emitted opportunity classifications P: {"BLOCKED_BY_COMPLETED_POSITION_OCCUPANCY": 134, "BLOCKED_BY_UNRESOLVED_OCCUPANCY": 139, "COMPLETED_INCLUDED": 2724, "COMPLETED_OUTSIDE_STRICT_WINDOW": 1, "ENTERED_UNRESOLVED_NO_REALIZED_PNL": 12}; C: {"BLOCKED_BY_COMPLETED_POSITION_OCCUPANCY": 489, "BLOCKED_BY_UNRESOLVED_OCCUPANCY": 5, "COMPLETED_INCLUDED": 4269, "COMPLETED_OUTSIDE_STRICT_WINDOW": 1, "ENTERED_UNRESOLVED_NO_REALIZED_PNL": 16}.

### BREAK: 15m

Parent: scalp7_break_15m_anchored_retest_reclaim_v2. Child: scalp7_break_shallow_additional_path_15m_v1.

| Side | T/day | Gross/T | Cost/T | Net/T | PF | Loss streak | ES5 all trades | Hold p50/p95 min | Unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| parent | 3.56 | -2.30 | 14.94 | -17.24 | 0.68 | 23 | -198.97 | 180.00/360.00 | 4 |
| child | 4.67 | -2.91 | 14.92 | -17.82 | 0.66 | 25 | -183.91 | 165.00/360.00 | 8 |

Net change -5390.25 = common-event change -9.99 + removed-parent contribution 850.62 + added-child net -6230.87. Event counts common/missed/added: 804/67/341.
Parent-winner group net change including missed winners: -3917.21; parent-loser observed loss saved: 4757.84. Missing events contribute zero actual child PnL; their hypothetical PnL is not estimated.
Child-minus-unchanged-parent net after removing the largest child winner: -6636.21; after removing the largest added winner: -6097.24.
Exact-time same-direction losing clusters P/C: 56/91; worst cluster bps -408.87/-469.06.
Window outcomes positive/negative/nonempty-zero/empty P: {"empty": 0, "negative": 8, "nonempty_zero": 0, "positive": 1}; C: {"empty": 0, "negative": 8, "nonempty_zero": 0, "positive": 1}.
All emitted opportunity classifications P: {"BLOCKED_BY_COMPLETED_POSITION_OCCUPANCY": 86, "BLOCKED_BY_UNRESOLVED_OCCUPANCY": 18, "COMPLETED_INCLUDED": 871, "ENTERED_UNRESOLVED_NO_REALIZED_PNL": 4}; C: {"BLOCKED_BY_COMPLETED_POSITION_OCCUPANCY": 184, "BLOCKED_BY_UNRESOLVED_OCCUPANCY": 129, "COMPLETED_INCLUDED": 1145, "COMPLETED_OUTSIDE_STRICT_WINDOW": 1, "DUPLICATE_SIGNAL_REJECTED": 21, "ENTERED_UNRESOLVED_NO_REALIZED_PNL": 8}.

### SR: 30m

Parent: sr_levels_30m_native_control_fidelity_v1. Child: sr_levels_30m_prebreak_reference_reclaim_fidelity_v1.

| Side | T/day | Gross/T | Cost/T | Net/T | PF | Loss streak | ES5 all trades | Hold p50/p95 min | Unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| parent | 9.08 | -0.04 | 14.87 | -14.91 | 0.61 | 28 | -206.05 | 30.00/120.00 | 6 |
| child | 10.71 | -0.04 | 14.89 | -14.93 | 0.60 | 33 | -195.73 | 30.00/120.00 | 7 |

Net change -6022.32 = common-event change 0.00 + removed-parent contribution 260.05 + added-child net -6282.37. Event counts common/missed/added: 2133/91/492.
Parent-winner group net change including missed winners: -2971.65; parent-loser observed loss saved: 3231.70. Missing events contribute zero actual child PnL; their hypothetical PnL is not estimated.
Child-minus-unchanged-parent net after removing the largest child winner: -6676.10; after removing the largest added winner: -6588.86.
Exact-time same-direction losing clusters P/C: 364/419; worst cluster bps -2574.35/-2574.35.
Window outcomes positive/negative/nonempty-zero/empty P: {"empty": 0, "negative": 9, "nonempty_zero": 0, "positive": 0}; C: {"empty": 0, "negative": 9, "nonempty_zero": 0, "positive": 0}.
All emitted opportunity classifications P: {"BLOCKED_BY_COMPLETED_POSITION_OCCUPANCY": 534, "COMPLETED_INCLUDED": 2224, "ENTERED_UNRESOLVED_NO_REALIZED_PNL": 6}; C: {"BLOCKED_BY_COMPLETED_POSITION_OCCUPANCY": 808, "BLOCKED_BY_UNRESOLVED_OCCUPANCY": 1, "COMPLETED_INCLUDED": 2625, "ENTERED_UNRESOLVED_NO_REALIZED_PNL": 7}.

## Validation — 30 calendar days

| Pair | T P→C | WR% P→C | Net bps P→C | DD bps P→C | Net 2x P→C | Winner profit retained | Strict gains /4 |
|---|---:|---:|---:|---:|---:|---:|---:|
| HG | 10→13 | 70.00→46.15 | 752.81→414.06 | 339.53→676.27 | 602.65→213.71 | 99.82% | 1 |
| RSI | 372→594 | 36.83→38.72 | -5315.74→-8752.12 | 6494.38→9467.81 | -10853.65→-17630.50 | 13.46% | 2 |
| BREAK | 106→142 | 32.08→28.87 | -754.15→-2276.17 | 1641.93→2976.66 | -2330.42→-4400.31 | 94.31% | 1 |
| SR | 267→324 | 29.21→28.40 | -5779.51→-6616.79 | 5779.51→6698.92 | -9781.92→-11462.60 | 99.41% | 1 |

Strict gains count T↑, WR↑, Net↑ and realized DD↓. This is descriptive, not a promotion gate.

### HG: 30m

Parent: scalp7_keltner_hg_parent_utc30m_v2. Child: scalp7_hg_initial_qualification_pullback_30m_fidelity_v1.

| Side | T/day | Gross/T | Cost/T | Net/T | PF | Loss streak | ES5 all trades | Hold p50/p95 min | Unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| parent | 0.33 | 90.30 | 15.02 | 75.28 | 3.19 | 2 | -153.28 | 255.00/750.00 | 0 |
| child | 0.43 | 47.26 | 15.41 | 31.85 | 1.61 | 5 | -153.28 | 150.00/750.00 | 0 |

Net change -338.75 = common-event change 0.00 + removed-parent contribution -2.00 + added-child net -336.75. Event counts common/missed/added: 9/1/4.
Parent-winner group net change including missed winners: -2.00; parent-loser observed loss saved: 0.00. Missing events contribute zero actual child PnL; their hypothetical PnL is not estimated.
Child-minus-unchanged-parent net after removing the largest child winner: -1137.38; after removing the largest added winner: -338.75.
Exact-time same-direction losing clusters P/C: 1/2; worst cluster bps -273.79/-273.79.
Window outcomes positive/negative/nonempty-zero/empty P: {"empty": 0, "negative": 0, "nonempty_zero": 0, "positive": 1}; C: {"empty": 0, "negative": 0, "nonempty_zero": 0, "positive": 1}.
All emitted opportunity classifications P: {"COMPLETED_INCLUDED": 10, "EMITTED_WITHOUT_SAVED_FILL_OR_OCCUPANCY_BLOCKER": 11}; C: {"BLOCKED_BY_COMPLETED_POSITION_OCCUPANCY": 1, "COMPLETED_INCLUDED": 13, "EMITTED_WITHOUT_SAVED_FILL_OR_OCCUPANCY_BLOCKER": 15}.

### RSI: 30m

Parent: rsi_swing_fail_30m_control_v2. Child: rsi_oscillator_failure_swing_30m_source_fidelity_v1.

| Side | T/day | Gross/T | Cost/T | Net/T | PF | Loss streak | ES5 all trades | Hold p50/p95 min | Unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| parent | 12.40 | 0.60 | 14.89 | -14.29 | 0.62 | 11 | -111.59 | 90.00/540.00 | 0 |
| child | 19.80 | 0.21 | 14.95 | -14.73 | 0.61 | 17 | -115.57 | 90.00/430.50 | 1 |

Net change -3436.37 = common-event change 0.00 + removed-parent contribution 4098.17 + added-child net -7534.54. Event counts common/missed/added: 65/307/529.
Parent-winner group net change including missed winners: -7552.91; parent-loser observed loss saved: 11651.07. Missing events contribute zero actual child PnL; their hypothetical PnL is not estimated.
Child-minus-unchanged-parent net after removing the largest child winner: -3612.06; after removing the largest added winner: -3612.06.
Exact-time same-direction losing clusters P/C: 40/61; worst cluster bps -374.01/-419.21.
Window outcomes positive/negative/nonempty-zero/empty P: {"empty": 0, "negative": 1, "nonempty_zero": 0, "positive": 0}; C: {"empty": 0, "negative": 1, "nonempty_zero": 0, "positive": 0}.
All emitted opportunity classifications P: {"BLOCKED_BY_COMPLETED_POSITION_OCCUPANCY": 13, "COMPLETED_INCLUDED": 372}; C: {"BLOCKED_BY_COMPLETED_POSITION_OCCUPANCY": 72, "COMPLETED_INCLUDED": 594, "ENTERED_UNRESOLVED_NO_REALIZED_PNL": 1}.

### BREAK: 15m

Parent: scalp7_break_15m_anchored_retest_reclaim_v2. Child: scalp7_break_shallow_additional_path_15m_v1.

| Side | T/day | Gross/T | Cost/T | Net/T | PF | Loss streak | ES5 all trades | Hold p50/p95 min | Unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| parent | 3.53 | 7.76 | 14.87 | -7.11 | 0.84 | 13 | -178.63 | 240.00/360.00 | 0 |
| child | 4.73 | -1.07 | 14.96 | -16.03 | 0.68 | 17 | -179.34 | 240.00/360.00 | 0 |

Net change -1522.02 = common-event change 0.00 + removed-parent contribution 1.77 + added-child net -1523.79. Event counts common/missed/added: 102/4/40.
Parent-winner group net change including missed winners: -233.50; parent-loser observed loss saved: 235.27. Missing events contribute zero actual child PnL; their hypothetical PnL is not estimated.
Child-minus-unchanged-parent net after removing the largest child winner: -2270.35; after removing the largest added winner: -1843.29.
Exact-time same-direction losing clusters P/C: 5/12; worst cluster bps -257.29/-372.73.
Window outcomes positive/negative/nonempty-zero/empty P: {"empty": 0, "negative": 1, "nonempty_zero": 0, "positive": 0}; C: {"empty": 0, "negative": 1, "nonempty_zero": 0, "positive": 0}.
All emitted opportunity classifications P: {"BLOCKED_BY_COMPLETED_POSITION_OCCUPANCY": 9, "COMPLETED_INCLUDED": 106}; C: {"BLOCKED_BY_COMPLETED_POSITION_OCCUPANCY": 25, "COMPLETED_INCLUDED": 142, "DUPLICATE_SIGNAL_REJECTED": 2}.

### SR: 30m

Parent: sr_levels_30m_native_control_fidelity_v1. Child: sr_levels_30m_prebreak_reference_reclaim_fidelity_v1.

| Side | T/day | Gross/T | Cost/T | Net/T | PF | Loss streak | ES5 all trades | Hold p50/p95 min | Unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| parent | 8.90 | -6.66 | 14.99 | -21.65 | 0.44 | 15 | -198.97 | 30.00/120.00 | 0 |
| child | 10.80 | -5.47 | 14.96 | -20.42 | 0.45 | 20 | -187.08 | 30.00/120.00 | 0 |

Net change -837.28 = common-event change 0.00 + removed-parent contribution 329.33 + added-child net -1166.61. Event counts common/missed/added: 260/7/64.
Parent-winner group net change including missed winners: -26.27; parent-loser observed loss saved: 355.60. Missing events contribute zero actual child PnL; their hypothetical PnL is not estimated.
Child-minus-unchanged-parent net after removing the largest child winner: -1296.64; after removing the largest added winner: -1024.54.
Exact-time same-direction losing clusters P/C: 38/51; worst cluster bps -1390.65/-1390.65.
Window outcomes positive/negative/nonempty-zero/empty P: {"empty": 0, "negative": 1, "nonempty_zero": 0, "positive": 0}; C: {"empty": 0, "negative": 1, "nonempty_zero": 0, "positive": 0}.
All emitted opportunity classifications P: {"BLOCKED_BY_COMPLETED_POSITION_OCCUPANCY": 68, "COMPLETED_INCLUDED": 267}; C: {"BLOCKED_BY_COMPLETED_POSITION_OCCUPANCY": 102, "COMPLETED_INCLUDED": 324}.

## Evidence limits

ECONOMIC_COMPARISON.json contains every event attribution, full window/month/symbol metrics, occupancy witnesses, tails, cost stress and exact input hashes. Occupancy classification uses saved real entries and unresolved positions. It does not fabricate outcomes for blocked opportunities.
Legacy HG parent receipts did not retain partial-fill cashflows. Their immutable gross and cost/net arithmetic are preserved; missing partial timing or prices are not reconstructed. New ledgers are independently checked against saved partial and terminal cashflows.
Behavior cosine is not measured; no fusion authority follows. The existing seven-strategy portfolio was not replayed or replaced. Source fidelity is not economic profitability or promotion evidence.
