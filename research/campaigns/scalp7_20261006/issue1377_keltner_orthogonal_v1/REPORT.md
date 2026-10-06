# Issue 1377 first deliverable

Saved-ledger audit only: no market replay, FULL consumption, order, Paper/Live, or promotion.

## Keltner cost transition

| Class | Trades | Meaning |
|---|---:|---|
| Original 1x loss | 44 | Non-positive before stress |
| 1x positive -> 2x non-positive | 27 | Cost crossing |
| 2x positive survivor | 38 | Same fills remain positive |

The 27 crossings are {'HG_FROZEN_5BAR_MFE_SCRATCH': 2, 'MAX_HOLD_NEXT_OPEN': 1, 'STOP_FIRST': 24}; 23 finish at approximately +2bps under 1x cost. The descriptive top seven 1x winners all remain positive at 2x. K child: **not selected**.

## Non-K selection

Selected `mr_cross_sectional_contraction_cost2_gate_30m_v1`. It keeps the parent 6h/3%/next-open/8-bar/single-pair lifecycle and changes only entry admission: completed-bar first-contraction bps must cover the exact frozen bilateral 2x cost. Rule SHA256: `e32154e58d0c04fb77376f0e1e0433bd7c6c6c272fbd1c10d04decaadf70ee7a`.

## Seven lanes

| Lane | State | Current work |
|---|---|---|
| Keltner | PARENT_POSITIVE_COST_FRAGILE | 109T_SAVED_AUDIT_COMPLETE_NO_CHILD |
| Squeeze | ISSUE1358_2T_DEVELOPMENT_SURVIVOR_NOT_G5 | NO_RERUN |
| Trend Rider | SCALP7_15M_FAIL_A1_261T_CONCENTRATION_HOLD | OTHER_OWNER_LEDGER_HANDOFF_ONLY |
| Cross-sectional MR | 1X_WEAK_POSITIVE_2X_NEGATIVE | ONE_COST_COVERED_ENTRY_CHILD_SELECTED |
| Break 15m | ANCHORED_RETEST_RECLAIM_FAIL | NO_PARENT_REPLAY |
| Supertrend 30m | NATIVE_IMPULSE_PULLBACK_FAIL | NO_PARAMETER_SWEEP |
| Micro EDGE15m | SOURCE_EXECUTION_HOLD | REAL_L2_OFI_RECEIPT_CONSUMER_REQUIRED |

Economic result: not run yet.
