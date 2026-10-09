# Issue #1388 — actual source witness, route decision, storage repair

Owner: `CLOUD_WORK_COORDINATOR_ISSUE1358_V1`. Issue body/latest five comments (then the new6088722645 completion comment) and the entire [#6087084175](https://github.com/leegkssk2000-commits/vultr-z/issues/1388#issuecomment-6087084175) were read. This receipt resumes that exact unfinished data task; it does not reopen failed BingX recovery or reclassify saved economic failures.

| First report | Actual outcome |
|---|---|
| Source verification | **PASS** for the archived reported `23:59` row chain, all six 365-day calendars and cutoff-attached 361-day suffixes. **HOLD** for exact historical `time` open/close semantics and historical delivery/fill authority. |
| New READY / identities / Children | **0 / 0 / 0** |
| New economic evaluation | **NOT_RUN**; density / cost1x / cost2x / FULL / robustness executions all0 |
| Actual new Net/T · PF · DD | **NOT_RUN · NOT_RUN · NOT_RUN**; not zero-valued profit statistics |
| Next single action | Obtain the original immutable `trade-executor` engine revision and bind `native_stop_cycle_transition_order(t)` for the already examined BTC15m ATR source. If unavailable, reject that source-exact route rather than replay or repeat source lists. |

## Actual VPS archive result

[Run37985782945](https://github.com/leegkssk2000-commits/vultr-z/actions/runs/37985782945) executed one authenticated read-only audit using existing VPS secrets and the previously observed pinned SSH host key. Source script7344917… ran via Python stdin; remote writes, new BingX requests, source backfill and market replays were all0. The actual JSON output, transport and executed script/test copies are saved in `verification/source_witness/`.

| Symbol | Direct reported23:59 rows | Last consecutive suffix | Missing terminal days | Preserved missing1m |
|---|---:|---:|---:|---:|
| BTC-USDT |365|361|0|4|
| ETH-USDT |365|361|0|4|
| SOL-USDT |365|361|0|4|
| XRP-USDT |365|361|0|4|
| LINK-USDT |365|361|0|4|
| DOGE-USDT |365|361|0|4|

Full calendar: **2025-09-15…2026-09-14**. Last361-day suffix: **2025-09-19…2026-09-14**. Fixed exclusive cutoff: **2026-09-15T00:00:00Z**. Each symbol has525,596 actual1m rows; all six total3,153,576. Missing rows remain exactly **2026-02-13T20:32…20:35UTC**, four per symbol. That day's terminal23:59 row is directly present. No synthetic candle or daily OHLC was manufactured.

The original `canonical_12m` stopped at the gap; the complete witness necessarily binds its existing `canonical_gapday_prefix` and `canonical_postgap_20260213` siblings. Manifest hashes, request receipts, raw response bytes, normalized chunks and daily1m files were compared, not inferred from a headline365-day summary. The pinned17,541-file inventory hash matched **53c64616fa98ddd446533cbc7b8e90eb2866ce9b1b0b3243df4211d59f155ba2**. Two extra FREEZE files were bound separately. Before/after metadata and second-byte digests matched for17,543 files,435,791,589 bytes per pass.

| Durable proof | SHA256 / identifier |
|---|---|
| Artifact |11642369676, uploaded2026-10-09T20:17:55Z,815,432bytes |
| Artifact ZIP |`8381a019d4a2365b3a2b32e8fc3ee2b6817196cf7859a014ad9d358a0770dc34` |
| Actual source JSON |`aee222461ded371847b6ab037febcbf9abd2cc36ca14f9e4d28a6831e4ce2221` |
| Receipt selfhash |`0c4c66b93204403f66fb6f73d0de943b50e4611a1b03a740f87b304c362e47b8` |

Independent downloaded-receipt review passed **80 checks**, including all2,190 day rows,19,710 provenance hashes and6,570 clock integers. It recomputed each361-day calendar hash and receipt selfhash. It did not issue a second VPS audit or independently fetch underlying minute files again; those checks were performed by the actual archived audit. See `INDEPENDENT_SOURCE_RECEIPT_REVIEW.json` and `SOURCE_AUDIT_RESULT.json`.

Historical modeled availability is reported terminal time+60s, hence next00:00UTC. **Actual** request, receive and archive-known timestamps are recorded separately for every day; the archive was collected on2026-09-15. Historical realtime delivery latency is **UNOBSERVED**. The raw API mapping exposes only `time`; this task does not certify its open/close meaning from a current documentation example. Successful source-chain state remains `chronology_economic_eligible=false`, `strategy_ready=false`, and `execution_authority=NONE`.

Limits: two sequential read passes are not an atomic filesystem snapshot; collector hash is the fixed manifest declaration rather than an audit of the current runtime collector file; the inventory covers specified close-source files rather than all15/30/60m derivatives; FREEZE hashes are actual bindings without an external fixed expected hash; gap-day full OHLC/volume and intraday fill authority remain absent. These limits do not erase the observed row-count/hash result.

## Exact Donchian source binding and decision

Primary MIT independent implementation: [LineGM/catching_crypto_trends@2a882b79be8fd1c60c2ee49bfc3c4cc83023a353](https://github.com/LineGM/catching_crypto_trends/tree/2a882b79be8fd1c60c2ee49bfc3c4cc83023a353). Seven exact primary Git blobs and file hashes are saved in `DONCHIAN_PRIMARY_SOURCE_SNAPSHOT.json`; complete fixed conditions are in `DONCHIAN_SOURCE_BINDING.json`. This is an independent paper implementation, not original-author code or the experimental Freqtrade adapter.

The original daily-close long/cash model uses horizons5/10/20/30/60/90/150/250/360 days. Current close belongs to its channel. An inactive model enters on `C_t >= U_t`, initializes the midpoint stop, and an active model exits on `C_t <= previous fixed stop`; surviving today's stop is raised only for tomorrow. The nine states combine equally. Annual volatility is sample standard deviation of90 consecutive calendar returns×sqrt365; target25%, cap2x. Aggregate signal-count changes resize immediately; unchanged count resizes only when desired versus drifted current holding differs by **more than20% of current holding**. There is no intraday stop, TP or fixed timeout.

Cost is **10bps each one-way traded notional**, approximately20bps for a complete buy/sell round trip before BingX funding/slippage. It is not10bps RT. Source accounting earns day-t returns with yesterday's holdings, then rebalances at the academic same close. That invariant prevents earning already observed returns; it does not establish an executable post-decision same-close BingX fill.

The source-reported BTC gross CAGR29.75% / Sharpe1.64 / MaxDD18.84%, and partial Freqtrade results quoted in #6087084175, are **source claims**, not economics newly reproduced here. Source-exact BingX Net/T, WR, PF, DD, signal density and an economic trade-ledger hash are not established.

An actual deterministic call to the exact donor `donchian_state` disproved state sufficiency: the same361-day suffix with a previous360-day prefix ends active1, while a cold suffix alone ends active0. The previous stop also differs. See `DONCHIAN_STATE_CARRY_FIXTURE.json`. A361-close feature witness cannot supply inherited active/stop/holding/band state. A365-day cold dataset also leaves only aboutfive fully warmed360-horizon decision days, insufficient for a credible economic assessment.

**No separate1d campaign execution authorization was found.** Current #1388 owner scope permits15m/30m/1h, so daily strategy status stays `DIFFERENT_TIMEFRAME_RESEARCH_ONLY`. No executable identity, owner claim, sealedG4/G5 expansion, cheap run or FULL was created. Spot/cash→BingX perpetual, fixed six-universe→monthly Top-B, native same-close→causal fill, funding/margin and initialization are material translations and may not be silently called original replication.

## Bounded route_change within the permitted timeframe

The daily route cannot become an executable original in current authority. The existing coordinator's newly saved next route remains Donchian1D PRE_SCREEN_THESIS after explicit timeframe/chronology authority; it is preserved. The following route_change is bounded fallback qualification, not a replacement owner claim, accepted READY route or economic activation. We reviewed only already examined alternatives; no new mass strategy search was performed. HV6/Shen native break-even costs3/7/10bps remain below15bps and were not rerun. Hansen1h retains its1202-episode density proof and cancelled-before-economic park; it was not relabelled or reactivated.

The existing BTC15m ATR source is [tradingstrategy-ai/getting-started@0be3392775ffd2567a617153a3c8d42fb0e57476](https://github.com/tradingstrategy-ai/getting-started/tree/0be3392775ffd2567a617153a3c8d42fb0e57476). Its first decisive missing execution field is **`native_stop_cycle_transition_order(t)` bound to the actual immutable engine SHA**: whether a15m trailing-stop change applies before or after the same-boundary5m stop callback, with original trigger/reference/fill chronology.

The pinned project points `trade-executor` to local `../trade-executor`; the lock has version0.3.2, `files=[]` and a directory dependency, without an engine Git commit or distribution hash. Notebook `engine_version="0.5"` is an API compatibility argument. Current upstream cannot establish the original engine. `TP=1.10` is defined but unused and must not be invented as an exit. Daily-regime Enum/availability and original engine license/data/cost gates remain later preflight items. Exact evidence and rejection boundaries are in `ROUTE_CHANGE.json`.

Keltner/HG and Squeeze originals, saved economics, failed ATR/cost filters, one-bar confirmation and repeated same-loss exits were preserved. No new entry-time causal axis was certified; Child0. The current anchors retain their existing concentration limitations: Keltner109T saved Net1x/T54.565bps, PF2.003 and Squeeze25T saved Net1x/T60.820bps, PF1.912 are old development evidence; they are not new results or independent fresh validation. Current-run DD for them is NOT_RUN, not inferred.

## Actual storage blockage, implementation, and test boundary

Initial readback found hourly Work last-run metadata2026-10-09T19:22:28Z and stale OWNER/CHECKPOINT projections dated2026-10-08T17:14:42Z. Final readback found an actual new durable result: coordinator ref advanced by one descendant commit to **bac369926fa79886db6db42dd0f52c3751828075**, adding `ISSUE1388_DAILY_CLOSE_WITNESS_RECONCILIATION_20261009T2024Z.json` (Git blob a90750ea67d3612607bcdeae33014a5ab37e4039). The existing Work independently downloaded/recomputed this exact37985782945 artifact, reran its11 fixtures and recorded **SOURCE_CLOSE_ONLY_INPUT_VERIFIED**, READY0 and economics0. New [comment6088722645](https://github.com/leegkssk2000-commits/vultr-z/issues/1388#issuecomment-6088722645), posted20:28:50Z, was read in full. This is actual result persistence, not inferred from the last wake. Automation metadata now reports last_run20:29:11.862456Z; it remains enabled and was not changed by this task. OWNER/CHECKPOINT projection blobs are byte-identical and still stale; only evidence was appended. Current existing canonical heavy37986165036 is IN_PROGRESS1/1. Root did not acquire/write/reset shared ownership, cancel it or start an evaluator. See `LATEST_OWNER_ACTUAL_COMPLETION_READBACK.json`.

| Existing Actions | Actual outcome / stored result |
|---|---|
| Hansen37810136523 |cheap job cancelled while pending, no economic run or artifact; parked unchanged |
| Exact8 old37866313836 |collection PASS, `HEAD -> master (fetch first)` rejection, persistence FAIL, final upload SKIPPED, artifact0 |
| Exact8 latest37983122615 |collection and six diagnostics completed; same push rejection2026-10-09T20:20:47Z; FAILURE; partial diagnostic artifact11642807025 saved, final receipt/state upload SKIPPED |
| Source37985782945 |actual read-only VPS audit SUCCESS; full source receipt artifact saved and independently verified |
| Final fixture37987321248 |final exact parser/storage bytes CPU-only17 tests SUCCESS; SSH/source-witness SKIPPED; no market run |

The first demonstrated storage failure was a non-fast-forward push after master advanced, not a JSON/economic computation error. The existing Exact8 workflow now keeps the original state blob and generated SHA, performs at mostthree non-force fetch/rebase/push attempts, and retries only unrelated master movement. If another writer changes the same state blob, it stops `HOLD_EXACT8_REMOTE_STATE_CHANGED`; it never overwrites that writer or recomputes economic output. Final receipt/state upload uses `if: always()`.

Regression evidence: **five actual extracted native YAML shell/local-bare-Git executions plus one static final-upload guard** passed. Cases cover unrelated master movement, same-state conflict refusal, push-time race retry, three-race exhaustion, no-op persistence and failure-path artifact configuration. This does not prove a repaired future scheduled run has already persisted, or recover a whole job forcibly killed before upload. Latest old run uses unpatched master and remains FAILURE. The patch changes storage handling only; schedules, source rules, economics, activation tokens and global-heavy ownership are unchanged.

Final local source/storage/old-collector targeted pytest: **39 PASS** in1.55s using the existing project venv. Stdlib targeted tests17 PASS. Frontend pre/post validate, py_compile, YAML/gate checks and diff checks PASS. Initial default runtime lacked pytest; an overly broad unittest discovery imported unrelated pytest modules and failed import. The existing venv resolved the test dependency; no code failures from that attempt are disguised as PASS. Actual final [CPU CI37987321248](https://github.com/leegkssk2000-commits/vultr-z/actions/runs/37987321248) passed11 source fixtures+6 storage checks on final codehead `1fa06df2d7bb9ba267a5d7fc91415a1faa14c733`. The actual archived VPS source audit used the earlier7344917… script; final c19584… adds bounded malformed-number parsing and was not re-executed against VPS.

Independent integration preflight parsed697 workflows, found19 master-push and22 PR path matches, no unskippable PR-family triggers and no workflow_run followers of the proof workflow/Exact8. Explicit final-head and merge-commit `[skip ci]` suppress those event runs, so integration cannot reserve a new global-heavy slot or deploy. Protected=false and rulesets[] were observed; detailed protection API403 was a permission limitation. General legacy PR checks are **SKIPPED/NOT_RUN**, not PASS. The one existing schedule remains enabled; no schedule creation, modification, dispatch, cancellation or economic retry was performed.

**Actual integration complete:** [PR1425](https://github.com/leegkssk2000-commits/vultr-z/pull/1425) merged2026-10-09T20:38:13Z as **588d6935dbd04ab45f18e5cf23bed2b9386c8ead**. Master tree exactly matched the locally verified code/report tree **a60095e492a75075ed0522f04af53759dc84fbb9**; all28 changed paths were the five scoped implementation files and23 saved source/review reports. Existing source/economic ledgers and owner files were unchanged. Merge-head Actions readback returned0 runs, and owner ref remainedbac369926…. Storage fix is now in master; the next existing scheduled workflow has **not yet** proved real persistence using it. Final integration receipt and this updated status are an append-only saved proof on the same research branch; no second economic owner or run.

Changed implementation files: `ops/issue1388_canonical_daily_close_audit_v1.py`, its11-fixture test, the one-shot readonly/CPU-only proof workflow, the existing Exact8 workflow storage step, and its6-fixture regression test. This report/source receipts are repository artifacts, not new framework or paid research services. **Deploy should not run.** Rollback concerns are confined to storage retries and these research-only files; reverting must not remove or reset existing economic ledgers, source archives or shared claims.
