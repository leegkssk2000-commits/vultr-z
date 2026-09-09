# Historical volume lineage audit

The exact original collector is recovered and its SHA256 matches the canonical manifest. It does **not** retain original OHLCV response bodies or the object-versus-array row schema. The current evidence therefore does not establish base-asset or fixed-contract volume for T1/F1/F0. This finding concerns the original acquisition path; separate artifact inspection may still supply a missing retained response.

| Link | Verified evidence | Consequence |
|---|---|---|
| Canonical archive | `6d6335d1c9ad7ecb1e9597da85c2eb87635561e1`; manifest SHA256 `17ab80c4101eefab5e0e13f43cca74010b1c1c8283c845e9399028516295c898` | Original seven-symbol requests and normalized file hashes are pinned. |
| Original collector | Commit `9808bebcc21e45658bea6768f1008d0fcd9841b0`, blob `3da90012bbd18c31299ccbdfa89f002a40107b3e`; SHA256 `eee9bf137fce2503e0d3eb1f361b17f8e74920443753d8bcb5e5d840418983f0` | Matches `collection_code_sha256`, including the implementation that actually acquired the dataset. |
| Source adapter | SHA256 `5a10ee08ed71780140b23ef0e9de5c621340413dab0ea455b7689d137eff953d` | Matches `source_adapter_sha256`; maps object `volume`/`vol` or array element5 into the same float field. |
| Page receipts | 68 pages; only request, received_ms, payload_sha256, decoded_rows | Receipt hashes identify a payload if recovered; they do not reveal which decoder branch ran. |
| Stored `raw_ohlcv` | `collect_symbol` decodes, sorts and deduplicates before `acquire` writes these rows | The word raw denotes history before common-calendar slicing, not an unmodified exchange response. |
| Stored `ohlcv` | Date-filtered normalized `raw_ohlcv` | Does not recover discarded row schema, quote volume, or unit metadata. |
| Cost capture | Separate hook around `costs.request_json` after OHLCV collection | Preserved cost responses are not historical klines response evidence. |
| Prior T/F packets | Both compressed packet byte hashes match the PR1229 frozen specification | Input preservation is verified; units remain a separate missing fact. |

The first manifest commit is `0328e6074366252387e17cf36b34439ca7db3cb1`, produced by acquisition run **33967876652**. The exact archived collector writes no klines-response sidecar. Its console output exposes summary/gap metadata, not raw klines payloads. The JSON companion records all 68 original request/payload hashes and canonical tree paths for bounded artifact matching.

To admit the frozen T/F lanes, recover existing original klines payload/schema evidence tied to those receipt hashes, covering the seven symbols and both USED prefixes, then bind explicit base or fixed-contract units to the actual field. The prior official excerpt labels array element5; it does not show that these historical payloads used arrays or explicitly establish object `volume`/`vol` semantics. Numeric magnitude, prior RVOL use and local variable names cannot replace that evidence.

No market request, economic execution, candidate allocation or budget reservation was made. No price rows were decoded in this audit, and no OOS rows were read. Prior M1/R1 outcomes and all frozen strategy, input and cost artifacts remain unchanged.
