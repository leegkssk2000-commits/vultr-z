#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
TMP=""
RC=2

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36_START' \
  'MODE=READ_ONLY_SELECTIVE_SCALP_FILL_REBASE_AND_BASELINE_TRACE_EXPANSION' \
  'CANONICAL_STRATEGY_UNIVERSE_COUNT=25' \
  'SHORT_TARGET_STRATEGY_UNIVERSE_COUNT=12' \
  'ACTIVE_REPAIR_STRATEGY_COUNT=3' \
  'SCALP_COUNTERFACTUAL_CANDIDATE_COUNT=4' \
  'SCALP_COUNTERFACTUAL_CELL_COUNT=24' \
  'BASELINE_CLUSTER_EXPANSION_SEGMENT_COUNT=36' \
  'BASELINE_ETH_TARGET=12' \
  'BASELINE_SOL_TARGET=12' \
  'BASELINE_BTC_TARGET=4' \
  'BASELINE_LINK_TARGET=4' \
  'BASELINE_XRP_TARGET=4' \
  'NOMINAL_LOSS_CAP_R=0.75' \
  'NOMINAL_FULL_TP_R=2.5' \
  'GROSS_LOSS_CAP_AND_NET_PAYOFF_SEPARATED=true' \
  'REALIZED_PAYOFF_RATIO_AUDIT_REQUIRED=true' \
  'PERFORMANCE_BASED_SEGMENT_SELECTION_ALLOWED=false' \
  'SCALP_ENTRY_PREDICATE_MUTATION_ALLOWED=false' \
  'GRID_REBALANCE_STRATEGY_QUARANTINED=true' \
  'VOL_SHOCK_PERMANENT_BLOCK=true' \
  'PRODUCTION_ADMISSION_EXPANSION_ALLOWED=false' \
  'ENTRY_THRESHOLD_RELAXATION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'FULL_3600_REEXECUTION_ALLOWED=false' \
  'EVENT_REPLAY_2880_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_selective_chart_gate_geometry_counterfactual_plan/counterfactual_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_chart_causal_cluster_diagnose/causal_cluster_diagnose_v1.json" \
  "$ROOT/runtime/r7a4d2_short_expanded_candidate_stress_168/stress168_proof_v1.json" \
  "$ROOT/runtime/r7a4d2_short_candidate_repair_expanded_stress_plan/expanded_stress_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_execution_harness_plan/short_execution_harness_plan_v1.json" \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json" \
  "$ROOT/runtime/r7a4_simulation_replay_input_freeze/frozen_input_manifest_v1.json"
 do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-scalp-cf24-expand36.XXXXXX)" || exit 2
for path in \
  tools/r7a4d_historical_simulation_3600.py \
  tools/r7a4d2_entry_chain_minimal_patch.py \
  tools/r7a4d2_short_execution_harness_minimal_patch.py \
  tools/r7a4d2_short_rr_sidecar_patch.py \
  tools/r7a4d2_short_rr_exact_math_patch.py \
  tools/r7a4d2_short_fill_rebase_counterfactual_patch.py \
  tools/r7a4d2_short_observer_target_patch.py \
  tools/r7a4d2_short_candidate_trace_patch.py \
  tools/r7a4d2_short_discovery_trace_only_patch.py \
  tools/r7a4d2_market_segment_expansion_for_short_candidates.py \
  tools/r7a4d2_short_scalp_counterfactual24_baseline_expansion36.py \
  tools/r7a4d2_short_counterfactual_expansion_integrity_patch.py \
  tests/test_r7a4d2_short_rr_sidecar_counterfactual.py \
  tests/test_r7a4d2_short_discovery_trace_only_patch.py \
  tests/test_r7a4d2_short_scalp_counterfactual24_baseline_expansion36.py \
  backend/contracts/ZOS_R7A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE_v1.json \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile \
  "$TMP/tools/r7a4d2_entry_chain_minimal_patch.py" \
  "$TMP/tools/r7a4d2_short_execution_harness_minimal_patch.py" \
  "$TMP/tools/r7a4d2_short_rr_sidecar_patch.py" \
  "$TMP/tools/r7a4d2_short_rr_exact_math_patch.py" \
  "$TMP/tools/r7a4d2_short_fill_rebase_counterfactual_patch.py" \
  "$TMP/tools/r7a4d2_short_observer_target_patch.py" \
  "$TMP/tools/r7a4d2_short_candidate_trace_patch.py" \
  "$TMP/tools/r7a4d2_short_discovery_trace_only_patch.py" \
  "$TMP/tools/r7a4d2_market_segment_expansion_for_short_candidates.py" \
  "$TMP/tools/r7a4d2_short_scalp_counterfactual24_baseline_expansion36.py" \
  "$TMP/tools/r7a4d2_short_counterfactual_expansion_integrity_patch.py"; then
  echo 'STATE=HOLD_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4d2_entry_chain_minimal_patch.py" \
  --input "$TMP/tools/r7a4d_historical_simulation_3600.py" \
  --output "$TMP/tools/r7a4d2_entry_patched_runner.py" || exit 2
