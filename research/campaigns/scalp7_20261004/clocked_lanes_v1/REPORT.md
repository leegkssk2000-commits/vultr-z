# PR1356 — Squeeze parent/BE1R actual recorded-price comparison

## Economic result and decision

The two pre-existing Squeeze30m identities each ran ONCE, using the already verified six-symbol input. One shared frame build, not two data acquisitions. Each produced15 signals:5 ATR/cost rejects,1 occupied-position reject,9 completed trades,0 unresolved. These are9 common opportunities in two parallel research models, NOT18 independent trades.

| Metric | Parent1x | BE1R1x | Parent2x | BE1R2x |
|---|---:|---:|---:|---:|
| Completed T |9|9|9|9|
| WR pct |22.222222|22.222222|22.222222|22.222222|
| Gross trade-bps |-572.422830|-572.422830|-572.422830|-572.422830|
| Cost trade-bps |139.877057|139.877057|279.754114|279.754114|
| Net trade-bps |-712.299887|-712.299887|-852.176945|-852.176945|
| Net bps/T |-79.144432|-79.144432|-94.686327|-94.686327|
| PF |0.254166|0.254166|0.199400|0.199400|
| Realized trade-sum DD bps |869.533824|869.533824|994.164448|994.164448|
| Max loss streak |5|5|5|5|

Fixed interval2026-09-15T20:00Z–2026-10-04T00:55Z exclusive,18.204861days; six-symbol aggregate0.494373T/day per model. 1x/2x differ ONLY in the charge applied to the same completed trades, not leverage or a new execution. Trade-bps sums and realized DD are not account percentage return/DD, and no margin/liquidation/NAV or actual funding settlement is certified.

**Decision:** this sample is negative BEFORE costs as well as after them. BE1R provides zero observed realized improvement; do not adopt it on these results. This fixed development comparison is CLOSED. Do not tune the same window until it looks positive. Nine common trades cannot establish universal strategy failure, nor justify promotion or formal G5 rejection. Preserve both old and current evidence.

## Why identical outcomes are not a missing BE callback

The parent produced52 management events, all without a next_stop update. BE1R produced52 events,6 with next_stop, all on ONE XRP trade; that trade still exited at the same price/time as the parent. All9 common entries and realized outcomes match: improved0, harmed0, unique parent0, unique child0; Net delta0bps at both cost scenarios. The mechanism did run; it simply did not alter realized exits in this sample.

All7 losing trades had recorded received-prefix MFE below1R at their last management observation (largest0.509134R). This is the adapter's declared observed-prefix diagnostic, NOT proof of the complete intraminute path. Eight trades exited on the native two-weak-momentum condition; one DOGE trade reached max-hold and lost523.109068trade-bps net1x. That loss is retained, not deleted by post-outcome symbol selection. These findings do not prove an earlier scratch, narrower stop or entry veto would improve a full new comparison.

## Execution, provenance and durable recovery

Reviewed source91a51098c401bae59ffe7e8a921d7b42586d92c3 passed24/24 PR workflows and final automated review5983393003 before activation. Separate approval commitd48484f7e91abc974935db52bd9454d9bcc71f29 binds source and contract. Activation61f0c75aa5ea80ad8596d666aa63a418a9af05e4 added ONLY RUN_GITHUB.json.

Actions run37227273218, attempt1, economic job111509492201 SUCCEEDED. Permanent claim09aa18f8e4b39bee4b51524bf1b4d9fc336614cd was created before signals; parent STARTED19:11:58.076308Z, child STARTED19:11:58.227095Z on2026-10-04. Artifact11312690449 ZIP SHA25639d3bc86d74cd1f6098ec4655585f0a3fbf7571e33f70b404cd42290c6a378ac was downloaded and verified. Full original result JSON, including signals/trades/events/start/completion/reservation, is preserved in committed RESULT_BUNDLE.json.xz. Original data input3da2f940 and contractd733d9c7 match; all exported executed sources were compared byte-for-byte with the reviewed source. No second execution was used for verification.

An independent stdlib SAVED_AUDIT recomputes trade gross/net, cost1x/2x, WR/PF/expectancy, simultaneous-outcome-netted realized DD, loss streak, basic entry/event chronology, signal accounting, result/completion hashes, and paired outcome attribution. All18 model rows reconcile. It does NOT regenerate signals or rerun economic paths, and is not a second independent exchange fill engine. The committed bundle survives Actions artifact expiry; full original price input/source transport remains in the90-day execution artifact, not claimed permanently stored in Git.

The old local owner was explicitly retired, NOT recreated. Its volume/process state could not be independently recovered; author receipts reported0 economics and no registered RUN.json existed. This limitation is recorded in OWNER_TRANSFER. A contradictory legacy execution must invalidate the total-two accounting. Git refs are protocol-immutable, not protected against a trusted repo administrator deliberately rewriting them.

## Repairs completed without changing native strategy rules

P1 output-before-claim is integrated: an existing/unwritable output cannot consume the claim, and post-claim errors preserve the original exception and do not reset the batch. A separate GitHub approval publication now prevents an activation from authorizing its own changed source/contract. Current economic driver uses a permanent atomic per-batch Git ref instead of a missing chat-session OWNER_ID. Original local contract, source pins, fit, costs, window and native strategy lifecycle remain preserved.

The earlier stale PR-base measurement-check failure is retained. It was resolved by normal integration of already published automated master telemetry, not by changing guards/allowlists. Preexecution47 generated regressions passed locally and in exact-source CI. Publication adds saved-only audit tests; final source CI/review/merge must be recorded separately, not inherited.

## What remains and what this closure does not do

The receipt-clocked research entry occurs strictly after recorded six-symbol causal price availability. Historical seed/config readiness, future-minute-open fill, minute OHLC stop path and acknowledgment remain model assumptions. The entire interval was used previously and is consumed development history, NOT untouched OOS/fresh or exchange-verified trading. No G5A shortlist/G5B terminal/G6/Core/LIVE is opened.

The old server consumers are NOT deployed/restarted by this work. The reusable price transport and the single-asset/no-partial/no-target clocked model exist; pair/microstructure/other order profiles are not silently treated as supported. Further candidate selection must use existing roadmap/current eligibility, not force adoption of Squeeze or wait for Keltner to be rescued. Any new economic batch needs its own bounded contract/usage accounting; this spent batch is not reused.

No new tuning candidate, Keltner replay, data collection, service change, deployment or real order. Next outcome is candidate selection or separately authorized genuinely unused/prospective verification, not another reproduction of these9 trades. Rollback only this PR's added files while preserving contract, claim and economic result evidence. Deployment: DO_NOT_RUN.
