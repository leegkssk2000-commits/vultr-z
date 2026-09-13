# G4 Scalp Round1 source repair plan

Issue #1322 remains the authority for Round1. This repair changes only the historical source plumbing used by the already-frozen native Round1 contract.

- Preserve the exact common window `2026-03-12T14:00:00Z` inclusive to `2026-09-12T14:00:00Z` exclusive.
- Preserve Liquid5: BTC-USDT, ETH-USDT, LINK-USDT, SOL-USDT, XRP-USDT.
- Reuse the proven BingX 1m collector lineage from branch `zel-bingx-1m-backfill-stage-v1` (`backend/tools/zel_bingx_1m_backfill_stage_v1.py`).
- Fetch authentic BingX public 1m rows with deterministic sub-1000-bar chunking and targeted authentic-source gap retries only.
- Aggregate each 5m bucket from exactly five contiguous 1m rows: first open, max high, min low, last close, summed volume.
- Any missing 1m row, conflicting duplicate, invalid OHLCV, incomplete 5m bucket, or coverage mismatch fails closed. No synthetic fill, forward fill, proxy bar, window shortening, strategy-rule change, cost change, threshold relaxation, or symbol cherry-pick is allowed.
- Feed the resulting 5m cache into the unchanged Round1 native economics runner, then checkpoint each completed strategy lane before moving to the next lane.
- This remains descriptive development evidence only: no selection/promotion/order/live/G5 authority.
