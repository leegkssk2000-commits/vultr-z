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
  'R7A4D2_SHORT_SIGNAL_FREQUENCY_AND_ADMISSION_CLOSURE_START' \
  'MODE=READ_ONLY_ISOLATED_BLOCKED_FLAT_ENTER_OBSERVER_REPLAY' \
  'OBSERVER_CANDIDATE_TARGET=158' \
  'CANDIDATE_INTERFERENCE_ALLOWED=false' \
  'SHORT_POLICY_LOSS_CAP_R=0.75' \
  'SHORT_POLICY_FULL_TP_R=2.5' \
  'GRID_REBALANCE_QUARANTINED=true' \
  'ADMISSION_EXPANSION_ALLOWED=false' \
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
  echo 'STATE=HOLD_SHORT_ADMISSION_OBSERVER_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_no_trigger_market_coverage_diagnose/coverage_diagnose_v1.json" \
  "$ROOT/runtime/r7a4d2_short_rr_sidecar_counterfactual/counterfactual_proof_v1.json" \
  "$ROOT/runtime/r7a4d2_short_execution_harness_plan/short_execution_harness_plan_v1.json"
 do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_ADMISSION_OBSERVER_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-admission-observer.XXXXXX)" || exit 2
for path in \
  tools/r7a4d_historical_simulation_3600.py \
  tools/r7a4d2_entry_chain_minimal_patch.py \
  tools/r7a4d2_short_execution_harness_minimal_patch.py \
  tools/r7a4d2_short_rr_sidecar_patch.py \
  tools/r7a4d2_short_rr_exact_math_patch.py \
  tools/r7a4d2_short_observer_target_patch.py \
  tools/r7a4d2_short_signal_frequency_admission_closure.py \
  tests/test_r7a4d2_short_rr_sidecar_counterfactual.py \
  tests/test_r7a4d2_short_signal_frequency_admission_closure.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_ADMISSION_OBSERVER_INPUT'
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
  "$TMP/tools/r7a4d2_short_signal_frequency_admission_closure.py"; then
  echo 'STATE=HOLD_SHORT_ADMISSION_OBSERVER_INPUT'
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
  --output "$TMP/tools/r7a4d2_rr_sidecar_linear_runner.py" || exit 2

python3 "$TMP/tools/r7a4d2_short_rr_exact_math_patch.py" \
  --input "$TMP/tools/r7a4d2_rr_sidecar_linear_runner.py" \
  --output "$TMP/tools/r7a4d2_rr_sidecar_runner.py" || exit 2

python3 "$TMP/tools/r7a4d2_short_observer_target_patch.py" \
  --input "$TMP/tools/r7a4d2_rr_sidecar_runner.py" \
  --output "$TMP/tools/r7a4d2_admission_observer_runner.py" || exit 2

if ! grep -q 'SHORT_OBSERVER_TARGET_V1 = True' "$TMP/tools/r7a4d2_admission_observer_runner.py"; then
  echo 'STATE=HOLD_SHORT_ADMISSION_OBSERVER_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["OBSERVER_RUNNER_MARKER_MISSING"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_RR_RUNNER="$TMP/tools/r7a4d2_admission_observer_runner.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_rr_sidecar_counterfactual.py"; then
  echo 'STATE=HOLD_SHORT_ADMISSION_OBSERVER_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["OBSERVER_RUNNER_REGRESSION_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_ADMISSION_CLOSURE="$TMP/tools/r7a4d2_short_signal_frequency_admission_closure.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_signal_frequency_admission_closure.py"; then
  echo 'STATE=HOLD_SHORT_ADMISSION_OBSERVER_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["ADMISSION_CLASSIFICATION_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$ROOT:$TMP" python3 "$TMP/tools/r7a4d2_short_signal_frequency_admission_closure.py" \
  --root "$ROOT" \
  --runner "$TMP/tools/r7a4d2_admission_observer_runner.py" \
  --contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?

echo 'R7A4D2_SHORT_SIGNAL_FREQUENCY_AND_ADMISSION_CLOSURE_COMPLETE'
echo "RC=$RC"
exit "$RC"
