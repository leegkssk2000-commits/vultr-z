# G5 future CLOSED trades: bounded read-only cost and overlap audit

**Source:** commit `a10927cf8531dc0ee85a9982e85aea281ec98c8d`; source SHA pins in `PIN.json`, raw saved source row hashes in `RESULT.json`. New economic FULL 0, market API calls 0, orders 0, collector changes 0. Existing A owner and B/C/D/F Work unchanged. No new Work.

## Verified source and cost parity

Read only the two immutable Git objects, selected fresh CLOSED rows using `signal_ts >= frozen G5 boundary_ms`, required unique closed trade IDs, chronological entry/exit, exact saved Net = Gross − saved cost. Supplied synthetic cost model 1x/2x, not proven actual funding or slippage. All 10 regression tests PASS after adjusting fixture arithmetic and exact input argument signatures.

| Metric | Keltner Reclaim | Supertrend Momentum |
|---|---:|---:|
| Fresh CLOSED rows | 29 | 27 |
| Net1 summed trade-bps | -3,677.61 | 4,071.98 |
| **Net2 summed trade-bps** | **-4,257.61** | **3,531.98** |
| PF2 | 0.3737 | 1.9409 |
| WR2 | 20.69% | 37.04% |
| Exit-sorted losing streak | 7 | 5 |
| Exit-cohort realized DD2 trade-bps | 5,742.34 | 2,782.51 |
| Net2 excluding largest 2 winners | -6,040.04 | -628.26 |

**Supertrend concentration:** top2 winner Net2 sums to 4,160.23 trade-bps; they contribute 57.10% of positive trade profit. After removing only those winning rows, the remaining trades are negative. September Net2 4,734.48; October Net2 -1,202.50. Large-winner dependence remains a fragile edge, no robust G5 PASS.

**Keltner future loss:** September Net2 -1,103.89; October Net2 -3,153.73. Both negative, so old positive used-DEV Keltner 126T does not certify current prospective profit.

## Duplicate opportunity and shared-risk evidence
- Overlapping cross-strategy model trade pairs: **94**; same-symbol overlapping pairs: **15**.
- Exact same (symbol, side, signal_ts, entry_ts, exit_ts) cross-strategy signatures: **7**.
- Peak simultaneous Keltner+Supertrend modeled positions: **10**. Actual account capital, margin, NAV and MTM drawdown cannot be inferred.
- Identical modeled trades and shared exposure MUST NOT be counted as independent alpha opportunities. Portfolio-level risk status remains HOLD.

## Terminal disposition
- `HOLD_INTEGRITY_AND_WINNER_CONCENTRATION`. No new product-grade strategy; no formal G5A/G5B credit.
- Existing G5 status reports `PENDING_LANE_LOCAL_ACCOUNTANT` for both. This helper independently validates saved closed-row arithmetic/time/duplication and static cross-sleeve overlap, **not** actual tick fills, original receipt arrival at signal, fee/funding rows or account NAV.
- Existing A one-shot Squeeze costed FULL was not observed in the most recent authorized workflow-dispatch history; previous PAT request failed with 403. Do not bypass permission using other services or force a second economic owner.
- Existing D HGL1 input remains HOLD (F validated old 240h source, still no input manifest SHA/immutable prospective snapshot); do not re-label historical data as fresh.
- Operating-risk limitation: last verified VPS disk general available ~1.4GB with bloated active syslog. Log history and ongoing collectors were preserved; no further log deletion or research-copy operation in this audit.
- Next: A should conclude the existing approved Squeeze economic run through its authorized route; existing G5 owner should bind complete actual fee/funding/as-of and shared capital risk for Supertrend without inventing missing observations. B/D keep HGL1 blocked until source binding is legitimate.
