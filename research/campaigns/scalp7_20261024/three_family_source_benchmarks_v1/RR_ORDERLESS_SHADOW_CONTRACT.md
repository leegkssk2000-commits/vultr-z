# Three frozen-strategy RR quote-mark observer (development-only)

This is one **independent observational sidecar**, NOT a modification to
K117/GMMA/TSMOM parent rules or an order, simulated perfect-next-open fill,
true NAV PnL, formal Paper/Live/G4/G5, or optimization success.

- Only recognizes *new future signal decisions after sidecar start* from the
  existing native K117 30m and GMMA/TSMOM 4h observers. One hypothetical
  observational sleeve per symbol; duplicates denied.
- Only pre-existing BingX **BTC/ETH** WebSocket quote ledger is approved for
  current BBO price marks. SOL/XRP remain source-HOLD; no new collector/API.
- Entry mark is the first verified **post-native-decision ask** within 120s,
  not native next-open; native stop/ATR-distance reference is frozen.
  Bad/incomplete/crossed or stale quote => no entry.
- Reference cost 40bp roundtrip, initial risk 1R at actual observed ask, no
  hard TP. At an observed 2R quote, prepare +0.5R stop floor that **only
  becomes active on the next distinct quote**. Native original strategy
  remains untouched. Observation at next quote never reconstructs hidden
  price path between quotes or actual matching engine fills.
- Deferred exits mark only a *sampled bid-touch* or finite native 24/48 4h
  (TSMOM/GMMA) or K117 50x30m time cap; native strategic exit parity is
  explicitly false. No claim of an optimum, G5 credit or market execution.
- Crash/restart loads the original status under exclusive lock. After a
  30-second or larger monitoring interruption, previously open marks are
  **censored** instead of inventing an intragap stop or close.
- Start default-OFF with explicit `--enable-observational-rr-only`, supervised
  via its own no-order unit, and single read-only source ledger.
- Price-series/funding/slippage and account risk are not verified, so
  `real_broker_fills=0`, `order_calls=0`, `formal_shadow=false` throughout.

Prior used-DEV 4h trade net-R can help set up negative controls; selecting
2R/+0.5R *because of hindsight* is not a robust economic parameter
optimization. It is a single preregistered **prospective-only axis** that
must be compared with the untouched native parent on genuinely new quotes.
