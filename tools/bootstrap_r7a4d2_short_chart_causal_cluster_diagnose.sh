#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
TMP=""
RC=2
PATCHED_DIAG=""

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_SHORT_CHART_CAUSAL_CLUSTER_DIAGNOSE_START' \
  'MODE=READ_ONLY_UNSUPERVISED_CHART_CLUSTER_AND_SCALP_FILL_GEOMETRY_TRACE' \
  'TARGETED_CANDIDATE_COUNT=28' \
  'BASELINE_CLUSTER_USES_PRE_ENTRY_FEATURES_ONLY=true' \
  'FUTURE_OUTCOME_USED_TO_FIT_CLUSTERS=false' \
  'FUTURE_OUTCOME_USED_TO_EVALUATE_CLUSTERS=true' \
  'BASELINE_CLUSTER_K_CANDIDATES=2,3' \
  'BASELINE_LEAVE_ONE_SOURCE_OUT_REQUIRED=true' \
  'SCALP_GEOMETRY_STRESS_PROOF_PARITY_REQUIRED=true' \
  'SCALP_REBASE_IS_COUNTERFACTUAL_ONLY=true' \
  'JSON_SAFE_NUMPY_SCALAR_RECURSION_REQUIRED=true' \
  'GRID_REBALANCE_STRATEGY_QUARANTINED=true' \
  'VOL_SHOCK_PERMANENT_BLOCK=true' \
  'VOL_COMPONENTS_OBSERVER_ONLY=true' \
  'FAILURE_LEARNING_CONNECTION_ALLOWED=false' \
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
  echo 'STATE=HOLD_SHORT_CHART_CAUSAL_CLUSTER_DIAGNOSE_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_chart_structure_forensics/chart_forensics_v1.json" \
  "$ROOT/runtime/r7a4d2_short_chart_structure_forensics/chart_atlas_v1.json" \
  "$ROOT/runtime/r7a4d2_short_expanded_candidate_stress_168/stress168_proof_v1.json" \
  "$ROOT/runtime/r7a4d2_short_candidate_repair_expanded_stress_plan/expanded_stress_plan_v1.json"
 do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_CHART_CAUSAL_CLUSTER_DIAGNOSE_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-chart-causal-cluster.XXXXXX)" || exit 2
for path in \
  tools/r7a4d_historical_simulation_3600.py \
  tools/r7a4d2_short_chart_causal_cluster_diagnose.py \
  tools/r7a4d2_chart_causal_cluster_json_safe_patch.py \
  tests/test_r7a4d2_short_chart_causal_cluster_diagnose.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_CHART_CAUSAL_CLUSTER_DIAGNOSE_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

PATCHED_DIAG="$TMP/tools/r7a4d2_short_chart_causal_cluster_diagnose_jsonsafe.py"
if ! python3 "$TMP/tools/r7a4d2_chart_causal_cluster_json_safe_patch.py" \
  --input "$TMP/tools/r7a4d2_short_chart_causal_cluster_diagnose.py" \
  --output "$PATCHED_DIAG"; then
  echo 'STATE=HOLD_SHORT_CHART_CAUSAL_CLUSTER_DIAGNOSE_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["JSON_SAFE_PATCH_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile \
  "$TMP/tools/r7a4d_historical_simulation_3600.py" \
  "$TMP/tools/r7a4d2_chart_causal_cluster_json_safe_patch.py" \
  "$PATCHED_DIAG"; then
  echo 'STATE=HOLD_SHORT_CHART_CAUSAL_CLUSTER_DIAGNOSE_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_CAUSAL_CLUSTER="$PATCHED_DIAG" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_chart_causal_cluster_diagnose.py"; then
  echo 'STATE=HOLD_SHORT_CHART_CAUSAL_CLUSTER_DIAGNOSE_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["CAUSAL_CLUSTER_FOCUSED_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$TMP:$ROOT" python3 "$PATCHED_DIAG" \
  --root "$ROOT" \
  --runner "$TMP/tools/r7a4d_historical_simulation_3600.py" \
  --contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?

echo 'R7A4D2_SHORT_CHART_CAUSAL_CLUSTER_DIAGNOSE_COMPLETE'
echo "RC=$RC"
exit "$RC"
