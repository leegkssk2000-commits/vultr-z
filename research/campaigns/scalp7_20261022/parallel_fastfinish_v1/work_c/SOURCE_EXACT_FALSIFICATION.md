# Source-exact Supertrend child: falsification result

**결론: `NO_SOURCE_EXACT_CAUSAL_CHILD`.** 정확한 A4 236T parent와 117T volatility subset에 연결된 외부 저자·버전·license 및 완전한 trailing exit 원문 규칙이 없다. 현재 확인한 code/기존 source record에서는 새로운 source-exact one-axis child를 정의할 수 없다. 신규 child 0, rule freeze 0, economic 실행 0이다. A에게 요청하는 다음 결정은 **별도 mechanism replacement 승인 여부**뿐이다.

이 결론은 조사한 immutable parent와 기록에 한정된다. 모든 공개 Supertrend 기법에 완전한 exit가 없다는 주장이 아니다. 기존 source gap을 해결할 수 없는 일반적인 자료를 새로 나열하거나, unknown 값을 임의의 ATR/R 수치로 채우지 않았다.

## 실제 고정 identity

| 항목 | 고정 값 |
|---|---|
| Source context commit | `b73129138e75bdf3fd8ffe58bea87effa2e59f2f` |
| A4 summary Git blob | `97a6bc3d50dfb91ea3d9d3815549327d40dfafad` |
| A4 summary file SHA256 | `1c979597753e5f4a1490632df43295f9e2d49991ca46ec6550de0537e050bd89` |
| A4 summary receipt | `b00e7cc6fcf5439912a5ba3e7eb3ff9c9d2998ad70adb0ac75ec2d6da2faddc1` |
| Parent receipt | `9edb8d722b985af9e6e5f8e77dc560b5473befbaa365e0c61a94838478cfdc9a` |
| Recovered parent file SHA256 | `5018f26c115a89bf69b3d3cccf0f7ccaac42bb3083bb2d3a6cc4360bb1fa9619` |
| Subset candidate | `supertrend_pullback__exact_parent__volatility_regime_owner_only` |
| Candidate SHA256 | `25f5ccd009e33d477a59bfe3f249663e73ad2c3f8d1832d58d283ed9c6066e3d` |
| Subset trade identity SHA256 | `e42711d8843107a94f32019e0a7d1c7492319e812ddf5be377bbdbdac1365e01` |
| Parent policy Git blob | `5212f92a0b181e523c235dc546b64ea2852045e7` |
| Parent config SHA256 | `ac462a17bf7c607cd0d3e97fa37bd33c5cc0672b7a81ecf37bd9e586d91fd2c4` |
| Data/clock identity | BingX swap kline endpoint, **1h**, 12 symbols; parent 236 closed trades; subset 117 |

The receipt's historical boundary is `2026-08-16T18:45:01Z`; its saved source metadata lists 1,000 bars per symbol with open timestamps `1788030000000` through `1791626400000`. That metadata is not the actual candle archive. The A4 `_maps` loader explicitly rejects intervals other than `1h`.

`49.57627118644068%` means **117/236 total-trade retention**. Parent and subset net-positive counts are respectively 64 and 32, so net-winner-count retention is 50%. Neither number establishes preservation of the largest winners. This is not K117/Holy Grail, the separate 87T native-line parent, the 15m authentic-flip identity, or broad-v2 30m architecture. A mutable `*_latest.json` name cannot replace these pins.

## Source → executable lifecycle → first gap

| Record/function | What is actually established | Missing authority or rule |
|---|---|---|
| `evidence_packet_trend_cluster_v1.json`, blob `6e03a2008c92357caac048eca9765e9d0c499e78` | `HIST_R7_SUPERTREND_PULLBACK` points to `r7a4d-strategy11-cause-aware-rotation-l090-v6:backend/strategies/supertrend_pullback.py`; TSMOM is explicitly mechanism-only support. | The exact remote locator was subsequently resolved and its complete file read: commit `1dadb1f6a28662823058a58fdeaa978fcd104b7b`, blob `7941bb1cfb380b01b27cbe196746bfb2b382ab6c`. It supplies entry/add/hold code, not an externally attributed complete exit lifecycle. |
| `trend_policy_batch_v1.py::compute_supertrend_pullback_feature` | The bound internal 1h policy uses Supertrend direction, EMA50 slope, bounded pullback/reclaim, and ATR-based guards. | No external author-native source is bound for a distinct exit child. Parameter defaults are internal parent facts, not a license to invent further thresholds. |
| `trend_policy_batch_v1.py::_build` | Initial SL = signal close ± 1.5×ATR14; TP=None; partial=false; timeout config=48. Trailing contains only `enabled:true` and `type:atr_structure_after_favorable_progress`. | Activation event/level, distance formula, update recurrence and effective timing are absent. The initial stop distance is not a trailing-distance rule. |
| `a1_exact25_generic_evaluator_v2.main → v1.main` | Features use bars through index i; entry uses i+1 open. Actual exit loop checks fixed initial SL, then optional TP, then timeout. | The evaluator has no dynamic trailing-state update. The named intent is not an executable exit contract. |
| Same evaluator exit loop | Stop touch fills at the SL value; no adverse-open gap branch appears in this loop. The timeout scan includes the entry index through `i+1+timeout`; terminal horizon remains open if no stop/TP occurred. | A new trail's stop/gap/queued-exit precedence and completed-bar observation/effective timestamp contract are unbound. Replacing these semantics would itself change the parent. |
| `a1_a5_no_idle_research_v1.json` | Cached A5E1/E2 descriptions support volatility/momentum/regime research axes. | They do not specify this parent’s source-exact trailing lifecycle. Their metadata was reused as cached evidence; full paper text, paid material and video bodies were not newly verified in this Work. |

