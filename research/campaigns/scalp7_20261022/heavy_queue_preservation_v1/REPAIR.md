# Shared economic queue preservation — bounded operational repair

## Confirmed source defect
Baseline master: `5f290859fdf7be23806e2cc930001a3144c6324d`.
62 workflow files participate in `a1-global-heavy-economic-evaluator-v1`; 52 omit `queue: max` although `cancel-in-progress: false` is present. The prior Keltner-only fix `3a6815938d346515433f970d1f2a4ed265ff23ef` changed only the Keltner workflow. Other producers still use the default replacement queue.

GitHub's official documentation says default `queue: single` replaces existing pending work; `cancel-in-progress: false` protects running work, not the waiting queue. `queue: max` retains up to 100 pending entries and does not increase concurrent execution.
Source: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
Release: https://github.blog/changelog/2026-05-07-github-actions-concurrency-groups-now-allow-larger-queues/

Runs 39762857755 and 39765927161 were cancelled with zero jobs. The exact cancelling actor/API reason has not been established. Mixed queue policy is a source-confirmed defect consistent with those symptoms, not a fabricated actor attribution.

## Minimal patch and preservation
Add exactly one `queue: max` line to each of the 52 missing concurrency blocks. Keep all group expressions, cancellation protection, schedules, jobs, original scripts, parameters, costs, economic ledgers, market inputs, owner contracts and permissions unchanged. Do not cancel active or pending work, remove a lock, create a competing group or reset an economic claim.
`PATCH_MANIFEST.json` pins the original and patched bytes for all 62 participating workflow files. Regression tests compare parsed YAML after removing only the queue property, so accidental behavior changes fail validation.

The existing `kp-input-validation-20261004.yml` receives a read-only queue-contract validation mode. Its default original validation remains intact. The new mode performs frontend pre/post validation and configuration regressions, with no secrets, market requests, trading replay, production mutation or global economic slot acquisition. No new workflow, service, cron or agent is added.

## Verification and merge scope
Local regression: 15 test methods PASS, including job-level and workflow-level mappings, conditional group expressions, missing/single/invalid queue negative controls, all-participant checks, exact before/after hashes and unchanged nonqueue semantics. Canonical frontend validation and git diff whitespace checks pass.
Use the existing workflow's dedicated source branch push to run exact-source non-economic CI. Before opening the PR, an empty metadata-only `[skip ci]` commit can prevent legacy PR workflows from performing unrelated historical economic replays; the Git tree must match the successfully validated tree exactly. Do not bypass branch protection or required review/check requirements. Merge only through the normal PR API and expected-head comparison; never push master directly. The merge message should preserve `[skip ci]` to prevent configuration-only changes from automatically rerunning all old strategies.

## Remaining limits and operational acceptance
This patch fixes replacement semantics, not unlimited throughput. Do not claim all queue congestion is solved from static checks. Existing in-flight requests retain their original configuration. New queued work must be observed retained through another enqueue and then actually started; native C/D receipts and unchanged 117-trade output are the operational completion criterion.
Existing historical scripts may still submit work faster than the single worker can finish. Scheduled producer deduplication or admission changes require a separate measured scope; do not silently disable collectors or another owner's work. The obsolete queue-purge workflow exists but its trigger has not changed since August; do not assert it caused today's cancellations without actual run evidence.
Public unauthenticated GitHub API returned 403/remaining=0 with reset 2026-10-22T11:13:52Z. Honor that reset. No token, account, proxy or alternate endpoint is used to evade the limit.