python3 "$TMP/tools/r7a4d2_short_execution_harness_minimal_patch.py" \
  --input "$TMP/tools/r7a4d2_entry_patched_runner.py" \
  --output "$TMP/tools/r7a4d2_dual_side_runner.py" || exit 2
python3 "$TMP/tools/r7a4d2_short_rr_sidecar_patch.py" \
  --input "$TMP/tools/r7a4d2_dual_side_runner.py" \
  --output "$TMP/tools/r7a4d2_rr_linear_runner.py" || exit 2
python3 "$TMP/tools/r7a4d2_short_rr_exact_math_patch.py" \
  --input "$TMP/tools/r7a4d2_rr_linear_runner.py" \
  --output "$TMP/tools/r7a4d2_rr_exact_runner.py" || exit 2

python3 "$TMP/tools/r7a4d2_short_fill_rebase_counterfactual_patch.py" \
  --input "$TMP/tools/r7a4d2_rr_exact_runner.py" \
  --output "$TMP/tools/r7a4d2_fill_rebase_runner.py" || exit 2
python3 "$TMP/tools/r7a4d2_short_observer_target_patch.py" \
  --input "$TMP/tools/r7a4d2_fill_rebase_runner.py" \
  --output "$TMP/tools/r7a4d2_scalp_cf24_runner.py" || exit 2

python3 "$TMP/tools/r7a4d2_short_candidate_trace_patch.py" \
  --input "$TMP/tools/r7a4d2_rr_exact_runner.py" \
  --output "$TMP/tools/r7a4d2_candidate_trace_runner.py" || exit 2
python3 "$TMP/tools/r7a4d2_short_discovery_trace_only_patch.py" \
  --input "$TMP/tools/r7a4d2_candidate_trace_runner.py" \
  --output "$TMP/tools/r7a4d2_baseline_expand36_runner.py" || exit 2

python3 "$TMP/tools/r7a4d2_short_counterfactual_expansion_integrity_patch.py" \
  --input "$TMP/tools/r7a4d2_short_scalp_counterfactual24_baseline_expansion36.py" \
  --output "$TMP/tools/r7a4d2_counterfactual_expansion_audited.py" || exit 2

if ! grep -q 'SHORT_FILL_REBASE_V1 = True' "$TMP/tools/r7a4d2_scalp_cf24_runner.py" || \
   ! grep -q 'SHORT_OBSERVER_TARGET_V1 = True' "$TMP/tools/r7a4d2_scalp_cf24_runner.py" || \
   ! grep -q 'SHORT_DISCOVERY_TRACE_ONLY_V1 = True' "$TMP/tools/r7a4d2_baseline_expand36_runner.py" || \
   ! grep -q 'GROSS_LOSS_CAP_AUDIT_V1 = True' "$TMP/tools/r7a4d2_counterfactual_expansion_audited.py"; then
  echo 'STATE=HOLD_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PATCH_MARKER_MISSING"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_RR_RUNNER="$TMP/tools/r7a4d2_scalp_cf24_runner.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_rr_sidecar_counterfactual.py"; then
  echo 'STATE=HOLD_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["RR_RUNNER_REGRESSION_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_DISCOVERY_PATCH="$TMP/tools/r7a4d2_short_discovery_trace_only_patch.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_discovery_trace_only_patch.py"; then
  echo 'STATE=HOLD_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["DISCOVERY_PATCH_REGRESSION_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_CF_EXPANSION_TOOL="$TMP/tools/r7a4d2_counterfactual_expansion_audited.py" \
  R7A4D2_FILL_REBASE_RUNNER="$TMP/tools/r7a4d2_scalp_cf24_runner.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_scalp_counterfactual24_baseline_expansion36.py"; then
  echo 'STATE=HOLD_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["COUNTERFACTUAL_EXPANSION_FOCUSED_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$ROOT:$TMP" python3 "$TMP/tools/r7a4d2_counterfactual_expansion_audited.py" \
  --root "$ROOT" \
  --stress-runner "$TMP/tools/r7a4d2_scalp_cf24_runner.py" \
  --discovery-runner "$TMP/tools/r7a4d2_baseline_expand36_runner.py" \
  --expansion-helper "$TMP/tools/r7a4d2_market_segment_expansion_for_short_candidates.py" \
  --a4c-contract "$TMP/backend/contracts/ZOS_R7A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE_v1.json" \
  --a4d-contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?

echo 'R7A4D2_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36_COMPLETE'
echo "RC=$RC"
exit "$RC"
