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
  'R7A4D2_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_PLAN_START' \
  'MODE=READ_ONLY_ALL_25_LANE_CANDLE_GEOMETRY_REPAIR_PLAN' \
  'EXPECTED_STRATEGY_LANE_COUNT=25' \
  'RAW_DOMINANT_REPAIR=entry_preserved_stop_exit_cost_repair' \
  'MIXED_REPAIR=winning_axes_locked_losing_axes_only' \
  'NO_SIGNAL_REPAIR=timeframe_route_or_semantic_reconstruction' \
  'DOMINATED_REPAIR=family_hypothesis_redesign' \
  'MAXIMUM_CANDIDATE_ARMS_PER_LANE=3' \
  'RETIREMENT_BEFORE_REPAIR_EXECUTION_ALLOWED=false' \
  'UNIVERSAL_RR_ALLOWED=false' \
  'FUTURE_PNL_PARAMETER_SELECTION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose/diagnose_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/signal_geometry_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_survivor_controlled_upgrade_discovery/discovery_lock_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_PLAN_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-all-lane-repair.XXXXXX)" || exit 2
mkdir -p "$TMP/tools"
if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_short_all_lane_architecture_repair_plan.py" \
  > "$TMP/tools/r7a4d2_short_all_lane_architecture_repair_plan.py"; then
  echo 'STATE=HOLD_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["MATERIALIZE_FAILED:tools/r7a4d2_short_all_lane_architecture_repair_plan.py"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$TMP/tools/r7a4d2_short_all_lane_architecture_repair_plan.py"; then
  echo 'STATE=HOLD_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TMP/tools/r7a4d2_short_all_lane_architecture_repair_plan.py" --self-test; then
  echo 'STATE=HOLD_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["ALL_LANE_REPAIR_PLAN_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4d2_short_all_lane_architecture_repair_plan.py" \
  --root "$ROOT" \
  --target-sha "$SHA"
RC=$?

echo 'R7A4D2_SHORT_ALL_LANE_ARCHITECTURE_REPAIR_PLAN_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
