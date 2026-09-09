# Original acquisition artifact audit

The original collection was run **33967876652**, job **101311083465**, at source commit `9808bebcc21e45658bea6768f1008d0fcd9841b0`. The first committed dataset is `0328e6074366252387e17cf36b34439ca7db3cb1`, inherited by the canonical ref.

Artifact **9970019637** (`g5a-stage-development-33967876652`) is available and unexpired: **2,174,304 bytes**, uploaded SHA256 `86a948834b0510abc53021301b3fc43fef05d062cf1f01afb6755bb4bdc2651b`. The connector returned a downloadable file reference, but local ZIP retrieval returned **HTTP 403 / Cloudflare error 1010**. No claim is made that the ZIP was opened or that an unavailable artifact does not exist.

The original acquisition source hashes to `eee9bf137fce2503e0d3eb1f361b17f8e74920443753d8bcb5e5d840418983f0`, exactly the collection code pinned by the manifest. Its historical collection path stores **68 page hashes**, then discards the original page bodies and writes decoded rows under `raw_ohlcv`. The original committed data inventory contains **28 files**, matching the Actions upload count: seven normalized raw histories, seven normalized common-calendar histories, seven cost files, one manifest, one gap audit and five native-epoch files. Neither that inventory nor decoded job logs provides historical kline object-volume semantics. The native epoch and cost files describe separate endpoints and cannot establish historical candle volume units. Their market payloads were not opened in this audit.

The manifest SHA256 remains `17ab80c4101eefab5e0e13f43cca74010b1c1c8283c845e9399028516295c898`. Full page/file inventory and the exact log evidence are in `ARTIFACT_AUDIT.json`.

The remaining links are (1) an original historical kline body/schema bound to its canonical page hash, and (2) explicit base or fixed-contract authority for its exact field and symbol conversion. A positive normalized volume, the decoder's field name, or present-day array documentation does not close those links. This audit provides **no admission for T1/F1/F0**. Economic executions, new market requests and unused-OOS payload reads are all **0**.
