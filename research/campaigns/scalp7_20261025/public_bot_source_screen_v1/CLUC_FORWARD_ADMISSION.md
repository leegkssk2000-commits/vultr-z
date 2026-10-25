# ClucMay72018 5m — actual source-clock admission (2026-10-25)

**Decision: HOLD_CURRENT_PUBLIC_COLLECTOR_CANNOT_PROVE_NATIVE_NEXT_OPEN.** Do not launch a 5m economic Shadow fill from this collector. This is an execution-input HOLD, **not** proof that the original strategy has negative expected value on a future timely feed.

- Exact published native strategy and GPL-3 original source are already frozen in PR #1475; unchanged here. The earlier 60-day historical *used* screen gave Cluc 27 completed model trades, Net40 +401.15 summed trade-bps / PF 1.410, but Net60 -138.85 and excluding DOGE Net40 -18.85. Those results are not account NAV.
- Independent clock audit period **[2026-10-25 03:00, 21:00) UTC**, fixed 18 hours, 6 BingX symbols, 1,080 source minutes per symbol / 216 completed five-minute signal bars per symbol, 1,296 total, actual immutable HTTP receipts and normalized source SHA verified.
- CLUC_FORWARD_CLOCK_AUDIT.json stores exact source identity, live cursor snapshot SHA at inspection, and selected per-symbol receipt+payload chain SHA. No 1m gap, no synthetic-fill source, no missing/invalid volume. volume_units=UNKNOWN is preserved, not relabeled. A within-symbol relative volume condition still needs a verified stable volume scale before formal admissibility.
- **All bars were first available after their 5m close:** exact original next-candle open fill was not observable; 968/1,296 (74.691%) were only available at or after the following full 5m candle closed. Per-symbol median latency BTC 4.046m, ETH 5.276m, SOL 6.662m, XRP 7.934m, DOGE 10.364m, LINK 9.205m.
- Native source stop is **-5% price**, not automatically admissible at leverage 10x/15x/20x; no real liquidation, quote, funding, account NAV or slippage proof. Do not convert used model profit into a futures edge.
- No new collector/API, historical backfill, economic FULL, virtual fills, paper/live, signed orders or K117/BbandRsi modifications. The existing public 1m collector is left untouched.

**Owner route:** existing B may assess earlier low-latency as-of evidence without another writer. Existing C should not waste a new 5m model execution until a suitable entry clock and a fixed futures-risk contract exist. Independently sourced >=1h candidates may be checked on the existing source after native rules/stop and distinct alpha ownership are frozen. No new Work.

Reproduce this read-only audit from the existing working tree: python -B audit_cluc_live_clock.py (output hash may change if live CURSOR changes; fixed time-window receipt-chain hashes should not). If source data have changed or are missing, the audit must fail closed rather than fabricate bars.
