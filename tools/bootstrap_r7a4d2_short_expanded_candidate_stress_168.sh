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
  'R7A4D2_SHORT_EXPANDED_CANDIDATE_STRESS_168_START' \
  'MODE=READ_ONLY_ISOLATED_EXPANDED_CANDIDATE_MULTI_AXIS_STRESS' \
  'TARGETED_CANDIDATE_COUNT=28' \
  'COST_AXIS_COUNT=3' \
  'PERTURBATION_AXIS_COUNT=2' \
  'TARGETED_CELL_COUNT=168' \
  'BASELINE_TARGET_PARITY_REQUIRED=28' \
  'AXIS_REPEATS_CREATE_INDEPENDENT_SAMPLES=false' \
  'SHORT_POLICY_LOSS_CAP_R=0.75' \
  'SHORT_POLICY_FULL_TP_R=2.5' \
  'GRID_REBALANCE_STRATEGY_QUARANTINED=true' \
  'NEGATIVE_PAIR_ADMISSION_ALLOWED=false' \
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
  echo 'STATE=HOLD_SHORT_EXPANDED_CANDIDATE_STRESS_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_candidate_repair_expanded_stress_plan/expanded_stress_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_market_segment_expansion_for_short_candidates/market_segment_expansion_v1.json" \
  "$ROOT/runtime/r7a4d2_short_admission_candidate_stress_66/stress66_proof_v1.json" \
  "$ROOT/runtime/r7a4d2_short_admission_allowlist_plan/allowlist_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_execution_harness_plan/short_execution_harness_plan_v1.json"
 do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_EXPANDED_CANDIDATE_STRESS_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-stress168.XXXXXX)" || exit 2
for path in \
  tools/r7a4d_historical_simulation_3600.py \
  tools/r7a4d2_entry_chain_minimal_patch.py \
  tools/r7a4d2_short_execution_harness_minimal_patch.py \
  tools/r7a4d2_short_rr_sidecar_patch.py \
  tools/r7a4d2_short_rr_exact_math_patch.py \
  tools/r7a4d2_short_observer_target_patch.py \
  tools/r7a4d2_short_expanded_candidate_stress_168.py \
  tests/test_r7a4d2_short_rr_sidecar_counterfactual.py \
  tests/test_r7a4d2_short_expanded_candidate_stress_168.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_EXPANDED_CANDIDATE_STRESS_INPUT'
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
  "$TMP/tools/r7a4d2_short_observer_target_patch.py" \
  "$TMP/tools/r7a4d2_short_expanded_candidate_stress_168.py"; then
  echo 'STATE=HOLD_SHORT_EXPANDED_CANDIDATE_STRESS_INPUT'
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
  --output "$TMP/tools/r7a4d2_rr_runner.py" || exit 2

python3 "$TMP/tools/r7a4d2_short_observer_target_patch.py" \
  --input "$TMP/tools/r7a4d2_rr_runner.py" \
  --output "$TMP/tools/r7a4d2_stress168_runner.py" || exit 2

if ! grep -q 'SHORT_OBSERVER_TARGET_V1 = True' "$TMP/tools/r7a4d2_stress168_runner.py"; then
  echo 'STATE=HOLD_SHORT_EXPANDED_CANDIDATE_STRESS_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["STRESS168_RUNNER_MARKER_MISSING"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_RR_RUNNER="$TMP/tools/r7a4d2_stress168_runner.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_rr_sidecar_counterfactual.py"; then
  echo 'STATE=HOLD_SHORT_EXPANDED_CANDIDATE_STRESS_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["RUNNER_REGRESSION_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_STRESS168="$TMP/tools/r7a4d2_short_expanded_candidate_stress_168.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_expanded_candidate_stress_168.py"; then
  echo 'STATE=HOLD_SHORT_EXPANDED_CANDIDATE_STRESS_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["STRESS168_AGGREGATION_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$ROOT:$TMP" python3 "$TMP/tools/r7a4d2_short_expanded_candidate_stress_168.py" \
  --root "$ROOT" \
  --runner "$TMP/tools/r7a4d2_stress168_runner.py" \
  --contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?

echo 'R7A4D2_SHORT_EXPANDED_CANDIDATE_STRESS_168_COMPLETE'
echo "RC=$RC"
exit "$RC"
