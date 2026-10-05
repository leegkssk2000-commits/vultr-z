# Issue1358 — point-in-time entry evidence checkpoint

## Actual work and scope
Manual continuation in the interactive Chat, not a verified scheduled invocation. Base master784ea0a5aa542d147fc0101cd8c5690f2057ac81, research branch codex/issue1358-entry-evidence-20261005. The active claim is Issue1358 comment5996229505. No competing new economic owner is created here.

Reconstructed the frozen Squeeze entry conditions at ALL15 saved potential signals, with the original9 completed outcomes and all6 noncompleted/rejected opportunities retained. Reused the pinned recorded-price input and original native indicator helpers. Did NOT call generate_signals, simulate, run_lanes, any completed economic runner, or fit/search any parameters. This is one Squeeze evidence checkpoint within ENTRY_EVIDENCE; it does not finish the whole entry-edge pilot or prove the absence of an exploitable mechanism.

## Findings that change the next work selection
| Observation | Actual result | Decision consequence |
|---|---:|---|
| Native momentum positive AND accelerating |15/15 saved signals|Adding this same requirement is redundant, not a new entry mechanism.|
| Completed positions whose LATER modeled fill is below the signal low |3/9|Not three ex-ante avoidable losses: modeled fills were not available when the decision was made.|
| Completed positions whose latest actually RECEIVED minute close is below the signal low |1/9|A distinct observable, but this small post-outcome grouping does not establish filter value.|
| Original winners without a close above the previous candle high |1 of2|A generic previous-high confirmation may discard genuine winning opportunity; do not assume free improvement.|
| Original losers with a close above that previous high |4 of7|That confirmation also does not separate the observed losses.|

The largest losing DOGE setup still had positive, accelerating native30m momentum. Its signal close was0.1038; its modeled fill0.10269 was106.9364bps below that close, whereas the latest minute close actually known at decision was0.10337, only41.4258bps below it. Both prices were above the signal low0.10184. The fill was240seconds after the signal bar closed. Neither an extra positive-momentum gate nor a signal-low violation rule explains this particular loss. These are observed prices and saved outcomes, NOT a new counterfactual exit or skipped-trade profit calculation.

The first two price domains above must remain separate. A future modeled fill is recorded under outcome_diagnostics and explicitly marked not a decision feature. A real conditional order using a future live quote would require its own supported order semantics and fixed experiment; it is not certified by this packet.

## Decision and exact successor
NO_JUSTIFIED_ENTRY_ALPHA_FROM_THIS_SMALL_INSPECTED_PACKET. This rejects the proposed shortcuts, NOT all Squeeze strategies and NOT all possible entry redesigns. Do not fit a classifier on9 trades, recycle a duplicate momentum gate, infer safe filtering from future fills, or continue the spent exit/BE axis.

The next permitted substantive item is broader source/attempt evidence selection under Issue1358 FREEZE_ONE: identify ONE distinct executable entry mechanism and compare its economic rationale and counterexamples against the prior registered/failed architectures BEFORE allocating a model execution. Known prior entry architectures already registered include Rider impulse/pullback/reclaim, Break anchored-retest-reclaim and Supertrend native impulse/pullback. They must not be relabeled new without a genuinely distinct change. Prior Squeeze false-release EMA34/momentum and Keltner EMA20-loss exits were rejected; do not rediscover them.

Targeted references, not a new whole-repository resurvey:
- research/campaigns/scalp7_20260915/broad_rebuild_v2/CAMPAIGN_PREREGISTERED_V2.json
- research/campaigns/scalp7_20260915/broad_rebuild_v2/EXECUTION_REGISTRY_EXPORT_V2.json
- research/campaigns/scalp7_20260915/SCALP7_CHAT_NEXT_REJECTIONS_V1.json
- existing source-mode rules and candidate-local final results referenced by those records.
A candidate's detailed rule and rationale must be frozen BEFORE its new full chronological comparison, including an executable negative control and retained/censored opportunities. The bounded pilot remains at new entry candidates0/1 and new model executions0/2. This checkpoint neither replenishes prior claims nor consumes a new economic allowance. G5 or material grades are not awarded.

