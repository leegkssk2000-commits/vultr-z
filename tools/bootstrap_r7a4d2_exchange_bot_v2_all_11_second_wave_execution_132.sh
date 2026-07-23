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
  'R7A4D2_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132_START' \
  'MODE=READ_ONLY_TEN_FAILED_LANE_REPAIR_PLUS_ONE_SURVIVOR_FURTHER_UPLIFT' \
  'EXPECTED_LANE_COUNT=11' \
  'EXPECTED_FAILED_LANE_REPAIR_COUNT=10' \
  'EXPECTED_PASSED_LANE_FURTHER_UPLIFT_COUNT=1' \
  'EXPECTED_VARIANT_PER_LANE=2' \
  'EXPECTED_BUNDLE_COUNT=22' \
  'EXPECTED_STRESS_CELL_PER_BUNDLE=6' \
  'EXPECTED_CELL_COUNT=132' \
  'REFERENCE_PASS_LANE_ID=dual_donchian_trend_bot:15m' \
  'ATR5_CONTROL_PRESERVED=true' \
  'MA_SAMPLE_EXPANSION_WITHOUT_THRESHOLD_RELAXATION=true' \
  'GRID_LEVEL_INVENTORY_ISOLATION=true' \
  'BASE_AND_ADVERSE_POSITIVE_REQUIRED=true' \
  'MINIMUM_TRADES=24' \
  'MINIMUM_SYMBOL_COUNT=3' \
  'MINIMUM_POSITIVE_WALK_FORWARD_FOLDS=4' \
  'PARAMETER_OPTIMIZATION_ALLOWED=false' \
  'BLIND_STOP_WIDENING_ALLOWED=false' \
  'ENTRY_THRESHOLD_RELAXATION_ALLOWED=false' \
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
  echo 'STATE=HOLD_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_plan/remaining_11_lane_uplift_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_execution_132/remaining_11_lane_uplift_summary_v1.json" \
  "$ROOT/runtime/r7a4d2_short_economic_calibration_and_exchange_bot_benchmark_v2_plan/economic_calibration_and_exchange_bot_benchmark_v2_plan_v1.json" \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-all-11-second-wave.XXXXXX)" || exit 2

for path in \
  tools/r7a4d2_exchange_bot_v2_all_11_second_wave_plan.py \
  tools/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132.py \
  tools/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_execution_132.py \
  tools/r7a4d2_short_exchange_bot_benchmark_v2_execution_72.py \
  tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py \
  tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

PLAN="$TMP/tools/r7a4d2_exchange_bot_v2_all_11_second_wave_plan.py"
TARGET="$TMP/tools/r7a4d2_exchange_bot_v2_all_11_second_wave_execution_132.py"
OLD="$TMP/tools/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_execution_132.py"
BENCHMARK="$TMP/tools/r7a4d2_short_exchange_bot_benchmark_v2_execution_72.py"
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
  echo 'STATE=HOLD_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["HELPER_DIFF_SNAPSHOT_COMPAT_PATCH_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo 'STATE=PASS_EXCHANGE_BOT_V2_SECOND_WAVE_DIFF_SNAPSHOT_COMPAT_PATCH'
echo 'PATCH_SCOPE=temporary_helper_copy_only'

if ! python3 - "$TARGET" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = '''    lane_best:dict[str,dict[str,Any]]={}
    for row in bundle_rows:
        lane_id=str(row["source_lane_id"])
        if lane_id not in lane_best or finite(row["candidate_risk_score"],-1e9)>finite(lane_best[lane_id]["candidate_risk_score"],-1e9): lane_best[lane_id]=row
'''
new = '''    lane_best:dict[str,dict[str,Any]]={}
    def lane_selection_key(row: dict[str, Any]) -> tuple[int, int, int, float, int]:
        return (
            int(bool(row.get("uplift_discovery_pass"))),
            int(bool(row.get("base_and_adverse_positive"))),
            int(row.get("positive_primary_cell_count") or 0),
            finite(row.get("candidate_risk_score"), -1e9),
            int(row.get("signal_count") or 0),
        )
    for row in bundle_rows:
        lane_id=str(row["source_lane_id"])
        if lane_id not in lane_best or lane_selection_key(row)>lane_selection_key(lane_best[lane_id]): lane_best[lane_id]=row
'''
if text.count(old) != 1:
    raise SystemExit("PASS_FIRST_AGGREGATION_PATCH_ANCHOR_INVALID")
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")

invalid = {"uplift_discovery_pass": False, "base_and_adverse_positive": True, "positive_primary_cell_count": 4, "candidate_risk_score": 999.0, "signal_count": 1}
valid = {"uplift_discovery_pass": True, "base_and_adverse_positive": True, "positive_primary_cell_count": 3, "candidate_risk_score": 1.0, "signal_count": 24}
def key(row):
    return (
        int(bool(row.get("uplift_discovery_pass"))),
        int(bool(row.get("base_and_adverse_positive"))),
        int(row.get("positive_primary_cell_count") or 0),
        float(row.get("candidate_risk_score") or -1e9),
        int(row.get("signal_count") or 0),
    )
if not key(valid) > key(invalid):
    raise SystemExit("PASS_FIRST_AGGREGATION_CONTRACT_FAILED")
PY
then
  echo 'STATE=HOLD_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PASS_FIRST_LANE_AGGREGATION_PATCH_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo 'STATE=PASS_EXCHANGE_BOT_V2_SECOND_WAVE_PASS_FIRST_LANE_AGGREGATION_PATCH'
echo 'LANE_SELECTION_ORDER=UPLIFT_PASS,BASE_ADVERSE_POSITIVE,PRIMARY_PASS_CELLS,RISK_SCORE,SIGNAL_COUNT'
echo 'PATCH_SCOPE=temporary_execution_copy_only'

if ! python3 -m py_compile "$PLAN" "$TARGET" "$OLD" "$BENCHMARK" "$RAW" "$HELPER"; then
  echo 'STATE=HOLD_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$PLAN" --self-test; then
  echo 'STATE=HOLD_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["SECOND_WAVE_PLAN_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$PLAN" --root "$ROOT" --target-sha "$SHA"; then
  echo 'STATE=HOLD_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["SECOND_WAVE_PLAN_BUILD_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TARGET" --self-test --old-uplift-module "$OLD"; then
  echo 'STATE=HOLD_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["SECOND_WAVE_EXECUTION_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TARGET" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --raw-module "$RAW" \
  --helper-module "$HELPER" \
  --benchmark-module "$BENCHMARK" \
  --old-uplift-module "$OLD" \
  --a4d-contract "$CONTRACT"
RC=$?

echo 'R7A4D2_EXCHANGE_BOT_V2_ALL_11_SECOND_WAVE_EXECUTION_132_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
