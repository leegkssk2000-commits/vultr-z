# TrendRider Unified Stage0 — prior axes and causal inventory

Read-only audit for Issue #1272. New screens, canonical candidates, economic runs, threshold experiments: **0**. This document is temporary subagent evidence; root owns the final Stage0 parity verdict and durable scope receipt.

## PR #1044 and #1052: exact status

| Source | Observed execution | Economic interpretation |
|---|---|---|
| PR #1044, head `a8f3e057b044a90a3d86512e693fab1db8fcb56a` | OPEN, unmerged; run33112033729/job98657051096 succeeded | `HOLD_FROZEN_PRIMARY_TRADE_PAYLOAD_UNAVAILABLE`. Selected0, combined metricsnull. Parent-payload block, not an economic rejection. |
| PR #1052 V3, head `fed01faa15cfab53158590bca12940a8a824a907` | OPEN, unmerged; run33122651040/job98693515674 succeeded | Code confirms five named state families, single-term and depth≤2 forms. Mixed holdout artifact not decoded; terminal economic outcome **unverified**, so CI success must not become an economic PASS or FAIL. |
| PR #1052 V4, same head | run33122651015/job98693120663 succeeded | Summary explicitly `HOLD_3BAR_PERSISTENCE_NOT_CAUSAL_ENOUGH`, both lanes preregisterablefalse, `REJECT_3BAR_GATE_AND_ROTATE_TO_HTF_ALIGNMENT`. Exact three aligned close-delta TRUE form is exhausted for both lanes. |

