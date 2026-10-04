# Receipt-clocked Squeeze parent / frozen BE1R comparison

User requested efficient continuation after PR1355. Current Scalp7 remains15m/30m, not old1h/Broad. Non-frontend research is explicitly requested under AGENTS exception. Existing frozen strategy, old experiments, telemetry, guards, services and order authority stay unchanged.

Two pre-existing Squeeze identities share one input build and one execution convention: parent and fee-adjusted BE1R child. One economic run each, maximum2. K.P replays0. This is one strategy A/B comparison, not two independent alpha sources. CONTRACT was committed before any output, corrected for review findings before activation. RUN.json remains absent at this preexecution revision.

Reuse PR1355's verified164,490 minute rows and same fixed Sep15 20:00Z–Oct04 00:55Z interval. No price recollection or replay of K.P's completed20/119 trades. This interval is already consumed research data. Good numbers cannot open G5B/G6/Core/Live; bad numbers are negative development evidence, not formal G5 terminal failure.

## Timing convention

The maximum of all six recorded price prefixes determines signal readiness, conditional on the explicit historical seed/config-ready assumption. Enter first1m open strictly after readiness, expiring at the next30m close. Resting initial stops work immediately, including adverse gap-open and conservative1m stop-first fills. Full30m bars starting after entry trigger native management; initial partial entry bar is excluded. Management becomes effective at first1m open after causal prices arrive. At that event, MFE includes every closed postentry minute actually received by then, including known minutes later than the trigger bar close. Momentum remains from the observed30m trigger. Unreceived prices never arm BE. MFE/MAE reports are observed management snapshots, not eventual full-path extrema.

This is an explicitly changed execution convention, not exact old-model parity or proof of actual fillability. Seed/config observation, next-minute market fills and acknowledgments are model assumptions. No funding, leverage, margin or continuous account NAV/DD certification. Single-asset no-target/no-partial only: unsupported profiles reject. It is not a complete universal7-lane executor.

## Review before activation

P1 atomic reservation4178580895: shared fixed-volume O_EXCL claim independent of output/checkout, never released after failure/success. P2 owner4178611288: pre-created32-byte persistent OWNER_ID on same claim volume, fingerprint-bound in contract; no boot_id or automatic regeneration. Lost volume cannot silently restart a spent batch. P1 observed MFE4178611284: included all actually received postentry minutes at management event, not only prices through triggerbar close. Added known-extra-minute/native-BE and stable-owner regressions. All corrections precede economic outputs; old unexecuted contracts remain in Git history.

27 generated tests PASS locally under pinned numpy2.2.6/pandas2.2.3/requests2.32.5. CI and final review must be checked on the exact source, not inherited. Local owner execution, GitHub contract/results publication; current Actions workflow has no economics or SSH. Existing source and input hashes are reused, not changed. End condition is actual paired output plus independent saved audit and reviewed publication. No separate Work handoff or user SSH is required. Deployment DO_NOT_RUN.
