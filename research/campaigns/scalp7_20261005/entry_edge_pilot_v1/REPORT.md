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
ENTRY_EVIDENCE_COMPACT.json durably stores all15 observations used here, including both clock/price domains and original realized outcomes; SHA25635cda9bb09813a791846f1d3c5bcacc063d4b3005dda4137dadcc2b98650dc0d. Its declared full diagnostic SHA25603d5602688ee8e33ccc65a34bc865e7b819f7f97c1be6856fa2234e5a7d758f3 refers to the larger local reconstruction including intermediate manifests. The full original price input is still in the original artifact, not permanently stored by this checkpoint. Source helper paths/digests remain in the pinned predecessor contract. The original source-contract SHA0717e695a33abed5ec3c362bc4e266b3ff9475766e8eab3186a30544ed61e088 is independently fixed by the diagnostic script.

```sh
PYTHONPATH=. python ops/issue1358_entry_evidence_v1.py \
  --price PRICE_INPUT.json.gz \
  --parent-bundle research/campaigns/scalp7_20261004/clocked_lanes_v1/RESULT_BUNDLE.json.xz \
  --source-contract research/campaigns/scalp7_20261005/squeeze_nonpositive_exit_v1/CONTRACT_GITHUB.json \
  --output NEW_ENTRY_EVIDENCE.json --compact-output NEW_COMPACT.json
```
Use only the previously verified original price payload3da2f940e532be2c04ea25386782ef5732b12eb99d6f8203473ee3d57433d0b3. This CLI reconstructs indicators and observations only, not market paths. Routine CI uses stdlib fixtures and the saved packet; it does not acquire prices or repeat this reconstruction. Local environment Python3.13.5/numpy2.2.6/pandas2.2.3; the supplied pinned wheel was reused, not a paid service. Local12 tests PASS:10 clock/feature fixtures plus2 saved-packet/parent-binding checks. Canonical frontend validation before/after PASS. A wrong local input pathname failed before reconstruction, then was corrected; no model allowance or source data changed. Exact-head CI/review/publication must be recorded separately, not assumed from local tests.

## Authority and limits
The18.204861-day interval is already consumed development history. Rejected opportunities receive no invented outcome; these counts are descriptive, not statistical proof of an alpha or a failed strategy. Seed/config readiness and modeled minute-open fills/ACK retain the original assumptions. No account NAV, funding settlement or live fill is certified. New economics0, signal regeneration0, strategy changes0, orders0, deployment0, service changes0, paid calls0. Existing parent/child result bundles, claims, contracts and other lanes are unmodified. No claim of autonomous scheduled progression or profitability improvement. Rollback removes only these additive diagnostic files, preserving all original evidence.
