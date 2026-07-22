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
  'R7A4D2_SHORT_SINGLE_SCALP_SURVIVOR_6_AND_COST_R_FEASIBILITY_PLAN_START' \
  'MODE=READ_ONLY_SINGLE_SURVIVOR_COST_R_FEASIBILITY_AND_RETEST_PLAN' \
  'EXPECTED_SCALP_CELL_COUNT=24' \
  'EXPECTED_SCALP_CANDIDATE_COUNT=4' \
  'EXPECTED_SINGLE_SURVIVOR_COUNT=1' \
  'SINGLE_SURVIVOR_RETEST_CELL_TARGET=6' \
  'ROBUST_DIAGNOSTIC_FRICTION_CAP_R=0.25' \
  'CONDITIONAL_DIAGNOSTIC_FRICTION_CAP_R=0.33' \
  'ABSOLUTE_DIAGNOSTIC_FRICTION_CAP_R=0.75' \
  'OPERATIONAL_SSOT_CHANGE=false' \
  'BLIND_STOP_WIDENING_ALLOWED=false' \
  'ENTRY_THRESHOLD_RELAXATION_ALLOWED=false' \
  'REJECTED_REBASE_CANDIDATES_LOCKED=true' \
  'RAW_CONTROL_EXECUTION_ALLOWED=false' \
  'BASELINE_MARKET_COVERAGE_EXPANSION_STILL_REQUIRED=true' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'FULL_3600_REEXECUTION_ALLOWED=false' \
  'EVENT_REPLAY_2880_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_SINGLE_SCALP_SURVIVOR_6_AND_COST_R_FEASIBILITY_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_stop_overshoot_cost_r_causal_audit/causal_audit_v1.json" \
  "$ROOT/runtime/r7a4d2_short_selective_counterfactual_plan/counterfactual_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_scalp_counterfactual24_baseline_expansion36/counterfactual_expansion_proof_v1.json"
 do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_SINGLE_SCALP_SURVIVOR_6_AND_COST_R_FEASIBILITY_PLAN_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-survivor-feasibility.XXXXXX)" || exit 2
for path in \
  tools/r7a4d2_short_single_scalp_survivor6_cost_r_feasibility_plan.py \
  tests/test_r7a4d2_short_single_scalp_survivor6_cost_r_feasibility_plan.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_SINGLE_SCALP_SURVIVOR_6_AND_COST_R_FEASIBILITY_PLAN_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile "$TMP/tools/r7a4d2_short_single_scalp_survivor6_cost_r_feasibility_plan.py"; then
  echo 'STATE=HOLD_SHORT_SINGLE_SCALP_SURVIVOR_6_AND_COST_R_FEASIBILITY_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_SURVIVOR_FEASIBILITY="$TMP/tools/r7a4d2_short_single_scalp_survivor6_cost_r_feasibility_plan.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_single_scalp_survivor6_cost_r_feasibility_plan.py"; then
  echo 'STATE=HOLD_SHORT_SINGLE_SCALP_SURVIVOR_6_AND_COST_R_FEASIBILITY_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["SURVIVOR_FEASIBILITY_FOCUSED_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$TMP:$ROOT" python3 "$TMP/tools/r7a4d2_short_single_scalp_survivor6_cost_r_feasibility_plan.py" \
  --root "$ROOT" \
  --contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?

echo 'R7A4D2_SHORT_SINGLE_SCALP_SURVIVOR_6_AND_COST_R_FEASIBILITY_PLAN_COMPLETE'
echo "RC=$RC"
exit "$RC"
