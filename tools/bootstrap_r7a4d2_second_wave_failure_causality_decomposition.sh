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
  'R7A4D2_SECOND_WAVE_FAILURE_CAUSALITY_DECOMPOSITION_START' \
  'MODE=READ_ONLY_ELEVEN_LANE_COST_FOLD_REGIME_SYMBOL_SIDE_EXIT_HOLDING_MFE_MAE_DECOMPOSITION' \
  'EXPECTED_LANE_COUNT=11' \
  'EXPECTED_SECOND_WAVE_BUNDLE_COUNT=22' \
  'EXPECTED_SECOND_WAVE_CELL_COUNT=132' \
  'ATR5_CONTROL_PRESERVED=true' \
  'SINGLE_PRIMARY_CAUSE_PER_LANE_REQUIRED=true' \
  'MAXIMUM_TARGET_REPAIR_AXIS_PER_LANE=2' \
  'EXPECTED_TARGET_REPAIR_ROW_COUNT=22' \
  'EXPECTED_THIRD_WAVE_BUNDLE_COUNT=22' \
  'EXPECTED_THIRD_WAVE_CELL_COUNT=132' \
  'MFE_MAE_RECOMPUTE_FROM_SELECTED_OHLCV=true' \
  'PARAMETER_OPTIMIZATION_ALLOWED=false' \
  'BLIND_STOP_WIDENING_ALLOWED=false' \
  'ENTRY_THRESHOLD_RELAXATION_ALLOWED=false' \
  'FUTURE_VALIDATION_SELECTION_ALLOWED=false' \
  'DISCOVERY_S_GRADE_LABEL_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'MARKET_SOURCE_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SECOND_WAVE_FAILURE_CAUSALITY_DECOMPOSITION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/all_11_second_wave_summary_v1.json" \
  "$ROOT/runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/second_wave_trade_rows_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132/second_wave_cell_rows_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_plan/all_11_second_wave_plan_v1.json" \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SECOND_WAVE_FAILURE_CAUSALITY_DECOMPOSITION_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-second-wave-causality.XXXXXX)" || exit 2

for path in \
  tools/r7a4d2_exchange_bot_v2_second_wave_failure_causality_decomposition.py \
  tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py \
  tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SECOND_WAVE_FAILURE_CAUSALITY_DECOMPOSITION_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

TARGET="$TMP/tools/r7a4d2_exchange_bot_v2_second_wave_failure_causality_decomposition.py"
RAW="$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py"
HELPER="$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py"
CONTRACT="$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"

if ! python3 - "$HELPER" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
if "def snapshot(paths: list[Path])" not in text:
    raise SystemExit("SNAPSHOT_API_MISSING")
if "def diff_snapshot(" not in text:
    marker = "\ndef classify_mutation(path_value: str, root: Path) -> str:\n"
    if text.count(marker) != 1:
        raise SystemExit("DIFF_SNAPSHOT_PATCH_ANCHOR_INVALID")
    compat = "\n\ndef diff_snapshot(before: dict[str, str], after: dict[str, str]) -> list[str]:\n    keys = set(before) | set(after)\n    return sorted(key for key in keys if before.get(key) != after.get(key))\n"
    path.write_text(text.replace(marker, compat + marker, 1), encoding="utf-8")
PY
then
  echo 'STATE=HOLD_SECOND_WAVE_FAILURE_CAUSALITY_DECOMPOSITION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["HELPER_DIFF_SNAPSHOT_COMPAT_PATCH_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo 'STATE=PASS_SECOND_WAVE_CAUSALITY_DIFF_SNAPSHOT_COMPAT_PATCH'
echo 'PATCH_SCOPE=temporary_helper_copy_only'

if ! python3 -m py_compile "$TARGET" "$RAW" "$HELPER"; then
  echo 'STATE=HOLD_SECOND_WAVE_FAILURE_CAUSALITY_DECOMPOSITION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TARGET" --self-test; then
  echo 'STATE=HOLD_SECOND_WAVE_FAILURE_CAUSALITY_DECOMPOSITION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["CAUSALITY_DECOMPOSITION_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TARGET" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --raw-module "$RAW" \
  --helper-module "$HELPER" \
  --a4d-contract "$CONTRACT"
RC=$?

echo 'R7A4D2_SECOND_WAVE_FAILURE_CAUSALITY_DECOMPOSITION_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
