# M1 outcome review

All amounts are equal-nominal trade-bps, not account returns. M stays the partial development workcopy; M1 is DEV_REJECT under unchanged inherited criteria in both periods. No automatic workcopy replacement.

| Metric | 2025 M | 2025 M1 | 2026 M | 2026 M1 |
|---|---:|---:|---:|---:|
| closed_T | 202.0000 | 202.0000 | 75.0000 | 75.0000 |
| open_T | 1.0000 | 1.0000 | 4.0000 | 4.0000 |
| raw_signal_T | 379.0000 | 379.0000 | 126.0000 | 126.0000 |
| entries_T | 203.0000 | 203.0000 | 79.0000 | 79.0000 |
| closed_net_bps | 6,022.2077 | 2,843.5413 | -397.8979 | 831.0990 |
| net_expectancy_bps_per_closed_trade | 29.8129 | 14.0769 | -5.3053 | 11.0813 |
| PF | 1.1542 | 1.0743 | 0.9713 | 1.0727 |
| win_rate | 0.4851 | 0.3812 | 0.3600 | 0.3200 |
| realized_payoff | 1.2248 | 1.7439 | 1.7268 | 2.2794 |
| closed_cost2x_net_bps | 1,749.8864 | -1,345.0177 | -1,998.2077 | -728.1441 |
| terminal_net_bps_hypothetical | 5,945.4766 | 2,766.8103 | -1,014.8835 | 214.1134 |
| terminal_cost2x_net_bps_hypothetical | 1,653.1553 | -1,441.7488 | -2,695.1933 | -1,425.1297 |
| marked_DD_trade_sum_bps | 11,605.8331 | 9,400.2302 | 5,643.8641 | 4,573.0257 |
| grouped_max_loss_trade_sum_bps | 4,782.5329 | 3,821.3935 | 3,758.3091 | 2,056.4371 |
| exposure_symbol_days | 372.6667 | 271.0000 | 141.1667 | 103.1667 |

The priority2026 terminal cost2 deficit falls from2695.193323 to1425.129717:1270.063606 reduced (47.12%), with1425.129717 still lost. Closed base improves1228.996869; terminal base becomes+214.113378, including all4 open marks totaling−616.985597. Cost2 remains negative.

2025 closed net preserves47.217590% of M (2843.541337/6022.207694); terminal net preserves46.53639% (2766.810273/5945.476630). The2025 net reduction is3178.666357 and terminal cost2 turns negative at−1441.748803. Both periods reduce marked DD and grouped losing-run loss, but this does not offset the loss of the2025 cost-stress surplus under the frozen cumulative goal. M remains the workcopy; M1 evidence and its risk improvements are preserved.

DEV2025 intervention accounting:

- Actual M1 trigger positions 96, without M1-priority trigger 107; executed M1 closes 96. Separate D-priority low/EMA overlaps 5. Trigger includes terminal-pending state; a pending order is not a fill.
- Original timeout-loss cohort: 70; triggered 49; combined signed net improvement 673.783981.
- Original winning-profit amount lost, capped at zero per former winner: 3946.990994; retained 91.244892%. Large-winner amount retained 100.000000%.
- The field winner_profit_cut (9478.979216) is the FULL net deterioration on original winning positions, including additional loss after a winner turns negative. It must not be confused with capped original-profit loss (3946.990994); both amounts are already part of signed net attribution, never additional deductions.
- Actual entries unchanged, new/removed entries0. Virtual reference economics0. After actual closes reference remains active for a total 101.666667 symbol-days, without market exposure attributed to those virtual reservations.
- The reference holding-duration sum above includes all actual/reference end differences; all reservation/entry timestamps and events match M exactly.

| Disjoint parent group | T | M net/mark | M1 net/mark | Delta |
|---|---:|---:|---:|---:|
| HARMFUL_D_EXIT | 16 | -7102.494243 | -5153.668695 | 1948.825548 |
| HELPFUL_D_EXIT | 18 | -10494.612598 | -6816.909268 | 3677.703330 |
| PARENT_OPEN | 1 | -76.731064 | -76.731064 | 0.000000 |
| UNCHANGED_EXIT_LOSS | 70 | -21462.836348 | -20789.052367 | 673.783981 |
| UNCHANGED_EXIT_NONLOSS | 98 | 45082.150882 | 35603.171666 | -9478.979216 |

Paired calendar-sum95% interval [-12776.028202, 3823.521655]. It includes zero; inherited30-day blocks,1000 resamples,seed1178, reused development data are not independent validation.

SEEN2026 intervention accounting:

