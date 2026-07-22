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
  'R7A4D2_SHORT_SCALP_R_DISTANCE_AND_TIMEFRAME_REDESIGN_PLAN_START' \
  'MODE=READ_ONLY_FROZEN_MARKET_TIMEFRAME_AND_NATURAL_R_DISTANCE_REDESIGN_PLAN' \
  'CANONICAL_STRATEGY_UNIVERSE_COUNT=25' \
  'SHORT_TARGET_STRATEGY_UNIVERSE_COUNT=12' \
  'ACTIVE_REPAIR_STRATEGY_COUNT=3' \
  'REDESIGN_STRATEGY_COUNT=1' \
  'REDESIGN_STRATEGY_ID=scalp_snap' \
  'CURRENT_1M_SCALP_EXECUTION_ALLOWED=false' \
  'TIMEFRAME_ARCHITECTURES=5m_5m,15m_15m,15m_5m' \
  'ARCHITECTURE_COUNT=3' \
  'CANDIDATE_TARGET_PER_ARCHITECTURE=12' \
  'TARGET_CANDIDATE_COUNT=36' \
  'TARGET_EXECUTION_CELL_COUNT=216' \
  'CONDITIONAL_FRICTION_CAP_R=0.33' \
  'ROBUST_FRICTION_CAP_R=0.25' \
  'ABSOLUTE_FRICTION_CAP_R=0.75' \
  'NATURAL_PRE_ENTRY_SWING_DISTANCE_REQUIRED=true' \
  'BLIND_STOP_WIDENING_ALLOWED=false' \
  'ENTRY_THRESHOLD_RELAXATION_ALLOWED=false' \
  'FUTURE_PNL_SEGMENT_SELECTION_ALLOWED=false' \
  'FROZEN_MARKET_SOURCE_ONLY=true' \
  'UTC_DETERMINISTIC_RESAMPLING_REQUIRED=true' \
  'FAILURE_LEARNING_CONNECTION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'PRODUCTION_ADMISSION_EXPANSION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'FULL_3600_REEXECUTION_ALLOWED=false' \
  'EVENT_REPLAY_2880_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_SCALP_R_DISTANCE_AND_TIMEFRAME_REDESIGN_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_single_scalp_survivor6_cost_r_feasibility_plan/feasibility_plan_v1.json" \
  "$ROOT/runtime/r7a4_simulation_replay_input_freeze/frozen_input_manifest_v1.json"
 do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_SCALP_R_DISTANCE_AND_TIMEFRAME_REDESIGN_PLAN_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-scalp-timeframe-redesign.XXXXXX)" || exit 2
for path in \
  tools/r7a4d2_short_scalp_r_distance_timeframe_redesign_plan.py \
  tools/r7a4d_historical_simulation_3600.py \
  tests/test_r7a4d2_short_scalp_r_distance_timeframe_redesign_plan.py \
  backend/contracts/ZOS_R7A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE_v1.json \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_SCALP_R_DISTANCE_AND_TIMEFRAME_REDESIGN_PLAN_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile \
  "$TMP/tools/r7a4d2_short_scalp_r_distance_timeframe_redesign_plan.py" \
  "$TMP/tools/r7a4d_historical_simulation_3600.py"; then
  echo 'STATE=HOLD_SHORT_SCALP_R_DISTANCE_AND_TIMEFRAME_REDESIGN_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_SCALP_TIMEFRAME_REDESIGN="$TMP/tools/r7a4d2_short_scalp_r_distance_timeframe_redesign_plan.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_scalp_r_distance_timeframe_redesign_plan.py"; then
  echo 'STATE=HOLD_SHORT_SCALP_R_DISTANCE_AND_TIMEFRAME_REDESIGN_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["SCALP_TIMEFRAME_REDESIGN_FOCUSED_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$TMP:$ROOT" python3 "$TMP/tools/r7a4d2_short_scalp_r_distance_timeframe_redesign_plan.py" \
  --root "$ROOT" \
  --runner "$TMP/tools/r7a4d_historical_simulation_3600.py" \
  --a4c-contract "$TMP/backend/contracts/ZOS_R7A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE_v1.json" \
  --a4d-contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?

echo 'R7A4D2_SHORT_SCALP_R_DISTANCE_AND_TIMEFRAME_REDESIGN_PLAN_COMPLETE'
echo "RC=$RC"
exit "$RC"