The declared trail versus actual fixed-stop execution difference is a real static observation. It does **not** identify a uniquely correct missing implementation, show that trailing would improve the saved trades, or establish a stale-state/exit bug. Implementing a plausible trail now would add a new internally selected rule.

`policy_kernel_v1.atr` uses an initial mean seed followed by Wilder recurrence. The parent source can therefore be identified precisely without treating any generic implementation called “Supertrend” as the same strategy. The inspected 15m authentic-flip and 30m broad-v2 paths have different entry/lifecycle responsibilities and cannot silently replace this parent.

## Exact historical source recovered: why it does not complete the exit

The targeted repository lookup resolved `r7a4d-strategy11-cause-aware-rotation-l090-v6` to commit `1dadb1f6a28662823058a58fdeaa978fcd104b7b`. The file `backend/strategies/supertrend_pullback.py` has Git blob `7941bb1cfb380b01b27cbe196746bfb2b382ab6c` and SHA256 `b5398dfce04260422f04a758736d210763dc8c6097eeca953af82a56eb80fe25`. The first gap is therefore **not a missing historical file**.

The complete file's `strategy()` returns only `enter`, `add`, or `hold`. `trail_atr_mult=0.90` is used in `long_sl=min(st−0.35×ATR, EMA−0.90×ATR, low)` and its short-side maximum counterpart, passed as entry/add geometry. There is no retained stop-state ratchet, favorable-progress activation, effective-bar cadence, gap-fill procedure or exit action. The fallback `EXIT_LONG` enum declaration is not an executable exit path. `decide()` maps long enter/add to ENTER_LONG, short enter/add to HOLD because its core is long-only, and other results to HOLD.

Its ATR is a rolling mean, its SL geometry and RR TP differ from the rebuilt parent, and it permits scale-in/dip-add/pyramiding. Its file does not bind native timeframe or completed-bar availability. Importing the whole legacy strategy would change entry, initial risk, TP, state and execution ownership; reinterpreting only the 0.90 field as a completed-bar monotonic trail would invent missing lifecycle semantics. Neither is a source-exact one-axis exit child of the frozen 1h parent.

## Exhausted or incompatible routes

- Fourteen exact-parent subset children were already audited across the existing lanes. This Supertrend parent’s trend-persistence, volatility, liquidity and session subset axes are exhausted. Further exclusion cannot be relabeled a winner-retention exit mechanism.
- `EXIT_TRAILING_ONLY` already ended `TERMINAL_RULE_INCOMPLETE_NO_ECONOMIC_RUN`. The missing fields above remain missing.
- Native prior-bar Supertrend-line trailing has a different **87T** parent, generation **2/2**, terminal `HOLD_SUPERTREND_EXIT_TRAILING_AXIS_EXHAUSTED`, receipt `fc4f712238114720ba2efc1ce7a4bbe17b452cdc853c0e294ed9ec9af09f3ef8`. Reapplying it to 117T would repeat an exhausted axis on a different identity.
- Broad-v2/donor-native reconstruction labels 1.0R activation and 1.8 ATR distance `IMPLEMENTATION_TRANSLATION_NOT_PUBLIC_DONOR_PARAMETER`; its parent entry/exit/intent/lifecycle reuse flags are all false. Its 30m architecture also explicitly separates its control from the legacy 1h scoreboard. These values do not repair the absent author rule.

One targeted repository lookup followed the exact HIST_R7 locator. The historical file was recovered and read in full; no broad web search was performed. No external performance claim is used as a local result.

## Separate data limitation

The recovered packet supplies the 236 parent trades and sealed initial intent geometry, plus the A4 summary and child identity hash. It does not supply the exact 117-row membership list, raw contiguous 1h candle sequences, or each trade’s intrabar/stage path. A trade-identity hash is a check against a supplied list; it does not reconstruct that list.

Accordingly, a source rule gap and a raw observation gap remain separate:

1. **Source rule gap:** no immutable licensed author-native complete exit rule bound to this parent. More candle data alone cannot fix it.
2. **Causal attribution gap:** no exact candle/stage history and explicit 117 membership in this recovered packet. More generic reading alone cannot fix it.

The saved aggregate and parent ledger may be audited without claiming “this exit saves these losses and preserves those winners.” No latest-market refetch, synthetic missing bar, economic replay or parameter fit was used. Byte-preservation and source-binding tests are static/integrity checks; they are not execution-parity or profitability tests.

## Falsifier and handoff

This finding is falsifiable: supply a licensed immutable author-native exit definition demonstrably linked to the exact parent, including activation, distance, update, cadence, effective information time and stop/gap precedence; show that it is genuinely distinct from the exhausted rules, with no invented parameter. Exact raw data and the 117 membership must separately be recovered before causal attribution. Until then a completed source contract, candidate freeze, negative control or economic command would falsely imply eligibility.

A necessary counterexample is a normal pullback that triggers the proposed exit and later becomes a large winner. A rule saving selected losses can still destroy the rare winners on which this parent depends. Source semantics alone cannot predict the net result; eventual evaluation would need affected losers, recovery winners and large-winner retention on the same frozen identity, under A’s separate authority.

**A handoff:** `CLOUD_WORK_COORDINATOR_ISSUE1358_V1` receives a mechanism-replacement decision request only. This Work supplies no source-exact child and no economic launch command. K117, existing A/B/D responsibilities, master, workflows and ledgers remain outside this source review’s mutation scope.

All 15 frozen source-object paths, Git blobs and SHA256 values are recorded in `SOURCE_EXACT_FALSIFICATION.json` and `inputs/SOURCE_OBJECTS.json`. The original policy/evaluator/evidence blobs are preserved as inert input snapshots; an archived workflow is evidence only and is not installed or run as a workflow.
