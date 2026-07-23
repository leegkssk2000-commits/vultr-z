#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
OUTDIR="$ROOT/runtime/r7a4d2_ma5_oos_market_source_coverage_expansion"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/coverage_and_oos_${STAMP}.log"
TMP=""

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_MA5_OOS_MARKET_SOURCE_COVERAGE_EXPANSION_START' \
  'MODE=PUBLIC_BINGX_READ_ONLY_ACQUISITION_PLUS_TEMPORARY_OOS_OVERLAY' \
  'PRIVATE_API_KEY_REQUIRED=false' \
  'ORDER_AUTHORITY_USED=false' \
  'SOURCE_WINDOW=LATEST_FIXED_30D_STRICTLY_AFTER_DISCOVERY' \
  'SYMBOL_SELECTION=DISCOVERY_SYMBOLS_THEN_FIXED_FALLBACK' \
  'MIN_SYMBOLS=3' \
  'INTERVAL=1m' \
  'ORIGINAL_FROZEN_MANIFEST_MUTATION_ALLOWED=false' \
  'SELECTED_MANIFEST_MUTATION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'WORKTREE_POLICY=DO_NOT_TOUCH'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_MA5_OOS_MARKET_SOURCE_COVERAGE_EXPANSION_INPUT'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json" \
  "$ROOT/runtime/r7a4_simulation_replay_input_freeze/frozen_input_manifest_v1.json" \
  "$ROOT/runtime/r7a4d2_ma5_independent_oos_expansion/ma5_independent_oos_summary_v1.json" \
  "$ROOT/runtime/r7a4d2_incremental_defect4_ma5_side_specialization_6/ma5_side_specialization_summary_v1.json" \
  "$ROOT/runtime/r7a4d2_incremental_defect4_ma5_side_specialization_6/ma5_long_only_child_trade_rows_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_simplebot_benchmark_kill_test_6cell/simplebot_benchmark_kill_test_summary_v1.json" \
  "$ROOT/runtime/r7a4d2_short_economic_calibration_and_exchange_bot_benchmark_v2_plan/economic_calibration_and_exchange_bot_benchmark_v2_plan_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_MA5_OOS_MARKET_SOURCE_COVERAGE_EXPANSION_INPUT'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

mkdir -p "$OUTDIR" || exit 2
TMP="$(mktemp -d /tmp/r7a4d2-ma5-oos-coverage.XXXXXX)" || exit 2

for path in \
  tools/r7a4d2_ma5_oos_market_source_coverage_expansion.py \
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
    echo 'STATE=HOLD_MA5_OOS_MARKET_SOURCE_COVERAGE_EXPANSION_INPUT'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

EXPAND="$TMP/tools/r7a4d2_ma5_oos_market_source_coverage_expansion.py"
TARGET="$TMP/tools/r7a4d2_ma5_independent_oos_expansion.py"
RAW="$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py"
HELPER="$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py"
BENCHMARK="$TMP/tools/r7a4d2_short_exchange_bot_benchmark_v2_execution_72.py"
OLD="$TMP/tools/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_execution_132.py"
SECOND="$TMP/tools/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132.py"
A4C="$TMP/backend/contracts/ZOS_R7A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE_v1.json"
A4D="$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"

if ! python3 -m py_compile "$EXPAND" "$TARGET" "$RAW" "$HELPER" "$BENCHMARK" "$OLD" "$SECOND"; then
  echo 'STATE=HOLD_MA5_OOS_MARKET_SOURCE_COVERAGE_EXPANSION_INPUT'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo "TARGET_SHA=$SHA"
echo "EXPANSION_SCRIPT_SHA256=$(sha256sum "$EXPAND" | awk '{print $1}')"
echo "OOS_SCRIPT_BASE_SHA256=$(sha256sum "$TARGET" | awk '{print $1}')"
echo "EXECUTION_LOG=$LOG"
echo 'MARKET_SOURCE_EXPANSION_EXECUTION_START=true'

python3 "$EXPAND" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  2>&1 | tee "$LOG"
EXPAND_RC=${PIPESTATUS[0]}

