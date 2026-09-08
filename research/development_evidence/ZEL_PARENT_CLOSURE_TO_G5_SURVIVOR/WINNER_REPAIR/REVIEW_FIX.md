# PR1215 required review disposition

Review 5137461695 of head 16c110e3279bd9972dd54a05168b981d5c78bb05 finished at 2026-09-08T04:56:21Z. Two findings addressed without changing the frozen economic modules, SPEC, any actual result or any strategy rule.

## P1: terminal shared-budget persistence (comment 3954449772)

The historical executor reserved all three trials but did not automatically copy its terminal receipts back into the shared budget. Root performed this settlement after the actual runs; that manual step was not represented by an executable producer in the first PR head. This is a persistence defect, not a new economic result.

Added `step7_kr3_winner_persistence_v1` as the operational caller. It invokes the immutable executor once and settles in `finally`, including when a batch fails partway. It preserves the original O_EXCL scope/run claims and limits. Settlement validates each trial/receipt scope, run, ordinal, candidate, SPEC identity, status and opaque result hash under the shared lock, then atomically records completed/failed/unknown counts. An unresolved reservation remains consumed/unknown and never becomes retryable. No candidate counter, evaluation counter or prior trial is reset.

Operational command, for an independently authorized unconsumed allocation only:

```sh
python -m backend.research.rebuild.step7_kr3_winner_persistence_v1 --input out/WINNER_PREPARED.json.gz --execute
```

This scope has already consumed all three attempts; that command was **not executed**. The original historical command remains in REPORT.md and frozen source, and will reject this consumed scope. The review fix does not rewrite the pre-outcome freeze or claim it existed before results.

The settlement function was invoked once on the saved terminal receipts (CLI equivalent `python -m backend.research.rebuild.step7_kr3_winner_persistence_v1 --settle`). The budget remained byte-identical: used/completed/failed/running/remaining = 3/3/0/0/0. Receipt: PERSISTENCE_FIX_RECEIPT.json. Five new synthetic tests passed: initial reserved→completed, idempotence/history preservation, failed/unknown consumption, result corruption and success/failure caller finalization. No actual economic replay.

## P2: dependency-only CI changes (comment 3954449777)

Both PR and master workflow triggers now name every non-winner dependency in the immutable SPEC. Winner code/test wildcard triggers include the new persistence caller. CI verifies this coverage and the original file hashes. Parent scope classification recognizes only the added caller/test so completed old economics remain skipped for this successor. No new source job or reviewer was dispatched.

The required final-head CI rerun includes the five new synthetic boundaries and confirms byte-identical stored settlement. No new rule freeze, candidate or evaluation is allocated for this persistence repair. Remote merge/fixed-merge receipts follow separately.
