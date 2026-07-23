#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
OUTDIR="$ROOT/runtime/r7a4d2_remaining_survivor_independent_oos_batch_execution"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/remaining_oos_batch_${STAMP}.log"
TMP=""

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH_EXECUTION_START' \
  'MODE=READ_ONLY_FIXED_10_CANDIDATE_STRICT_FORWARD_OOS_BATCH' \
  'CANDIDATE_COUNT=10' \
  'STRICT_FORWARD_SEGMENTS=240' \
  'STRESS_CELLS_PER_CANDIDATE=6' \
  'TOTAL_EXPECTED_CELLS=60' \
  'PARAMETER_OPTIMIZATION_ALLOWED=false' \
  'CANDIDATE_RESELECTION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'WORKTREE_POLICY=DO_NOT_TOUCH'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH_INPUT'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

mkdir -p "$OUTDIR" || exit 2
TMP="$(mktemp -d /tmp/r7a4d2-remaining-oos-batch.XXXXXX)" || exit 2

for path in \
  tools/r7a4d2_remaining_survivor_independent_oos_batch_execution.py \
  tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py \
  tools/r7a4d2_short_exchange_bot_benchmark_v2_execution_72.py \
  tools/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_execution_132.py \
  tools/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132.py \
  tools/r7a4d2_ma5_independent_oos_expansion.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH_INPUT'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
 done

TARGET="$TMP/tools/r7a4d2_remaining_survivor_independent_oos_batch_execution.py"
RAW="$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py"
BENCHMARK="$TMP/tools/r7a4d2_short_exchange_bot_benchmark_v2_execution_72.py"
OLD="$TMP/tools/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_execution_132.py"
SECOND="$TMP/tools/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132.py"
OOS="$TMP/tools/r7a4d2_ma5_independent_oos_expansion.py"
A4D="$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"

if ! python3 -m py_compile "$TARGET" "$RAW" "$BENCHMARK" "$OLD" "$SECOND" "$OOS"; then
  echo 'STATE=HOLD_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH_INPUT'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo "TARGET_SHA=$SHA"
echo "TARGET_SCRIPT_SHA256=$(sha256sum "$TARGET" | awk '{print $1}')"
echo "EXECUTION_LOG=$LOG"

if ! python3 "$TARGET" \
  --self-test \
  --target-sha "$SHA" \
  --raw-module "$RAW" \
  --benchmark-module "$BENCHMARK" \
  --old-uplift-module "$OLD" \
  --second-wave-module "$SECOND" \
  --oos-module "$OOS" \
  --a4d-contract "$A4D"; then
  echo 'STATE=HOLD_REMAINING_SURVIVOR_INDEPENDENT_OOS_BATCH_INPUT'
  echo 'BLOCKERS=["SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo 'REMAINING_OOS_BATCH_EXECUTION_START=true'
python3 "$TARGET" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --raw-module "$RAW" \
  --benchmark-module "$BENCHMARK" \
  --old-uplift-module "$OLD" \
  --second-wave-module "$SECOND" \
  --oos-module "$OOS" \
  --a4d-contract "$A4D" \
  2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}

echo
echo '===== REMAINING SURVIVOR OOS BATCH SUMMARY ====='
grep -E '^(STATE=|BLOCKER_COUNT=|STRICT_FORWARD_OOS_SEGMENT_COUNT=|OOS_CANDIDATE_COUNT=|EXPECTED_TOTAL_STRESS_CELLS=|ACTUAL_CELL_ROW_COUNT=|ROBUST_SURVIVOR_COUNT=|CONDITIONAL_SURVIVOR_COUNT=|OBSERVER_RETIRE_COUNT=|OOS_RESULT=|MUTATION_PATH_COUNT=|SUMMARY_JSON=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 240

echo "FINAL_RC=$RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$RC"
