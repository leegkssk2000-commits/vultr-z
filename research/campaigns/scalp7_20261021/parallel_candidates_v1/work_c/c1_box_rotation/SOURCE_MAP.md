# C1 fixed confirmed box rotation

Status: source/code ready for owner consumption; economic results and marginal portfolio contribution are **NOT_MEASURED**.

## Primary material and attribution

- Author: Al Brooks / Brooks Trading Course.
- URL: https://www.brookstradingcourse.com/price-action-trading-terms-glossary/
- Existing repository source: `BROOKS_GLOSSARY`, `research/campaigns/scalp7_20260917/source_fidelity_v1/audits/REBUILD_SOURCES.json#source_receipts` at base `3f4a798f15fbb3a21f3f6063db1b063b95d182e0`.
- This Work read the primary page on 2026-10-21 (one page; no paid content).
- Verified scope: glossary entries trading range, double bottom/top, reversal bar, high1, context. The glossary describes sideways overlap, repeated failed breakout attempts and prior-bar context. It supplies price-action concepts, **not** this candidate's complete rules.
- Original market/timeframe: general glossary with examples from E-mini/QQQ and intraday charts; no certified crypto30m strategy.
- Public profit claims used: none. External implementation observed: none. Audited external PnL is neither available here nor required for a synthetic development test.

## Explicit internal adaptation, fixed before testing

All numerical choices in `SPEC.json` are ZEL design assumptions: 12 completed30m formation bars; two separated tests at each edge; separation3; edge zone10%; interleaved tests; a frozen range valid for6 bars; bullish in-range lower20% rejection with close between25% and50%; floor stop; geometric-center close exit at next open; hold8; fresh12-bar reformation after one signal, expiry or breach. None is attributed to Brooks, optimized on historical PnL, or an SSOT risk/promotion change.

The hypothesis is range rotation without any lower-bound breach. Signals are long-only for this new identity. This leaves both directions and all authority of existing K/S controls unchanged.

## Exact difference from previous rejected identities

- `range_fade__donor_state_machine_v2`: old5m EMA21/55 flatness, rolling20 extreme breach/reclaim with ATR tolerance, trend veto, ATR stop and VWAP50 target. C1 has30m frozen two-sided tested edges, no breach/reclaim, no EMA/ATR/VWAP and a geometric-center close exit.
- `bb_revert__donor_state_machine_v2`: oldBB20/1.8 extension/reentry, ATR stop and rolling mean target. C1 never uses bands or their extension and never rolls the target during a setup.
- Failure evidence remains `research/campaigns/scalp7_20260917/source_fidelity_v1/audits/MATERIAL_HOLD_SOURCES.json` at base above. No old result was replayed or overwritten.
- Keltner/HG and Squeeze aim at trend/expansion opportunities. C1 requires a confirmed fixed range and rotation; whether this supplies different dates is still unmeasured.

## Execution, inputs and remaining uncertainty

`adapter.py` emits the existing `scalp7_execution_v2` signal contract and supplies callbacks. The unchanged engine owns next-open fills, resting stop/gap handling, fees, occupancy and unresolved positions. A close-confirmed center exit never invents a resting-limit fill. A signal whose next open reaches/passes the center or floor is rejected.

Inputs are existing complete six-symbol30m OHLC/time/segment fields. Volume, L2, OI, tick size and higher timeframes are unused. Gaps or late feature availability reset setup formation. Historical availability remains a bar-close model, not measured delivery latency.

21 synthetic tests passed; synthetic price arithmetic is not profitability evidence. Owner must bind the pinned existing source/cost/window contract, verify current sole-owner consumption and capacity, and run this identity at most once under the existing batch authority. Net/PF/frequency, actual historical funding, independent OOS and shared-account contribution remain unverified.