if [[ "$EXPAND_RC" -ne 0 ]]; then
  echo
  echo '===== MARKET SOURCE COVERAGE SUMMARY ====='
  grep -E '^(STATE=|DISCOVERY_GLOBAL_END_MS=|OOS_START_MS=|OOS_END_MS=|REQUESTED_SYMBOLS=|GENERATED_SOURCE_COUNT=|GENERATED_SEGMENT_CAPACITY=|SOURCE=|MUTATION_PATH_COUNT=|OVERLAY_MANIFEST=|SUMMARY_JSON=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 120
  echo "FINAL_RC=$EXPAND_RC"
  echo "FULL_LOG=$LOG"
  exit "$EXPAND_RC"
fi

python3 - "$TARGET" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

old_manifest = 'FROZEN_MANIFEST = Path("runtime/r7a4_simulation_replay_input_freeze/frozen_input_manifest_v1.json")'
new_manifest = 'FROZEN_MANIFEST = Path("runtime/r7a4d2_ma5_oos_market_source_coverage_expansion/oos_overlay_frozen_input_manifest_v1.json")'
if text.count(old_manifest) != 1:
    raise SystemExit("OOS_OVERLAY_MANIFEST_PATCH_ANCHOR_INVALID")
text = text.replace(old_manifest, new_manifest, 1)

old_zero = '(int(kill_summary.get("blocker_count") or -1) == 0, "KILL_TEST_BLOCKED"),'
new_zero = '(int(kill_summary.get("blocker_count", -1)) == 0, "KILL_TEST_BLOCKED"),'
if old_zero in text:
    text = text.replace(old_zero, new_zero, 1)
elif new_zero not in text:
    raise SystemExit("OOS_KILL_ZERO_PATCH_ANCHOR_INVALID")

path.write_text(text, encoding="utf-8")
PY
PATCH_RC=$?

if [[ "$PATCH_RC" -ne 0 ]]; then
  echo 'STATE=HOLD_MA5_OOS_OVERLAY_BIND'
  echo 'BLOCKERS=["OOS_TEMPORARY_PATCH_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo 'STATE=PASS_MA5_OOS_OVERLAY_BIND'
echo 'OVERLAY_PATH=runtime/r7a4d2_ma5_oos_market_source_coverage_expansion/oos_overlay_frozen_input_manifest_v1.json'
echo 'PATCH_SCOPE=temporary_oos_copy_only'

if ! python3 -m py_compile "$TARGET"; then
  echo 'STATE=HOLD_MA5_OOS_OVERLAY_BIND'
  echo 'BLOCKERS=["PATCHED_OOS_COMPILE_FAILED"]'
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
  echo 'STATE=HOLD_MA5_OOS_OVERLAY_BIND'
  echo 'BLOCKERS=["PATCHED_OOS_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo 'MA5_OOS_OVERLAY_REPLAY_START=true'

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
  2>&1 | tee -a "$LOG"
OOS_RC=${PIPESTATUS[0]}

echo
echo '===== MARKET SOURCE + OOS FINAL SUMMARY ====='
grep -E '^(STATE=|DISCOVERY_GLOBAL_END_MS=|OOS_START_MS=|OOS_END_MS=|REQUESTED_SYMBOLS=|GENERATED_SOURCE_COUNT=|GENERATED_SEGMENT_CAPACITY=|SOURCE=|OOS_CLASSIFICATION=|STRICT_FORWARD_OOS_SEGMENT_COUNT=|UNIQUE_LONG_SIGNAL_COUNT=|SIGNAL_SYMBOL_COUNT=|SIGNAL_FOLD_COUNT=|COVERAGE_CHECKS=|STRESS_CELL_COUNT=|BASE_NET_R=|ADVERSE_NET_R=|SEVERE_NET_R=|WORST_SEVERE_CELL=|PROFILE_CHECKS=|ROBUST_SURVIVOR=|CONDITIONAL_SURVIVOR=|MUTATION_PATH_COUNT=|SUMMARY_JSON=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 180

echo "FINAL_RC=$OOS_RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$OOS_RC"
