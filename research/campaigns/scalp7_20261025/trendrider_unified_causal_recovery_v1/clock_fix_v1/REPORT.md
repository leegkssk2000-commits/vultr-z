# Unified TrendRider — 24h exit + closed-clock correction (2026-10-25)

**Minimal defect repair, not new strategy research.** No parameter/tp/sl changes; original frozen historical `RESULT.json`, `ROBUSTNESS.json`, `TRACES.json.gz` preserved untouched in parent directory.

### Exactly repaired
- SHORT expiry mistakenly iterated **25** hourly bars while contract said **24**. Limit 24 candles; if not stopped, close at completed 24th candle. Old S4 over-24h shorts = **15**, corrected **0**. Original S3 also 15 -> 0.
- Entry loss-streak circuit mistakenly added **+1 extra hour** to an already-effective close timestamp. Now requires `end_ms < candidate_entry_ts` with strict completed-before-entry, applying 36h/6h from actual effective end exactly once; same-timestamp closes are not leaked.
- Source snapshot fetched at 08:01:20Z while 08:00-09:00 1h candle was unfinished. Last confirmed closed candle OPEN is 07:00Z; the unclosed 08:00 candle is not credited. All original candidate native saved exit-hours in this bounded test passed source completion.

### Exact single chronological replay, same 267 saved union opportunities, original risk/fees
| Variable | Preserved earlier S4 | Corrected S4 |
|---|---:|---:|
| Admitted opportunities | 121 | 119 |
| Net2 summed modeled trade-bps | +1752.48 | +497.66 |
| PF2 | 1.2942 | 1.0798 |
| Realized exit-leg DD2 trade-bps | 2225.86 | 2947.86 |
| Max losing opportunity streak | 14 | 14 |
| Short legs | 71 | 69 |
| Loss-streak circuit rejected entries | 24 | 34 |
| October Net2 | +99.92 | -1208.06 |

**Current robustness:** added +20 instrument-bp cost ALL legs -> -755.67bp; +40bp -> -2009.01bp; exclude 1000PEPE full re-sim -> -1688.09bp. This remains **HOLD / NOT ECONOMICALLY ROBUST**. Historical actual signed funding/quote/received-at/complete raw signal stream and native short order fill are UNVERIFIED; no G5, Paper, Live or production authorization.

Failed PR1471 native cost-vs-stop filter remains **REJECTED and unused**; it requires not-known-at-entry realized full-holding costs. It was not retuned or imported by this model.

### Reproduce without API calls, no overwritten original results

```bash
cd research/campaigns/scalp7_20261025/trendrider_unified_causal_recovery_v1
# Create a new empty output directory; point to unchanged original freeze.
mkdir -p /tmp/trendrider-clock-verify-v1
ln -s "$PWD/FREEZE.json" /tmp/trendrider-clock-verify-v1/FREEZE.json
python -B fuse_and_recover.py --root /tmp/trendrider-clock-verify-v1
python -B robustness.py --root /tmp/trendrider-clock-verify-v1
# Compare SHA256 against pins below.
```

16/16 next-open, stop-first, 24h, same-timestamp circuit and unfinished-bar unit tests passed. Results and gzip trade details reproduced **byte-for-byte** under a different Python hash seed, without any source ingestion or order calls.

### Pinned receipts
- Preserved original S4 result SHA256: `e99bbd783908628572a64875f7d019676fa5d686fdc7e7b29fd24cee2d4fab13`
- Pre-existing shared OHLC archive SHA256: `16198ac2a3db7849237028a5f5a0100e2033162a9d93b05ad171273215c9a592`
- Corrected result SHA256: `8f8ab3a5cbc4414d8a0a140124f202b16017c78d1c1c38206b0450b6435540da`
- Corrected stress SHA256: `3f51f869f0f5c811c25fea08bc8f6639c9b8ce1299497e40c00f788489d3b81d`
- Corrected trace SHA256: `1561be794fb2ff263ebc2356760a077e0403745e97c6ffb751e37d7c8999061b`

**Final:** source and clock CODE DEFECTS FIXED; economic validation HOLD. Do not tune previously consumed Sep/Oct returns.