- Actual M1 trigger positions 33, without M1-priority trigger 46; executed M1 closes 32. Separate D-priority low/EMA overlaps 3. Trigger includes terminal-pending state; a pending order is not a fill.
- Original timeout-loss cohort: 34; triggered 22; combined signed net improvement 1444.512377.
- Original winning-profit amount lost, capped at zero per former winner: 1201.998561; retained 91.077286%. Large-winner amount retained 100.000000%.
- The field winner_profit_cut (1691.451053) is the FULL net deterioration on original winning positions, including additional loss after a winner turns negative. It must not be confused with capped original-profit loss (1201.998561); both amounts are already part of signed net attribution, never additional deductions.
- Actual entries unchanged, new/removed entries0. Virtual reference economics0. After actual closes reference remains active for a total 38.000000 symbol-days, without market exposure attributed to those virtual reservations.
- The reference holding-duration sum above includes all actual/reference end differences; all reservation/entry timestamps and events match M exactly.

| Disjoint parent group | T | M net/mark | M1 net/mark | Delta |
|---|---:|---:|---:|---:|
| HARMFUL_D_EXIT | 7 | -2576.381355 | -1699.727013 | 876.654342 |
| HELPFUL_D_EXIT | 7 | -1792.709451 | -1193.428247 | 599.281204 |
| NEW_TO_P | 1 | 1305.023995 | 1305.023995 | 0.000000 |
| PARENT_OPEN | 4 | -616.985597 | -616.985597 | 0.000000 |
| UNCHANGED_EXIT_LOSS | 34 | -9500.028859 | -8055.516482 | 1444.512377 |
| UNCHANGED_EXIT_NONLOSS | 26 | 12166.197776 | 10474.746723 | -1691.451053 |

Paired calendar-sum95% interval [-256.936482, 6311.688923]. It includes zero; inherited30-day blocks,1000 resamples,seed1178, reused development data are not independent validation.

Preservation and execution record:

- Frozen parentM/code/rules,2025/2026 calendars,seven symbols,funding/cost authority/floor20 are unchanged. No forced liquidation. Close-confirmed signal-low is a research exit, not a native exchange protective SL.
- PR1186 Supertrend signal-low fixed-entry delta−4809.587903, winner deterioration11973.979751,17 winner→loss andDEV_REJECT remain explicit counterevidence. No generic-success claim or result transfer.
- M1 full replay and a separate fixed-M-entry valuation match every closed/open row and trace. Disabled M replay matches the complete stored M view, including causal reference events and costs. Shared daily valuation and same-calendar contribution windows, symbol/month/entry-month results are in the two period ledgers.
- Preregistration remote commit c8faa35cbe838e7289e0cdddda0fcdff3c7341ae predates the M1 result. Prereg CI34063736572PASS/check-only, no economic replay.
- Initial actual writer PID7,UTC2026-09-06T22:20:42.540990→22:20:57.412594,14.897seconds, one candidate attempt31; detailed progress in EXECUTION.jsonl. Later permitted identical CI/master reproductions record their own run ID/time/hash in logs; they are not new candidates.
- Synthetic/direct-dependency tests118 + governance46 + controller16 =180 PASS; compile,Alpha Proof/common self-tests and frontend validationPASS. No economic candidate was run by the separate reviewer.
- Prior30 immutable; candidate31 consumed; remaining0. Prior seen evaluation1/1 and independent comparison0/1NOT_RUN preserved. Q0 futureobserver/G5B/operating code unchanged; no future price use,no new paid AI,executionNONE/orderBLOCKED/liveBLOCKED.
- CI dependency coverage P2 is provided through the existing external-evidence workflow; old sealed M workflow bytes remain unchanged. M1-only changes skip unrelated legacy economic replay. No deployment is requested. Rollback means retaining M, already selected; no operating strategy was switched.
- This file records measured results and local validation. Final-head PR/master CI and merge status are reported from their actual remote checks after result publication; no future PASS is preclaimed.


Separate read-only reviewer:5,560 arithmetic/parity/window assertions passed, with zero raw-price reads, alternative economic runs or edits. This includes2,860 trade/mark/accounting/entry/reference assertions and2,700 component assertions over90 stored same-calendar windows.21 original winners turn into losses in2025,3 in2026. Large winners remain intact.

Same-calendar risk attribution (overlapping windows are not additive):

-2025 M worst-DD interval September19–December29: M−11605.8331→M1−8593.5927, +3012.2404. M1 worst-DD interval August14–December29: M−11215.1124→M1−9400.2302,+1814.8822.
-2026 M worst-DD interval June4–July9: M−5643.8641→M1−3026.4547,+2617.4094. M1 worst-DD interval August28–September5: M−3876.5480→M1−4573.0257,−696.4777. Lower global maximum does not imply improved risk in every common calendar window.

PR1186 counterevidence exact prior result seal:6afdfdf2e8db285ea1fe52fbb40f3621128ec9937387f99c6981c0eabf7391f6; stored receipt result.attribution.fixed. It remains a failure, never a transferred success.
