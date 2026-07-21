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
  'R7A4D2_SHORT_MISMATCH_PERFORMANCE_DIAGNOSE_START' \
  'MODE=READ_ONLY_LONG_BASELINE_600_AND_EXISTING_DUAL_PROOF_ANALYSIS' \
  'SHORT_REEXECUTION_ALLOWED=false' \
  'LONG_BASELINE_REPLAY_SCENARIOS=600' \
  'FULL_3600_REEXECUTION_ALLOWED=false' \
  'EVENT_REPLAY_2880_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_MISMATCH_PERFORMANCE_DIAGNOSE_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  runtime/r7a4d2_short_execution_harness_verify/short_execution_harness_proof_v1.json \
  runtime/r7a4d2_entry_chain_minimal_patch_verify/entry_chain_patch_proof_v1.json \
  runtime/r7a4d2_short_execution_harness_plan/short_execution_harness_plan_v1.json
 do
  if [[ ! -f "$ROOT/$required" ]]; then
    echo 'STATE=HOLD_SHORT_MISMATCH_PERFORMANCE_DIAGNOSE_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["RUNTIME_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-perf.XXXXXX)" || exit 2
for path in \
  tools/r7a4d_historical_simulation_3600.py \
  tools/r7a4d2_entry_chain_minimal_patch.py \
  tools/r7a4d2_short_execution_harness_minimal_patch.py \
  tools/r7a4d2_short_harness_mismatch_performance_diagnose.py \
  tests/test_r7a4d2_short_harness_mismatch_performance_diagnose.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_MISMATCH_PERFORMANCE_DIAGNOSE_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile \
  "$TMP/tools/r7a4d2_entry_chain_minimal_patch.py" \
  "$TMP/tools/r7a4d2_short_execution_harness_minimal_patch.py" \
  "$TMP/tools/r7a4d2_short_harness_mismatch_performance_diagnose.py"; then
  echo 'STATE=HOLD_SHORT_MISMATCH_PERFORMANCE_DIAGNOSE_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TMP/tools/r7a4d2_entry_chain_minimal_patch.py" \
  --input "$TMP/tools/r7a4d_historical_simulation_3600.py" \
  --output "$TMP/tools/r7a4d2_entry_patched_runner.py"; then
  echo 'STATE=HOLD_SHORT_MISMATCH_PERFORMANCE_DIAGNOSE_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["ENTRY_CHAIN_PATCH_BUILD_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TMP/tools/r7a4d2_short_execution_harness_minimal_patch.py" \
  --input "$TMP/tools/r7a4d2_entry_patched_runner.py" \
  --output "$TMP/tools/r7a4d2_dual_side_runner.py"; then
  echo 'STATE=HOLD_SHORT_MISMATCH_PERFORMANCE_DIAGNOSE_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["SHORT_PATCH_BUILD_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_SHORT_PERF_DIAG="$TMP/tools/r7a4d2_short_harness_mismatch_performance_diagnose.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_harness_mismatch_performance_diagnose.py"; then
  echo 'STATE=HOLD_SHORT_MISMATCH_PERFORMANCE_DIAGNOSE_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$ROOT:$TMP" python3 "$TMP/tools/r7a4d2_short_harness_mismatch_performance_diagnose.py" \
  --root "$ROOT" \
  --runner "$TMP/tools/r7a4d2_dual_side_runner.py" \
  --contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?

echo 'R7A4D2_SHORT_MISMATCH_PERFORMANCE_DIAGNOSE_COMPLETE'
echo "RC=$RC"
exit "$RC"