## Reproduction and verification
ENTRY_EVIDENCE_COMPACT.json is immutable predecessor evidence; SHA25635cda9bb09813a791846f1d3c5bcacc063d4b3005dda4137dadcc2b98650dc0d. Its six rejected/occupied opportunities incorrectly label next-minute prices as modeled fills despite having no completed parent trade. These fill labels are superseded by ENTRY_EVIDENCE_REVIEW_CORRECTION_V1.json, SHA2562c35e3af1b6b8a6967ee57cf17411579b41e1baf9e341c0a3178b98966ccf5db. Do not consume the raw packet as current fill evidence.

The current saved-only consumer is ops.issue1358_entry_evidence_v1.load_effective_packet(). It verifies both byte hashes, source/schema bindings, unique signal keys and the correction's exact six-key nontrade set before applying the null-fill semantics. All15 decision-time fields and all9 completed-trade rows remain unchanged; only the six nontrade later_modeled_fill cells become null. For nontrades, modeled_entry_ms remains the original next-minute modeling grid timestamp, not proof of an entry or a fill. The deterministic encoded effective packet has SHA256345cb98f7c315617ff9a6e1fa9485339aa824c354f016675e8faf1fe81cd53b6.

The predecessor full-diagnostic SHA25603d5602688ee8e33ccc65a34bc865e7b819f7f97c1be6856fa2234e5a7d758f3 is retained only as superseded provenance; it is not an active corrected diagnostic artifact. The loader sets full_diagnostic_sha256=null and full_diagnostic_not_persisted_after_review_fix=true. The full original price input remains in the original artifact. Source helper paths/digests remain in the pinned predecessor contract; original source-contract SHA0717e695a33abed5ec3c362bc4e266b3ff9475766e8eab3186a30544ed61e088 remains fixed. This correction does not reconstruct the15 signals or rerun economics.

```sh
PYTHONPATH=. python -c 'from ops.issue1358_entry_evidence_v1 import load_effective_packet, encoded, digest; print(digest(encoded(load_effective_packet())))'
PYTHONPATH=. python -m unittest discover -s tests -p test_issue1358_entry_evidence_v1.py -v
```
Before this consumer repair, the existing SavedPacketTest.packet() exposed nonnull fill prices for all6 nontrades despite the correction receipt; a saved-only assertion requiring null failed. The first repair at603fb323 corrected new reconstruction output and published the supersession receipt but did not connect saved consumers. This loader/test/report connection is the second and final permitted minimal repair for that same cause (cap2); it does not reset the allowance. Focused17 tests PASS:10 clock/feature fixtures and7 saved effective-packet/parent-binding, invariance and failure checks. Canonical frontend validation before/after PASS. These commands read saved evidence and stdlib fixtures only; they do not acquire prices, reconstruct indicators, regenerate signals or call economic models. The original price pin3da2f940e532be2c04ea25386782ef5732b12eb99d6f8203473ee3d57433d0b3 is retained, not reopened. Historical reconstruction environment was Python3.13.5/numpy2.2.6/pandas2.2.3; the current correction uses stdlib only. Exact-head CI/review/publication must be recorded separately, not assumed from local tests.

## Authority and limits
The18.204861-day interval is already consumed development history. Rejected opportunities receive no invented outcome; these counts are descriptive, not statistical proof of an alpha or a failed strategy. Seed/config readiness and modeled minute-open fills/ACK retain the original assumptions. No account NAV, funding settlement or live fill is certified. New economics0, signal regeneration0, strategy changes0, orders0, deployment0, service changes0, paid calls0. Existing parent/child result bundles, claims, contracts and other lanes are unmodified. No claim of autonomous scheduled progression or profitability improvement. Rollback removes only these additive diagnostic files, preserving all original evidence.
