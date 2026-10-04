# Next bounded Scalp7 stage: timing-aware Squeeze comparison

This is the current user's explicit next-step instruction after PR1355 and the decision not to let Keltner monopolize development. Current Scalp7 remains15m/30m; legacy1h/Broad results are not revived. This is authorized non-frontend research under the AGENTS explicit-task exception, not a deployment.

Reuse PR1355's verified164,490-row input and frozen30m strategy functions. Do not reacquire prices, replay K.P's completed20/119 trades, retune any candidate, touch shared running consumers, or allocate to other lanes. Next comparison is the two already frozen Squeeze identities: parent and fee-adjusted BE1R child. Same prices, prefix clocks, costs and new execution model; one economic execution per identity, maximum2. This is one strategy comparison, not two independent alpha sources.

## The changed execution convention

All six price prefixes determine when the signal could be computed, conditional on the explicit historical seed/config-ready assumption. Enter at the first1m open strictly AFTER that time; do not backdate to the30m close. A signal expires at the next30m close. Resting initial stops work from entry, with adverse gap-open fills and conservative1m stop-first behavior. Only full30m bars beginning at/after entry are given to the native lifecycle callback; the initial partial bar is excluded. Management orders take effect at the first1m open after the relevant prefix has arrived. This is a newly frozen execution convention, not proof of exact original live execution. No additional zero-latency market-data assumption is silently inserted; future minute-open execution/ack and historical seed readiness remain MODEL assumptions.

Partial/pair/target profiles are explicitly unsupported in this small adapter and reject. Do not call this a finished universal seven-strategy engine. Squeeze has no partial/target profile; its two exact variants share this path. K.P's partial engine is not replaced.

## Evidence/roadmap boundary

The interval was already consumed in K.P research and is NOT untouched OOS/fresh. A good result cannot open G5B/G6/Core/Live; a bad result is negative development evidence, not formal G5 terminal failure. The purpose is to close a timing-aware executable comparison and judge the pre-existing Squeeze management child before spending on broader independent tests. Input receipt stamps are retained, not altered. New truly unused/prospective evidence and complete use/owner records are still required for stage advancement.

CONTRACT.json is frozen before outputs. RUN.json does not yet exist; no economic invocation has happened in this branch.20 generated-data tests pass locally, including real frozen callback connection, later-symbol and earlier-bar delay, no preentry/future MFE, stop activation, gaps, expiry and unresolved positions. Canonical validation passed locally and in bootstrap37219099279. New exact-head CI/review is separate and must precede activation. After activation, retain failure or completion and do not retry consumed economics. End-point: comparison result + reviewed publication, not a promise of future background work.
