# Issue #1361 repeatability preparation

State at 2026-10-06T01:11:26Z: protocol and source-admission implementation only. No market signal, fit, FULL, or economic claim was created.

## Fixed scope

- Candidate: frozen EMA21 `BUY_LIMIT`; comparator: original Squeeze parent.
- Rule hash: `004d374096f31eadb3ef883e4481a58be7673eea7d679ad66ac5c59a73c1964d`.
- Historical validation: exactly H1/H2/H3, each with its own prior-only 90-day fit and exclusive 30-day test, classified `RETROSPECTIVE_PIPELINE_STABILITY_NOT_FRESH`.
- Prospective validation: final 2026-09-15 fit, one cohort, first future UTC 30-minute boundary only after protocol/source binding, 30/60/90-day reporting, recorded receipts required.
- Allocation: H at most six FULL instances; F two model streams; Issue #1358 consumption is not reset or reused.

## Source finding

The repository retains the published 2026-09-15 receipt (3,153,576 raw rows, 24 missing minutes, 17,519 complete 30-minute bars per symbol, two segments) and its source inventory hash. The canonical archive root is not mounted in this Work environment, which is an access result—not evidence that the archive is absent. Historical delivery remains a modeled bar-close profile; volume units, funding, mark, and NAV are not filled with zero.

The added post-merge manual workflow performs one read-only manifest hash inventory over the already configured SSH path. It neither starts/restarts services nor fetches market data. H remains `INPUT_NOT_READY` until that readback succeeds. F remains separately `INPUT_NOT_READY` until an existing observation path can supply persistent recorded receipts; historical REST data is not relabeled as forward reception.

## Verification and next gate

Local compilation and direct contract assertions passed. The full focused pytest set was not available in this Work image because `pytest` is not installed; the dedicated GitHub job installs pinned test dependencies and runs the new tests plus the source, rolling-context, and EMA21 suites. After exact-source CI/review and normal merge, run the read-only inventory job, store its artifact/hash, then obtain independent approval and create immutable per-instance claims before any H economics. F starts only after genuine recorded-receipt binding.
