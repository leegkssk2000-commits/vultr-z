# A Squeeze saved-result recovery

State: `HOLD_AUTHENTICATED_WORKFLOW_DISPATCH`. No FULL result has been recovered. This directory adds a bounded, offline arithmetic verifier and synthetic fixtures; it does not dispatch, replay, consume a claim, or adopt a candidate.

## Exact input contract

Use only the immutable `RESULT.json` and `STARTED_FREEZE.json` recovered from the official Squeeze FULL workflow artifact. The candidate, existing owner, source inventory, context fit, saved S receipt, ordered K receipt and used-development window are pinned in the verifier. SHA-256 receipts bind their contents; they are not cryptographic signatures or independent proof of data origin.

```sh
python3 -B research/campaigns/scalp7_20261023/a_squeeze_result_recovery_v1/verify_saved_result.py --result <recovered_artifact>/SQUEEZE_SIGNAL_LOW_FULL/RESULT.json --freeze <recovered_artifact>/SQUEEZE_SIGNAL_LOW_FULL/STARTED_FREEZE.json
```

The placeholder paths are a contract, not an assertion that those artifacts exist. Missing inputs return exit 2 and `NOT_RUN_MISSING_FULL_ARTIFACT`; invalid inputs return exit 1 and `HOLD_INVALID_SAVED_ARTIFACT`.

## Bounded verification

The verifier independently recalculates successor 1x/2x costs, trade count, gross/net, net per trade/day, win rate, profit factor, maximum loss streak, worst trade and realized drawdown grouped by simultaneous outcome availability. It checks receipt bindings, row uniqueness, recorded causal clocks, accepted-entry matching and incomplete-result classification. Realized trade-bps drawdown is not account NAV or mark-to-market drawdown.

A pass means only `PASS_SAVED_SUCCESSOR_ARITHMETIC_ONLY`. It does not establish OHLC fill correctness, stop-first/gap handling, opportunity completeness, parent/child reconciliation, the ten-trigger causal attribution, ordinary/large/recovery winner retention, or SSOT economic acceptance. These require the actual recovered artifacts and source audit. Actual economic metrics remain null/NOT_RUN.

## Synthetic validation

```sh
python3 -B -m unittest discover -s research/campaigns/scalp7_20261023/a_squeeze_result_recovery_v1 -p 'test_verify_saved_result.py' -v
```

Four artificial trades supply hand-calculated expectations; fourteen finite tests include tampering, incorrect doubled costs, duplicate events, future features, accepted/trade entry mismatch, the exclusive end boundary, nonpositive costs, unresolved-trade misclassification, wrong inventory, missing acceptance, and confusing the old overlay with the successor. No historical replay is involved.

## Resume condition

Use normal official Work Cloud Browser authentication only after its existing approval block is resolved. Before dispatch, refresh master/SSOT, the existing owner/consumption ledger, scheduler, all relevant run attempts and artifacts, the permanent Squeeze claim, native input hashes and the shared global-heavy guard. Recover any existing started/consumed result and never rerun it. The snapshot in `HANDOFF_RECEIPT.json` is not a reservation or future capacity guarantee.

Preserve the enabled existing timer until a verified safe ownership transfer. At most the one already-approved remaining Squeeze FULL may run through authenticated `workflow_dispatch` against master with `squeeze_signal_low_full=true` and other controls unchanged. No other dispatch route is authorized here.

No application deployment is needed. This addition changes only this research directory; rollback may revert the addition without changing owner state or the economic ledger.

