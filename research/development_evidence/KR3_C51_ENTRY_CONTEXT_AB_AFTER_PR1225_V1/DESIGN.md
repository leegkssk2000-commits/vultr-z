# C51 entry-context factorial — pre-outcome design

User explicitly approved the immediately preceding A / B / A+B entry-context plan with `다음으로 들어가`. This is a new, finite research implementation/economic comparison, not a re-run of completed PR1225. AGENTS' explicit-request exception applies only to this backend research module, tests, evidence and associated CI. Canonical frontend validation still runs; no deployment/SSH.

Current master3feaf364ed4b3da20876a61d4d8174c2d18f4f90 and recent/openPRs were checked once. Latest measured ledger is PR1225 candidate52/evaluation84; C52 rejected, C51 kept. UnrelatedPR1084 and all collectors/otherWork remain untouched. This Chat is the sole source/budget/economic writer. No Work session is implicitly launched. Three new hypotheses, six FULL applications only; old C51/KR3 results reused. No fixed-path replay, neighbor search, extra indicator family, source collection, unused OOS, paid model API, orders or sizing changes.

## Mechanism and exact constants
Direct parent C51 (`kr3_profit_zone_exit_v1.py`) preserves original KR3 signal pool, bounded EMA seed, next-open entry, signal-half predicate, causal reference reservations, all existing exit priorities and C51 profit-zone protection. Each candidate can veto actual entry; immutable reference reservations remain even for a veto. Actual symbol occupancy is replayed chronologically, so new subsequent opportunities may appear; do not simply subset saved parent trades.

A / candidate53: locate the immediately preceding contiguous sequence of completed closes <= native EMA20 ending at signal i-1. Let q be its last preceding completed close > EMA20. At q require EMA20>EMA50, +DI14>-DI14, ADX14>=25, ADX14[q]>ADX14[q-1]. Missing prior episode/ADX seed rejects A. No requirement that ADX rises on the recovery signal. No backward search for a favorable ADX peak. No expired-trend-age constant added. Existing top5_external_features_v1.directional_movement computes DMI, source-pinned with policy_kernel_v1. The period14 and strength25 are conventional research settings already present in prior external code, not calibrated on new outcomes or a claim of optimality.

B / candidate54: (signal close - native EMA20) / ATR14[i-1] must be >0 and <=1. ATR14 is Wilder RMA, seed TR1..TR14 (row0 excluded); gaps included through previous close. Use previous-bar ATR so the trigger's own large range cannot loosen its threshold. One ATR is an interpretable unit-range cap, a NEW research hypothesis, not an SSOT risk threshold or optimized number. No execution price override; actual next-open gaps remain.

AB / candidate55: exact logical conjunction of the same A and B, with no new constants. All three are frozen together before the first market result. RVOL deferred as previously stated. No RSI/volume threshold, new SL/TP, extra delay, timeframe change or year/symbol selectors.

## Comparisons and limits
Run order A2025,A2026,B2025,B2026,AB2025,AB2026. Candidate ordinal assigned on first actual start; failed/unknown reservations remain and block retries. Six slots max, no rerun until success. Each runtime claim is committed and remotely read back before engine invocation. Preserve every old budget field, attempted result and failure. Source packet hashes match C51 and only its approved USED_DEV intervals/warmup are decoded.

Development objective retained from C51: WR up, terminal net up, all-cost2 up, daily markedDD down, each period; eight checks. Tradeoff and failed increments retained without operating adoption. Entry count/exposure, PF/payoff/average losses, avoided loss vs foregone winners, top-decile/capped retention, new/displaced/open transitions and event/symbol concentration reported. AB interaction=deltaAB-deltaA-deltaB is descriptive factorial accounting, not independence or guaranteed synergy.

All raw signals retain their reasons and completed-bar feature availability. Parent labels are post-run accounting only. Same nominal trade-bps and hypothetical open marks are not account returns, actual execution, signed funding or15x futures proof. G5 hold/formalcredit0. No automatic promotion merely from stored-DEV arithmetic.

## Preflight and stop
41 artificial tests (16 new plus25 inherited C51) passed locally before market inputs were replayed. Prefix/future-data invariance, pre-pullback timing, lagged ATR/equality/zero, disabled exact parent, accept-all exact fills/clock, veto without fictitious wins/cost, prior reservations, boundary/open mark and hook restoration checked. Remote repeats the same tests before freeze/claims. Parameter values are not retuned based on diagnostics or outcomes.

Final validation must compare raw geometry/cost/metric accounting and confirm full net contribution, not hashes alone. Related CI/review/merge and exact-merge saved verification only; completed dispatcher is removed. Bound response45min, no busy polling or waiting for G5. On real blocker preserve IDs/evidence and close CHECKPOINTED. No blanket process cancellation, reset/clean, collector edits or platform billing-stop guarantee. Final report once; no further economic execution after scope completion.
