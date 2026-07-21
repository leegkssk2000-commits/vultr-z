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
  'R7A4D2_SHORT_ADMISSION_CANDIDATE_STRESS_66_START' \
  'MODE=READ_ONLY_ISOLATED_CANDIDATE_MULTI_AXIS_STRESS' \
  'STRESS_CANDIDATE_COUNT=11' \
  'COST_AXIS_COUNT=3' \
  'PERTURBATION_AXIS_COUNT=2' \
  'TARGETED_CELL_COUNT=66' \
  'AXIS_REPEATS_CREATE_INDEPENDENT_SAMPLES=false' \
  'FULL_11_CANDIDATE_BASELINE_PARITY_REQUIRED=true' \
  'GRID_REBALANCE_QUARANTINED=true' \
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
  echo 'STATE=HOLD_SHORT_ADMISSION_CANDIDATE_STRESS_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_admission_allowlist_plan/allowlist_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_signal_frequency_admission_closure/admission_closure_v1.json" \
  "$ROOT/runtime/r7a4d2_no_trigger_market_coverage_diagnose/coverage_diagnose_v1.json" \
  "$ROOT/runtime/r7a4d2_short_execution_harness_plan/short_execution_harness_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_rr_sidecar_counterfactual/policy_results_600_v1.jsonl"
 do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_ADMISSION_CANDIDATE_STRESS_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-stress66.XXXXXX)" || exit 2
for path in \
  tools/r7a4d_historical_simulation_3600.py \
  tools/r7a4d2_entry_chain_minimal_patch.py \
  tools/r7a4d2_short_execution_harness_minimal_patch.py \
  tools/r7a4d2_short_rr_sidecar_patch.py \
  tools/r7a4d2_short_rr_exact_math_patch.py \
  tools/r7a4d2_short_observer_target_patch.py \
  tools/r7a4d2_short_admission_candidate_stress_66.py \
  tools/r7a4d2_short_stress66_baseline_parity_audit.py \
  tests/test_r7a4d2_short_rr_sidecar_counterfactual.py \
  tests/test_r7a4d2_short_admission_candidate_stress_66.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_ADMISSION_CANDIDATE_STRESS_INPUT'
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
  "$TMP/tools/r7a4d2_short_admission_candidate_stress_66.py" \
  "$TMP/tools/r7a4d2_short_stress66_baseline_parity_audit.py"; then
  echo 'STATE=HOLD_SHORT_ADMISSION_CANDIDATE_STRESS_INPUT'
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
  --output "$TMP/tools/r7a4d2_stress66_runner.py" || exit 2

if ! grep -q 'SHORT_OBSERVER_TARGET_V1 = True' "$TMP/tools/r7a4d2_stress66_runner.py"; then
  echo 'STATE=HOLD_SHORT_ADMISSION_CANDIDATE_STRESS_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["STRESS_RUNNER_MARKER_MISSING"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_RR_RUNNER="$TMP/tools/r7a4d2_stress66_runner.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_rr_sidecar_counterfactual.py"; then
  echo 'STATE=HOLD_SHORT_ADMISSION_CANDIDATE_STRESS_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["RUNNER_REGRESSION_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_STRESS66="$TMP/tools/r7a4d2_short_admission_candidate_stress_66.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_admission_candidate_stress_66.py"; then
  echo 'STATE=HOLD_SHORT_ADMISSION_CANDIDATE_STRESS_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["STRESS_AGGREGATION_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$ROOT:$TMP" python3 "$TMP/tools/r7a4d2_short_admission_candidate_stress_66.py" \
  --root "$ROOT" \
  --runner "$TMP/tools/r7a4d2_stress66_runner.py" \
  --contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?
if [[ "$RC" -ne 0 ]]; then
  echo 'R7A4D2_SHORT_ADMISSION_CANDIDATE_STRESS_66_COMPLETE'
  echo "RC=$RC"
  exit "$RC"
fi

python3 "$TMP/tools/r7a4d2_short_stress66_baseline_parity_audit.py" --root "$ROOT"
RC=$?

echo 'R7A4D2_SHORT_ADMISSION_CANDIDATE_STRESS_66_COMPLETE'
echo "RC=$RC"
exit "$RC"
