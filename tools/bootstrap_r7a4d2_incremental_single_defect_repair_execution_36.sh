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
  'R7A4D2_INCREMENTAL_SINGLE_DEFECT_REPAIR_EXECUTION_36_START' \
  'MODE=READ_ONLY_SIX_LANE_CONTROL_RESTORE_OR_SINGLE_COST_DEFENSE' \
  'EXPECTED_SELECTED_LANE_COUNT=6' \
  'EXPECTED_STRESS_CELL_PER_LANE=6' \
  'EXPECTED_CELL_COUNT=36' \
  'SECOND_WAVE_BEST_SOFAR_IS_CONTROL=true' \
  'THIRD_WAVE_REJECTED_VARIANT_IS_COMPARATOR=true' \
  'CONTROL_SIGNAL_SET_RESTORED_FOR_REGRESSION_LANES=true' \
  'ONE_COST_DEFENSE_ONLY_FOR_COST_FRAGILITY_LANES=true' \
  'BASELINE_MUST_NOT_DEGRADE=true' \
  'ATR5_CONTROL_PRESERVED=true' \
  'DONCHIAN15_REFERENCE_PRESERVED=true' \
  'KEEP14_UNTOUCHED=true' \
  'SAME_FROZEN_DATA_AND_COSTS_REQUIRED=true' \
  'NO_STOP_WIDENING=true' \
  'NO_ENTRY_THRESHOLD_RELAXATION=true' \
  'NO_PARAMETER_OPTIMIZATION=true' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'MARKET_SOURCE_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_INCREMENTAL_SINGLE_DEFECT_REPAIR_EXECUTION_36_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_incremental_defect_ablation_audit/incremental_defect_ablation_audit_v1.json" \
  "$ROOT/runtime/r7a4d2_short_economic_calibration_and_exchange_bot_benchmark_v2_plan/economic_calibration_and_exchange_bot_benchmark_v2_plan_v1.json" \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_INCREMENTAL_SINGLE_DEFECT_REPAIR_EXECUTION_36_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-incremental-single-defect.XXXXXX)" || exit 2

for path in \
  tools/r7a4d2_incremental_single_defect_repair_execution_36.py \
  tools/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132.py \
  tools/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_execution_132.py \
  tools/r7a4d2_short_exchange_bot_benchmark_v2_execution_72.py \
  tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py \
  tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_INCREMENTAL_SINGLE_DEFECT_REPAIR_EXECUTION_36_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

TARGET="$TMP/tools/r7a4d2_incremental_single_defect_repair_execution_36.py"
SECOND="$TMP/tools/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132.py"
INDICATOR="$TMP/tools/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_execution_132.py"
BENCHMARK="$TMP/tools/r7a4d2_short_exchange_bot_benchmark_v2_execution_72.py"
RAW="$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py"
HELPER="$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py"
CONTRACT="$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"

if ! python3 - "$INDICATOR" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
anchor = 'def context_columns(frame5: pd.DataFrame, frame15: pd.DataFrame) -> pd.DataFrame:\n    base = frame5.copy()\n'
replacement = 'def context_columns(frame5: pd.DataFrame, frame15: pd.DataFrame) -> pd.DataFrame:\n    base = frame5.copy()\n    base["__timestamp"] = pd.to_numeric(base["__timestamp"], errors="raise").astype("float64")\n'
if text.count(anchor) != 1:
    raise SystemExit(f"TIMESTAMP_PATCH_ANCHOR_INVALID:{text.count(anchor)}")
path.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")
PY
then
  echo 'STATE=HOLD_INCREMENTAL_SINGLE_DEFECT_REPAIR_EXECUTION_36_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["INDICATOR_TIMESTAMP_NORMALIZATION_PATCH_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo 'STATE=PASS_INCREMENTAL_SINGLE_DEFECT_INDICATOR_TIMESTAMP_NORMALIZATION'
echo 'TIMESTAMP_DTYPE=left_float64,right_float64'
echo 'PATCH_SCOPE=temporary_indicator_copy_only'

if ! python3 -m py_compile "$TARGET" "$SECOND" "$INDICATOR" "$BENCHMARK" "$RAW" "$HELPER"; then
  echo 'STATE=HOLD_INCREMENTAL_SINGLE_DEFECT_REPAIR_EXECUTION_36_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 - "$INDICATOR" <<'PY'
import importlib.util
import sys
from pathlib import Path

path = Path(sys.argv[1]).resolve()
spec = importlib.util.spec_from_file_location("r7a4d2_incremental_indicator_contract", path)
if spec is None or spec.loader is None:
    raise SystemExit("INDICATOR_SPEC_FAILED")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
required = (
    "atr", "volume_z", "ema", "context_columns", "edge",
    "retest_after_break", "rolling_vwap", "anchored_vwap", "append_signal",
)
missing = [name for name in required if not callable(getattr(module, name, None))]
if missing:
    raise SystemExit("INDICATOR_API_MISSING:" + ",".join(missing))
PY
then
  echo 'STATE=HOLD_INCREMENTAL_SINGLE_DEFECT_REPAIR_EXECUTION_36_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["INDICATOR_API_CONTRACT_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo 'STATE=PASS_INCREMENTAL_SINGLE_DEFECT_INDICATOR_BIND'
echo 'INDICATOR_HELPER_API_COUNT=9'

if ! python3 "$TARGET" --self-test; then
  echo 'STATE=HOLD_INCREMENTAL_SINGLE_DEFECT_REPAIR_EXECUTION_36_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["EXECUTION_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TARGET" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --raw-module "$RAW" \
  --helper-module "$HELPER" \
  --benchmark-module "$BENCHMARK" \
  --indicator-module "$INDICATOR" \
  --second-wave-module "$SECOND" \
  --a4d-contract "$CONTRACT"
RC=$?

echo 'R7A4D2_INCREMENTAL_SINGLE_DEFECT_REPAIR_EXECUTION_36_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
