# Independent read-only review

Scope: `WORK_D_EXISTING(1).txt`, the new `trend256_source_gate_v1` implementation, its tests, the exact saved inputs and frozen native source, and the saved eight-file `completion` result. No implementation, native source, ledger, owner state or remote system was changed by this review. No market API, native strategy replay, economic FULL, guard or Actions was run.

## Findings

No P1/P2 defect found in the reviewed closure. `SOURCE_FEATURE_BLOCKED / NO_CAUSAL_CHILD` is a supported terminal result, not an economic pass or a deployable child. The work preserves the complete signed 256-row receipt and does not infer missing as-of features from hashes or substitute retrospective month, symbol or winner labels for execution features.

The following potentially misleading interpretations are explicitly prevented in the implementation and should remain intact in the owner handoff:

- The legacy overlap result is 107 pairs touching 106 of 123 Liquid6 rows. Strict positive half-open intersection gives 105 pairs touching 104 rows; the additional one-hour exit-bar model gives 115 pairs touching 113 rows. The two zero-span exceptions explain the legacy/strict difference. None of these numbers establishes observed physical holding time or independent eligible opportunities.
- The correlation near +0.924 uses the union of 37 stored exit-bar UTC dates, filling a missing lane with zero. It is not a 37-date intersection or actual outcome-availability correlation. The 28-date intersection and complete 42-date common metadata-envelope calendar are reported separately. Native Liquid6 risk-scaled units remain separate; no combined Net, 50:50 allocation, NAV, or causal portfolio benefit is claimed.
- Winner leave-out statistics are descriptive concentration diagnostics. All original winners remain present in the audit; no filtered subset is submitted as a strategy or an improved result. Entry-month and exit-month attribution are separately named, so October's 59 trades are correctly exit-month trades.
- The lifecycle counterexamples use the hash-bound native `transform` AST with explicit synthetic inputs and stubs. They demonstrate source semantics only, including fixed-stop gap fills and bar-open timeout stamps. They neither reprice the actual 256 rows nor estimate the economic incidence of those behaviors.
- Parent open/rejected records retain their inherited parent scope; they are not treated as the long-only child's reconstructed admission path. Missing OHLC, feature bodies, path state and availability evidence prevent a causal child or independent-opportunity claim.

## Independent verification

A separate standard-library calculation over the two saved receipts reproduced the three overlap results above and Pearson correlations 0.9237247419824631 (37-date union) and 0.9436779569987105 (28-date intersection). All seven output hashes listed by `RUN_RECEIPT.json` matched saved bytes. Its implementation hashes matched the current reviewed files. Every `ROWS_AUDIT.json.saved_row` equalled its corresponding original receipt row, in order. The saved terminal states are `NO_CAUSAL_CHILD` and `SOURCE_FEATURE_BLOCKED`.

Reviewed test coverage includes exact receipt/source rejection, all-row and winner preservation, cost arithmetic, month/chronology semantics, absence of invented features, source-bound native counterexamples, overlap ambiguity, unknown availability/independence, and exclusive output/readback. The parent's reported 48-test pass was not rerun by this review; the independent calculation and saved-output verification above were run separately.

The runner computes and serializes results before creating an exclusive new output directory, uses exclusive file creation, and reads every output back. Its source binding and pinned original D-module reuse do not alter A/B/C code or economic authority. No concrete remaining blocker to this evidence-only closure was identified.
