# K.P committed snapshot: observed cause and metadata-only repair

## Scope and authorization
The user requested continuation of the GitHub-based snapshot/census investigation after PR1353, not another Work handoff. Earlier authorization for operational GitHub work and limited metadata reads remains applicable. No new FULL, collection, trading, parent tuning, runtime replacement, live authority, or other lane work is performed. Existing guards and pinned strategy/source files are unchanged.

## First real-host result
Source head e76c75f6b576cddf03e37b1424e327951e52f6c2. Dedicated run37165979400/job111328820995 SUCCESS; artifact11289642394 ZIP SHA256 9b1b46f3efffd1fa50d685cce6c5340d1c1129abacfbf9620a971525a7ee23ac. Archive, expanded JSON transfer SHA and all7 exported code hashes verified locally.

Captured2026-10-04T00:47:00.127Z. Verified75821 committed receipt-metadata files against their original cursor hashes, source/symbol/window/clock and row/gap accounting. Elapsed31.199206s includes a deliberate20s observation interval. During this read DOGE appended1 receipt: all captured prefixes stayed equal, while the overall CURSOR bytes changed. The appended suffix was excluded from the snapshot; no collector was stopped.

| Symbol | Captured receipts | Receipt-reported1m rows | Exclusive coverage end UTC | Explicit missing minutes in receipts |
|---|---:|---:|---|---:|
|BTC-USDT|12640|26275|2026-10-04T00:43:00Z|0|
|ETH-USDT|12640|26275|2026-10-04T00:43:00Z|0|
|SOL-USDT|12639|26275|2026-10-04T00:43:00Z|0|
|XRP-USDT|12637|26275|2026-10-04T00:43:00Z|0|
|LINK-USDT|12634|26275|2026-10-04T00:43:00Z|0|
|DOGE-USDT|12631|26271|2026-10-04T00:39:00Z|0|

All begin2026-09-15T18:48:00Z; receipt-reported total157646rows. These are source metadata counts, NOT inspected/validated candle bodies, trades or fresh economic credit. Source identity a5c2d7d6888b1cbf5e5c851c66b11127736fda94fd58f0484e19381c7e1efca9. Volume units remain UNKNOWN. No claim of complete original input or unused OOS.

## Why the producer can stay alive without advancing
`scalp7_fresh_forward_v2.build_current_frames` captures CURSOR bytes, calls `load_observed_minutes`, then compares the *entire* live cursor again. `load_observed_minutes` rereads the cursor and revalidates all prior raw/normalized payloads. Even a valid append after the captured cutoff triggers SOURCE_SNAPSHOT_CHANGED_RETRY_WITHOUT_ADVANCING. The collector atomically publishes CURSOR after each new immutable receipt. Growing history increases reader work while the collector continues to append.

A CI regression invokes the exact frozen `build_current_frames` with an append-only loader callback and reproduces that exact exception. The actual server exhibited precisely the append-only condition while retaining every old reference. Deployed hashes of fresh_source, fresh_forward, observed_paper_v3 and the frozen K.P parent match the reviewed checkout. Thus append-only publications are a confirmed rejected condition, not speculation that the server is down.

ObservedPaper calls the same frame builder (including a second refresh after quotes), catches this exception and deliberately commits no state/cursor advancement. Current STATUS in both paths still names that retry. The K.P evaluation timestamp inside STATE is2026-09-18T18:32:45.238Z; paper's stored last_poll is2026-09-16T17:13:36.493Z. Before/after STATE byte hashes match. This does not establish that every intervening attempt failed, nor does it rule out downstream blockers after fixing this one.

## What the new implementation fixes — and does not
The new standalone utility pins one cursor snapshot and follows only its hash-verified committed receipt metadata. Later suffix append is allowed only when all old symbol prefixes remain identical. Shrink/reorder/prefix rewrites, changed identity/receipt bytes, unsafe paths, invalid clocks and accounting mismatches reject. No latest-cursor reread is substituted into captured input. Path traversal is anchored with directory descriptors and O_NOFOLLOW all the way from filesystem root.

It fixes this concurrency failure **for metadata acquisition**. It is not wired into either live frozen consumer, does not load price bodies or validate their hashes, and is not a market replay engine. The actual producer/paper loops therefore remain blocked, rather than being silently repinned/restarted. The receipt projections contain original receipt hashes and selected metadata, not full copies of every original receipt's bytes.

Review P2 identified that the first probe's path-based mtime could race an atomic replacement after reading its bytes. The revised read API returns metadata from the same open file descriptor and the probe uses that identity. An atomic-replacement regression verifies old bytes cannot inherit the new inode's mtime. Earlier raw-byte hashes and in-file clocks remain preserved; the final-source observation must verify the amended metadata binding separately.

## Verification and resumption
Local metadata-only cases23 PASS. Dedicated CI additionally tests the exact old frame builder (expected total24); final exact-head result is recorded in the PR closeout, not inherited from predecessor21-case CI. Canonical precheck/postcheck and actual SSH source checks are in the workflow. No test count represents economic trades.

Next concrete engineering step is a separately versioned K.P market-input adapter that consumes a pinned committed snapshot, verifies the recorded raw/normalized bodies, and preserves original receipt/usable times, source identity, overlap/gap checks and initial risk/cost semantics. Its binding and complete source-use history must be resolved before G5A unused OOS execution. Do not hot-edit shared frozen files, weaken the snapshot check, stop the collector to force a quiet window, clear state/locks, or backdate missed decisions into fresh trades.

Historical/failed input reads are not proof that later data is unused. Current full candidate census and source-use history are still incomplete; G5A shortlist/G5B/G6/LIVE remain unapproved. Old119 arithmetic and admission/lock work are not repeated. The next owner uses this working GitHub route, not a user-operated SSH handoff.

Deployment: NOT_REQUIRED/DO_NOT_RUN. Rollback only these additive helper/probe/test/workflow/report files; preserve all archived observations and old runtime evidence. Service changes0, raw-price bodies opened0, strategy invocations0, newFULL0.
