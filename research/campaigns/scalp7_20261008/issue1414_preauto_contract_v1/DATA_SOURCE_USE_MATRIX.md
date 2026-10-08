# Issue 1414 source-use audit

Read-only audit of saved bytes at `e135b59675c16524a41e61cb8f7f0b8d0a240b18`. No economic replay, API collection or spending, collector restart, schedule, order or deployment.

- Saved 15m/30m receipts describe 35,039/17,519 complete bars per each of the six symbols, two segments and one shared 4-minute gap. The referenced runtime archive and cache are absent here. Historical availability is `BAR_CLOSE_MODEL`, delivery is `UNOBSERVED`, and volume units are `UNKNOWN`. These saved receipts are not locally available OHLC observations.
- Twelve genuine 1m response bodies and receipts verify the 2026-09-15 opening-time and revision witness. This single-date witness does not certify a year of arrival timestamps.
- Twelve cost response bodies match saved raw hashes. The 14.0–16.73065 bps cost snapshot is a pinned scenario; personal fee tier, historical spread/impact and depth quantity units are not certified.
- Later Issue 1388 raw funding exists for all six symbols: 465 unique 8h settlements each over `[1768262400000,1781654400000)`. Raw hashes, timestamp grid, signed rate and positive mark fields were checked. This is retrospective data for that fixed window, not 12-month history or certified account debits.
- Issue 1388 already derives complete 1h bars from two same-segment 30m bars. Scalp7 execution remains 15m/30m; this audit does not take over Issue 1388 or claim new 1h observations.
- A genuine micro wire/receipt/clock sample includes a 1ms native-ahead barrier. It does not provide continuous L2, queue, OFI or quantity/direction authority.
- All 24 native CF/GS candidate paths are absent locally and all 15 production SSOT bindings are null. Actual remote CF/GS authority and the account NAV chain are `[UNSURE]+hold`; remote unavailability is not claimed.
- A saved Keltner research ledger is present and its compressed byte hash matches the result receipt. It may support retrospective mechanism audit; model trade-bps are not actual account NAV or fresh evidence.
- Five cached videos retain historically verified 2026-07-31 view snapshots; three topical seeds have unknown views. Direct video, transcript and timecoded source-exact rules were not verified in this audit. Creator claims remain hypotheses.

`DATA_SOURCE_USE_MATRIX.json` separates actual raw SHA256, saved content SHA256 and Git blob SHA1. Its rows specify clocks, units, gaps, purpose, consumer and omissions. This audit alone is not `PREAUTO_CONTRACT_VERIFIED`, a G4/G5 PASS or automation permission.
