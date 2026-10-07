# Minimum ETH terminal report extension

Status: **NOT_COMMON_RUNNER_INTEGRATED**. Pure fixture-only code lives outside the repository. Source rules and actual replay state remain unchanged.

The helper `terminal_eth_report(result, hourly_records, end_ms=END)` provides a diagnostic statement beside the existing realized ledger. It never passes an open mark to common `summarize()`, adds a completed trade, changes WR/PF/DD, submits an exit or charges an unexecuted exit fee.

| Component | Report treatment |
|---|---|
| Closed positions | Existing realized gross minus existing closed fees and signed funding |
| Still-open position | Unrealized gross at the latest eligible close, separately subtracting its already-paid entry fee and signed funding |
| Fee stress | Existing1x/2x fees only; signed funding unchanged |
| Combined value | Descriptive per-entry-normalized bps; NAV, source portfolio return and account DD stay unknown |

A mark must occur strictly after entry, at or before END, and be delivered at or before END. Source descriptors from entry through END must be complete and in one segment. The latest eligible close wins; the latest receipt alone does not. A receipt exactly at END is eligible. A late END-close is excluded; an older available mark is disclosed with its clock and age, without an invented age cutoff. Unavailable and post-END close bodies are never accessed by this helper.

Funding at END remains excluded under the fixed development window. Funding already paid or received remains signed; same-side boundaries are uninterrupted ownership. The helper does not authenticate an archive or certify settlement coverage: the common caller must do that before using any economic report.

For multiplier m, closed net=closed gross−m×closed fees−signed closed funding. Open marked net=open gross−m×already-paid entry fee−signed open funding. Combined value sums the two under the existing descriptive bps convention. The report also distinguishes the realized cashflow prefix, including open paid costs, from the unrealized price mark.

Missing funding, missing eligible mark, inconsistent source lineage, occupied gaps or fee reconciliation failure produce blocked/null components. Unknown values are never replaced with zero. An available mark does not resolve the actual position: the replay retains `BLOCKED_TERMINAL_UNRESOLVED`, and this report adds no economic PASS/sample threshold.

An artificial example proves the distinction: one closed trade yields+86bps, while the open exposure has−200bps unrealized gross,7bps already-paid entry fee and5bps funding debit. Its marked net is−212bps and the combined diagnostic is−126bps. Closed sample count stays1; no exit fee or trade is fabricated.

Validation:31 artificial methods (22base+9terminal) and compile checks passed. Independent review also passed31/31. Tests cover late-price access guards, exact-END receipt/funding, missing mark/funding, occupied gaps, source lineage, cost stress, period/fee mismatch, unchanged state and positive-closed/negative-open reporting.

The original22-method draft is preserved in `baseline_22/`. Its receipt remains historical. Current hashes and limitations are recorded in `TERMINAL_EXTENSION_RECEIPT.json`.

Actual market replay, funding row reads, claims, activation, model invocations and repository edits:0. Common runner integration, terminal disposition policy and later execution remain coordinator-owned.

