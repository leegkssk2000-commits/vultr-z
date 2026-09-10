# Frozen C63/C70 profit management component

Scope: C63_C70_TRADER_PROFIT_LIFECYCLE_AFTER_PR1258_V1, Issue #1259.
No outcomes from either new child existed when this contract was selected.

## Parent binding
C63 is SQUEEZE_M1_ER_OR_PRIOR_RANGE_ESCAPE_V1. Its prior_high excludes the signal candle; floor includes the release candle. Entry pool, eligibility, next actual open, unit initial notional and decision-time occupancy remain native.
C70_LOCAL is registered71, C69_DAILY21_OR_NONFALLING_SMA5_STRICT_RANGE_ESCAPE_V1. Its original imported archive/spec/result SHA and the complete original event projection are preserved. Current master implements its exact predicate in the independent verify_corrected.py; the new adapter implements that same predicate and is checked on every saved entry observation. It is not PR1243's deferred C70 or candidate72's prior-session-high replacement. No historical parent position is rerun.

## Source selection and fidelity
First compatible source: Qullamaggie Breakout management. Educational primary source; financial success is self-reported, not a verified track record. Source selection uses public numeric specification, post-entry stage compatibility and causal executability, with no new child economics. Jerry Parker is not tried because this first source passed. Carter is not transplanted. Full stock selection/entry/ATR sizing is outside this component.

## Source to ZEL contract
| Source management rule | Exact locator | Entry-stage fit | Frozen ZEL operationalization | Clock / unknown |
| --- | --- | --- | --- | --- |
| Realize part after several days | Qullamaggie article, Breakouts, How do you trade, item 4 | Existing breakout-position age begins at actual entry | Third completed UTC daily close after entry; 1/3 assembled quantity; positive close mark after frozen costs only | Decision after daily close; actual next 4h open fill, including gaps; 24/7 crypto calendar is an adaptation |
| Protect remainder at entry and follow a daily average | Same item 4 | Remainder exists after actual partial | Raw entry-price break-even protection and SMA10 of completed daily closes; strict daily close below SMA10 triggers next actual open | BE uses completed 4h close<=entry then next open; no promise of a guaranteed break-even fill |

## Exit conflict and event order (fixed before results)
Native floor CLOSE<=original floor always takes first priority, with existing next-open execution. There is no exchange-resident stop and no invented floor fill inside a candle. Before partial fill, native nonpositive momentum remains the failure exit. Native fixed-time20 is replaced throughout: it otherwise caps the source holding lifecycle. After actual partial fill, source BE and SMA10 replace native momentum as profit management; this replacement is needed because a 14x4h momentum reversal is not the source daily runner. Native floor and input integrity continue throughout. This is a hybrid source-grounded component, not a full trader strategy replica.

At a close: floor -> runner BE -> pre-runner native momentum -> armed-runner daily SMA10 -> first D3 partial decision. At the next observed open: execute only the previously sealed action before reading that bar's high/low/close. If D3 is profitable but its completed close already violates SMA10, record the 1/3 partial and close the remaining 2/3 at that same next open; no extra entry filter. Missing SMA10 at that point gives the same safe remaining exit. A nonpositive D3 never retries the profit partial and retains native failure protection. The third day counts only closes strictly after actual entry (including the entry UTC day's eventual completed close).

Partial does not release occupancy. Only full final fill releases a slot; a signal at the final fill timestamp remains occupied under the native decision-time rule. At the exact window end, a pending exit/partial remains unfilled and the residual is marked with remaining liquidation costs. No future open is loaded for settlement.

## Quantity / cash / marks
One campaign starts with normalized quantity1 and unchanged entry price. Partial1/3 and final2/3 each carry their corresponding share of entry/exit fee, spread, impact, elapsed 8h funding and frozen20bps floor. Fractions sum1, so entry fees are not double charged. Funding uses entry<settlement<=exit/mark. Cost2 doubles all modeled components. Daily marks are the sum of realized partial and marked residual legs; WR counts completed campaigns only. Exposure reports both occupied campaign time and quantity-weighted symbol-days. These are equal-initial-notional trade-bps, not account percentage returns, and inherited historical costs are proxies.

## Budget / judgment
Two children jointly frozen: C63_TM and C70_TM. Four first FULLs in the original DEV2025 and SEEN2026 USED_DEV windows; parent replay0, FIXED0, sweep0, retry0, OOS0, paidAI0, order0, deploy0. Only this Work owns execution. Reserve/read-back each execution on the remote branch, allocate candidate/evaluation numbers at actual start behind79/142, and persist the consumed result before the next slot. Failed attempts consume their slot and cannot retry automatically.

Source conformance and economic increment are separate. For each child, positive terminal net AND cost2 deltas in both periods are a positive economic increment; report WR, payoff, PF, DD, loss tail and winner retention tradeoffs separately. A period reversal is TRADEOFF; two negative increments REJECT. Preserve a development workcopy only when it improves both periods without worsening marked DD or ordinary/top-decile winner retention. A C70 workcopy must additionally maintain positive total advantage over C63 in both periods. No automatic operating adoption, no year-specific choice, no next source.

All existing evidence bytes remain untouched. Final CI verifies saved outputs and synthetic regression only. Economic CLI is a temporary Work-local runner removed before final review. Close only this scope to REPORT_ONLY after saved verification and normal PR merge; record exact merge SHA verification.
