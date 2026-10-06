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

The added post-merge manual workflow performs one read-only manifest hash inventory over the already configured SSH path. It neither starts/restarts services nor fetches market data. The metadata-only tool lives under `ops/` so unrelated historical measurement guards do not mistake it for a replacement of their owned backend. H remains `INPUT_NOT_READY` until that readback succeeds. F remains separately `INPUT_NOT_READY` until an existing observation path can supply persistent recorded receipts; historical REST data is not relabeled as forward reception.

## Verification and next gate

Local compilation and direct contract assertions passed. The full focused pytest set was not available in this Work image because `pytest` is not installed; the dedicated GitHub job installs pinned test dependencies and runs the new tests plus the source, rolling-context, and EMA21 suites. After exact-source CI/review and normal merge, run the read-only inventory job, store its artifact/hash, then obtain independent approval and create immutable per-instance claims before any H economics. F starts only after genuine recorded-receipt binding.

Review hardening binds every H fold to the exact candidate/comparator identities and removes the caller-controlled F freeze timestamp. F admission obtains the trusted digest from a fixed permanent GitHub claim ref containing exactly `CLAIM.json` and `FREEZE.json`, verifies both Git blobs plus the independent-approval identity, and then requires the contract and receipt to match that external digest. The start must equal the first UTC 30-minute boundary strictly after the claimed freeze; a merely aligned later boundary is rejected.

Source admission does not infer readiness from the three manifests alone. The read-only probe hashes the same receipt, response-body, normalized-chunk, 1-minute, and gap-prefix file set as the established loader and requires the complete inventory hash `53c64616fa98ddd446533cbc7b8e90eb2866ce9b1b0b3243df4211d59f155ba2`; a missing or changed member stays `INPUT_NOT_READY`.
