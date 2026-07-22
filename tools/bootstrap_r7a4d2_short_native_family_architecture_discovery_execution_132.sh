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
  'R7A4D2_SHORT_NATIVE_FAMILY_ARCHITECTURE_DISCOVERY_EXECUTION_132_START' \
  'MODE=READ_ONLY_ELEVEN_NATIVE_STRATEGY_TWENTY_TWO_COMPLETE_ARCHITECTURE_BUNDLES_DISCOVERY' \
  'EXPECTED_STRATEGY_COUNT=11' \
  'EXPECTED_ARCHITECTURE_BUNDLE_COUNT=22' \
  'EXPECTED_DISCOVERY_SEGMENT_COUNT=12' \
  'EXPECTED_STRESS_CELL_PER_BUNDLE=6' \
  'EXPECTED_ARCHITECTURE_CELL_COUNT=132' \
  'SEVERE_ECONOMIC_GATE=trade_count>=8,pf>1,expectancy_r>0,net_pnl_pct>0,positive_cells>=4' \
  'STRICT_S_GRADE_GATE=trade_count>=8,pf>1.25,expectancy_r>0.15,net_pnl_pct>0,strict_positive_cells>=4' \
  'DRAW_DOWN_NONWORSENING_REQUIRED=true' \
  'CROSS_STRATEGY_SIGNAL_ALIAS_ALLOWED=false' \
  'OVERLAPPING_POSITION_ALLOWED=false' \
  'STOP_FIRST_COLLISION_REQUIRED=true' \
  'FUTURE_VALIDATION_SELECTION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'MARKET_SOURCE_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_NATIVE_FAMILY_ARCHITECTURE_DISCOVERY_EXECUTION_132_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_vwap_native_hypothesis_and_remaining_family_rebuild_plan/rebuild_plan_v1.json" \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json" \
  "$ROOT/runtime/r7a4d2_short_selective_vwap_repair_execution_54_and_remaining_uplift_audit/economic_execution_and_uplift_audit_v1.json" \
  "$ROOT/runtime/r7a4d2_short_all_lane_architecture_repair_execution/repair_arm_cell_results_v1.jsonl"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_NATIVE_FAMILY_ARCHITECTURE_DISCOVERY_EXECUTION_132_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-native-family-discovery.XXXXXX)" || exit 2
for path in \
  tools/r7a4d2_short_native_family_architecture_discovery_execution_132.py \
  tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py \
  tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_NATIVE_FAMILY_ARCHITECTURE_DISCOVERY_EXECUTION_132_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile \
  "$TMP/tools/r7a4d2_short_native_family_architecture_discovery_execution_132.py" \
  "$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py" \
  "$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py"
then
  echo 'STATE=HOLD_SHORT_NATIVE_FAMILY_ARCHITECTURE_DISCOVERY_EXECUTION_132_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TMP/tools/r7a4d2_short_native_family_architecture_discovery_execution_132.py" --self-test; then
  echo 'STATE=HOLD_SHORT_NATIVE_FAMILY_ARCHITECTURE_DISCOVERY_EXECUTION_132_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["NATIVE_FAMILY_DISCOVERY_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4d2_short_native_family_architecture_discovery_execution_132.py" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --raw-module "$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py" \
  --helper-module "$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py" \
  --a4d-contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?

echo 'R7A4D2_SHORT_NATIVE_FAMILY_ARCHITECTURE_DISCOVERY_EXECUTION_132_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