Sources: [PR1044](https://github.com/leegkssk2000-commits/vultr-z/pull/1044), [PR1052](https://github.com/leegkssk2000-commits/vultr-z/pull/1052), [1044 run](https://github.com/leegkssk2000-commits/vultr-z/actions/runs/33112033729), [1052 V3 run](https://github.com/leegkssk2000-commits/vultr-z/actions/runs/33122651040), [1052 V4 run](https://github.com/leegkssk2000-commits/vultr-z/actions/runs/33122651015).

GitHub `merge_commit_sha` fields on these OPEN PRs are proposed merge references, not evidence of actual normal merges.

## Six authorized feature families — source definitions only

| Family | Existing state definition | Owner |
|---|---|---|
| session_state | Signal UTC hour: APAC[00,08), EU[08,16), US[16,24) | `trend_rider_transition_freshness_non_us_child_policy_v1.py::_session` |
| st_gap_state | EXPANDING iff current completed-bar st_gap_atr > prior completed-bar value; else COOLING_OR_FLAT | `a1_trend_rider_wr80_winner_restore_attribution_v1.py::_enrich` |
| chase_state | EXPANDING iff current completed-bar chase_atr > prior completed-bar value; else COOLING_OR_FLAT | Same enrichment owner |
| atr_state | EXPANDING iff current ATR/close×100 > prior completed-bar ratio; else COOLING_OR_FLAT | Same enrichment owner |
| geometry_balance | ST_GAP_GE_CHASE iff current st_gap_atr ≥ current chase_atr; else CHASE_GT_ST_GAP | Same enrichment owner |
| directional/persistence | Three close deltas ending at signal close are strictly side-aligned; four closed prices; flat step fails | PR1052 `a1_trendrider_3bar_persistence_causal_v4.py::enrich_persistence` |

All local owner paths are under `backend/research/rebuild/`. The PR1052 policy is unmerged and must be referenced at its exact PR head, not claimed to exist in master.

Primary runtime owner `trend_rider_wr80_us_chase_cooling_child_policy_v1.py` retains a transition signal if session!=US OR current chase≤prior chase. Missing prior data maps to EXPANDING_OR_UNAVAILABLE, not cooling. Session/chase already inside Primary is a parent property, not a newly earned gene.

The state definition owner currently fetches rolling bars in its diagnostic enrichment; **do not invoke it on current data to backfill missing frozen historical snapshots**. Recover original immutable input and reproduce its original prefix, or leave parity blocked.

## Reuse bans and history limits

| Lane | Exact historical form | Disposition |
|---|---|---|
| Primary + Broad | PREENTRY_3BAR_DIRECTIONAL_PERSISTENCE_TRUE | Terminal rejection from PR1052 V4. No period/delta retuning or new name to reset it. This does not ban every possible directional mechanism. |
| Primary | PRIMARY_KELTNER_INCLUDE / PRIMARY_KELTNER_VETO | Both `DROP_CELL_KEEP_PARENT_FALSIFIED`; fixed donor decomposition exhausted. |
| Primary | PRIMARY_SUPERTREND_BTC_INCLUDE / PRIMARY_SUPERTREND_BTC_VETO | Both `DROP_CELL_KEEP_PARENT_FALSIFIED`; fixed donor decomposition exhausted. |
| Primary + Broad | PR1052 V3 named-state single terms / conjunctions≤2 | Previously executed forms; per-form terminal status unavailable in inspected safe summaries. Must recover exact prior receipt before proposing structurally identical reuse; do not mark all five families terminal-rejected without evidence. |
| Generic trend_rider | DONOR__EMA_RIBBON_SCALP__MULTI_SPEED_TREND_ALIGNMENT__ONLY | Generic prior attempt recorded; exact lane+axis mapping not proven. Audit-only according to existing lane-aware synthesis. |

Relevant local history:
- `backend/research/architecture_factory/a1_trendrider_lane_aware_history_latest.json`: READY_EMPTY_LANE_ATTEMPT_HISTORY, both lists empty. This is incomplete history, not proof of no prior attempts.
- `backend/research/architecture_factory/a1_trendrider_lane_aware_synthesis_v1.py`: generic strategy-level history may not automatically block a specific lane.
- `backend/research/rebuild/a1_top5_g4_primary_donor_decomposition_v1_latest.json`: four donor cells, zero winners, FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED.
- `backend/research/rebuild/a1_trendrider_8125_donor_state_gates_v1.py`: confirms four state families and historic current12 donor logic; absent terminal output is not a reason to rerun it.
- `backend/research/contracts/a1_prior_attempt_registry_v1.json`: exact dedup dimensions include strategy, baseline, axis, source/config/data cohort hashes.

## Stage0 failure handling

Root reports common-data parity blocked if original OHLC/warmup/full signal tape/funding and historical decision snapshots cannot be verified. Saved parent row parity alone does not establish this contract.

If root finalizes that block, all six family rows are `NOT_RUN_PARENT_PARITY`, each with screen_executed=false, metrics=null, survivor=null. **Do not report six screened failures or zero economic survivors.** The conditional rows are provided in the JSON companion.

Existing FOCUSED_REPAIR_20260907_V1/TRENDRIDER_AND_SUPERTREND.md already documents missing original data and evaluator occupancy differences. Its saved historical15 common paths can support audit but cannot create the missing causal opportunity tape.

Read boundary: historical PR/source/receipt summaries inspected. PR1044/V4 job logs also emitted old Aug2026 rebuild_current research stdout; no such records are persisted or used for gate decisions here. No prospective/G5B collector dataset or Squeeze prospective records opened.


## Bounded follow-up: Broad transition freshness actual result

The exact saved root state in `backend/research/rebuild/a1_trendrider_broad30_transition_addonly_v1_result.json` is **HOLD_TRANSITION_ADDONLY_PROFILE_PASS_BUT_VALIDATION_NOT_STRICT**, not the REJECT branch found in its source. Historical profile checks all passed; decision status is `PROFILE_QUALIFIED_WAIT_POSTLOCK_PROSPECTIVE_EVIDENCE`, next `ROTATE_SECOND_DISTINCT_ADD_ONLY_AXIS_IN_PARALLEL_WITHOUT_UNION`.

Its exact predicate is `CURRENT_PARENT_CONFIRM_TRUE_AND_PRIOR_CLOSED_BAR_SAME_SIDE_CONFIRM_FALSE`, axis `TRANSITION_FRESHNESS_REENTRY_SUPPRESSION_ONLY`, used as Broad future ADD_ONLY admission. This is a prior attempted form, but **no terminal-rejection ban is established by this saved result**. Never infer a historical result solely from an alternative source-code branch.

Provenance: run33124759000, artifact9668005541, artifact ZIP SHA256 `66dba870e89ec374c6a50e66e5c772544aadb59da9d2ba7177760dd5dffbc846`; latest commit touching the summary `fb54590fc5950c784efd209e5d3824a278a931f4`. Only root metadata, historical-profile summary and decision lines were read. The postlock prospective section was not read or decoded.

Root now confirmed Stage0 **BLOCKED_PARENT_PARITY**. Six family rows therefore remain NOT_RUN_PARENT_PARITY; no screen or additional mechanism search was performed.
