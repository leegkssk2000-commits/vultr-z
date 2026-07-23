#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
OUTDIR="$ROOT/runtime/r7a4d2_ma5_independent_oos_expansion"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/ma5_oos_${STAMP}.log"
TMP=""

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_MA5_INDEPENDENT_OOS_EXPANSION_START' \
  'MODE=READ_ONLY_DISJOINT_SOURCE_OR_STRICT_FORWARD_CHRONOLOGICAL_OOS' \
  'PERFORMANCE_BASED_SEGMENT_SELECTION_ALLOWED=false' \
  'VARIANT_ID=ma5_accel_15m_alignment' \
  'SIDE=long_only' \
  'SEGMENT_BARS=320' \
  'MAX_OOS_SEGMENTS=240' \
  'MIN_UNIQUE_EVENTS=24' \
  'MIN_SYMBOLS=3' \
  'EXPECTED_FOLDS=6' \
  'EXPECTED_STRESS_CELLS=6' \
  'PARAMETER_OPTIMIZATION_ALLOWED=false' \
  'EXIT_REPAIR_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'WORKTREE_POLICY=DO_NOT_TOUCH'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_MA5_INDEPENDENT_OOS_EXPANSION_INPUT'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json" \
  "$ROOT/runtime/r7a4_simulation_replay_input_freeze/frozen_input_manifest_v1.json" \
  "$ROOT/runtime/r7a4d2_incremental_defect4_ma5_side_specialization_6/ma5_side_specialization_summary_v1.json" \
  "$ROOT/runtime/r7a4d2_incremental_defect4_ma5_side_specialization_6/ma5_long_only_child_trade_rows_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_simplebot_benchmark_kill_test_6cell/simplebot_benchmark_kill_test_summary_v1.json" \
  "$ROOT/runtime/r7a4d2_short_economic_calibration_and_exchange_bot_benchmark_v2_plan/economic_calibration_and_exchange_bot_benchmark_v2_plan_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_MA5_INDEPENDENT_OOS_EXPANSION_INPUT'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

mkdir -p "$OUTDIR" || exit 2
TMP="$(mktemp -d /tmp/r7a4d2-ma5-oos.XXXXXX)" || exit 2

for path in \
  tools/r7a4d2_ma5_independent_oos_expansion.py \
  tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py \
  tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py \
  tools/r7a4d2_short_exchange_bot_benchmark_v2_execution_72.py \
  tools/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_execution_132.py \
  tools/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132.py \
  backend/contracts/ZOS_R7A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE_v1.json \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_MA5_INDEPENDENT_OOS_EXPANSION_INPUT'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

TARGET="$TMP/tools/r7a4d2_ma5_independent_oos_expansion.py"
RAW="$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py"
HELPER="$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py"
BENCHMARK="$TMP/tools/r7a4d2_short_exchange_bot_benchmark_v2_execution_72.py"
OLD="$TMP/tools/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_execution_132.py"
SECOND="$TMP/tools/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132.py"
A4C="$TMP/backend/contracts/ZOS_R7A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE_v1.json"
A4D="$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"

if ! python3 -m py_compile "$TARGET" "$RAW" "$HELPER" "$BENCHMARK" "$OLD" "$SECOND"; then
  echo 'STATE=HOLD_MA5_INDEPENDENT_OOS_EXPANSION_INPUT'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TARGET" \
  --self-test \
  --raw-module "$RAW" \
  --helper-module "$HELPER" \
  --benchmark-module "$BENCHMARK" \
  --old-uplift-module "$OLD" \
  --second-wave-module "$SECOND" \
  --a4c-contract "$A4C" \
  --a4d-contract "$A4D"; then
  echo 'STATE=HOLD_MA5_INDEPENDENT_OOS_EXPANSION_INPUT'
  echo 'BLOCKERS=["SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo "TARGET_SHA=$SHA"
echo "TARGET_SCRIPT_SHA256=$(sha256sum "$TARGET" | awk '{print $1}')"
echo "EXECUTION_LOG=$LOG"
echo 'MA5_OOS_EXECUTION_START=true'

python3 "$TARGET" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --raw-module "$RAW" \
  --helper-module "$HELPER" \
  --benchmark-module "$BENCHMARK" \
  --old-uplift-module "$OLD" \
  --second-wave-module "$SECOND" \
  --a4c-contract "$A4C" \
  --a4d-contract "$A4D" \
  2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}

echo
echo '===== MA5 INDEPENDENT OOS SUMMARY ====='
grep -E '^(STATE=|BLOCKER_COUNT=|OOS_CLASSIFICATION=|STRICT_FORWARD_OOS_SEGMENT_COUNT=|UNIQUE_LONG_SIGNAL_COUNT=|SIGNAL_SYMBOL_COUNT=|SIGNAL_FOLD_COUNT=|COVERAGE_CHECKS=|STRESS_CELL_COUNT=|BASE_NET_R=|ADVERSE_NET_R=|SEVERE_NET_R=|WORST_SEVERE_CELL=|PROFILE_CHECKS=|ROBUST_SURVIVOR=|CONDITIONAL_SURVIVOR=|MUTATION_PATH_COUNT=|SUMMARY_JSON=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 100

echo "FINAL_RC=$RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$RC"
