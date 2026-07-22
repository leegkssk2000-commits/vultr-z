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
  'R7A4D2_SHORT_CHART_STRUCTURE_FORENSICS_START' \
  'MODE=READ_ONLY_PRE_ENTRY_CHART_STRUCTURE_AND_SIMPLE_GATE_FORENSICS' \
  'TARGETED_CANDIDATE_COUNT=28' \
  'PRE_ENTRY_CHART_FEATURE_COUNT=20' \
  'GATE_USES_PRE_ENTRY_CHART_ONLY=true' \
  'FUTURE_MFE_MAE_PNL_GATE_INPUT_ALLOWED=false' \
  'FUTURE_CHART_CONTEXT_VISUAL_ONLY=true' \
  'RULE_COMPLEXITY_MAX_CONDITIONS=2' \
  'LEAVE_ONE_SOURCE_OUT_REQUIRED=true' \
  'GRID_REBALANCE_STRATEGY_QUARANTINED=true' \
  'VOL_SHOCK_AUTOMATIC_REPAIR_ALLOWED=false' \
  'PRODUCTION_ADMISSION_EXPANSION_ALLOWED=false' \
  'ENTRY_THRESHOLD_RELAXATION_ALLOWED=false' \
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
  echo 'STATE=HOLD_SHORT_CHART_STRUCTURE_FORENSICS_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_expanded_candidate_stress_168/stress168_proof_v1.json" \
  "$ROOT/runtime/r7a4d2_short_candidate_repair_expanded_stress_plan/expanded_stress_plan_v1.json"
 do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_CHART_STRUCTURE_FORENSICS_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-chart-forensics.XXXXXX)" || exit 2
for path in \
  tools/r7a4d_historical_simulation_3600.py \
  tools/r7a4d2_short_chart_structure_forensics.py \
  tests/test_r7a4d2_short_chart_structure_forensics.py
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_CHART_STRUCTURE_FORENSICS_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile \
  "$TMP/tools/r7a4d_historical_simulation_3600.py" \
  "$TMP/tools/r7a4d2_short_chart_structure_forensics.py"; then
  echo 'STATE=HOLD_SHORT_CHART_STRUCTURE_FORENSICS_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_CHART_FORENSICS="$TMP/tools/r7a4d2_short_chart_structure_forensics.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_chart_structure_forensics.py"; then
  echo 'STATE=HOLD_SHORT_CHART_STRUCTURE_FORENSICS_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["CHART_FORENSICS_FOCUSED_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$TMP:$ROOT" python3 "$TMP/tools/r7a4d2_short_chart_structure_forensics.py" \
  --root "$ROOT" \
  --runner "$TMP/tools/r7a4d_historical_simulation_3600.py"
RC=$?

echo 'R7A4D2_SHORT_CHART_STRUCTURE_FORENSICS_COMPLETE'
echo "RC=$RC"
exit "$RC"
