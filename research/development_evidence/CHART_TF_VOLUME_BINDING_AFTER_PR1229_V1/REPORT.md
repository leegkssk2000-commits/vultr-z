# T1/F1/F0 historical volume binding — NOT_RUN

The source condition was not met. No new candidate, reservation or economic evaluation occurred. PR1229 and subsequent master history remain preserved.

## Actual economic status

C54 figures below are reused saved USED_DEV results, not new replays. Net and cost2 include hypothetical marks on unfinished positions. Units are equal-notional trade-bps, not account returns.

|Period|Rule|Closed/open|WR %|Total net|Cost2 total|Daily marked DD|Avoided losses / missed wins|
|---|---|---:|---:|---:|---:|---:|---|
|DEV2025|C54 saved|191/0|43.46|13666.60|9445.52|10452.80|Reference only|
|DEV2025|T1|NOT_RUN|—|—|—|—|NOT_MEASURED|
|DEV2025|F1|NOT_RUN|—|—|—|—|NOT_MEASURED|
|DEV2025|F0|NOT_RUN|—|—|—|—|NOT_MEASURED|
|SEEN2026|C54 saved|69/2|37.68|7198.71|5634.99|3997.48|Reference only|
|SEEN2026|T1|NOT_RUN|—|—|—|—|NOT_MEASURED|
|SEEN2026|F1|NOT_RUN|—|—|—|—|NOT_MEASURED|
|SEEN2026|F0|NOT_RUN|—|—|—|—|NOT_MEASURED|

## Newly established historical evidence

- Exact acquisition run33967876652, source commit9808bebcc21e45658bea6768f1008d0fcd9841b0 and collector SHA256eee9bf137fce2503e0d3eb1f361b17f8e74920443753d8bcb5e5d840418983f0 match the canonical manifest. Adapter SHA also matches.
- All68 page receipts contain request, received time, payload hash and decoded row count. The collector normalizes before returning and writes normalized rows under raw_ohlcv; it does not retain lossless klines response bodies. Cost payloads belong to separate endpoints.
- Original artifact9970019637 was retrieved in same-repository read-only CI34314937337/job102349074186. Its28members match the original committed path set, byte counts and Git blobs exactly; canonical manifest SHA also matches. There are no extra body/schema files. Price values were never decoded in this artifact inspection.
- The previous local transfer403 is preserved in ARTIFACT_AUDIT; it is not the reason for the final NOT_RUN. Actual retained archive inspection now confirms the output set.

## Exact missing links

1. Original klines response body or lossless schema receipt linked to the preserved page payload_sha256; normalized raw_ohlcv does not retain object-versus-array identity or discarded fields.
2. Independent base-asset/fixed-contract unit authority for the actual historical field, symbol and any conversion, linked to those preserved responses; current array-only documentation cannot supply historical object-volume evidence.

No current public documentation was re-fetched to infer historical object volume. A payload digest verifies bytes if those bytes exist; it cannot recover discarded schema or unit meaning. A normalized field named volume is not a unit attestation.

## Preservation, allocation and closure

M1 remains profitable in both stored windows (+4130.89/+11492.23 total net) but retains its original joint-goal rejection. R1 retains its original failure and the recorded3-trade2026 limitation. No old decision, C54 rule, pivot, Fib interval, entry/exit, input or cost was changed.

The conditional6FULL slots refer to the same6unused T/F slots from PR1229. There is no additional parallel allocation, no reservation and no new candidate/evaluation number. Cumulative59/98 remains unchanged. No C54/M1/R1 replay, FIXED replay, sweep, market collection, unusedOOS read, paidAI, order or deployment.

All conditional economics are NOT_RUN and source-blocked. Scope ends CHECKPOINTED / REPORT_ONLY with no automatic retry. Required CI/review/merge/exact-merge preservation verification is recorded in PR1230. Rollback must preserve all prior attempt/result/budget evidence.
