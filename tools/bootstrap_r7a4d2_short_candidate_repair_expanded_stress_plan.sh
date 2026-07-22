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
  'R7A4D2_SHORT_CANDIDATE_REPAIR_AND_EXPANDED_STRESS_PLAN_START' \
  'MODE=READ_ONLY_FAIL_CLOSED_EXPANDED_CANDIDATE_REPAIR_AND_STRESS_PLAN' \
  'EXPECTED_EXPANDED_CANDIDATE_COUNT=28' \
  'EXPECTED_EXPANDED_STRESS_CELL_COUNT=168' \
  'SHORT_POLICY_LOSS_CAP_R=0.75' \
  'SHORT_POLICY_FULL_TP_R=2.5' \
  'GRID_REBALANCE_STRATEGY_QUARANTINED=true' \
  'VOL_SPIKE_PROMOTION_ALLOWED=false' \
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
  echo 'STATE=HOLD_SHORT_CANDIDATE_REPAIR_AND_EXPANDED_STRESS_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_market_segment_expansion_for_short_candidates/market_segment_expansion_v1.json" \
  "$ROOT/runtime/r7a4d2_short_admission_candidate_stress_66/stress66_proof_v1.json" \
  "$ROOT/runtime/r7a4d2_short_admission_allowlist_plan/allowlist_plan_v1.json"
 do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_CANDIDATE_REPAIR_AND_EXPANDED_STRESS_PLAN_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-expanded-stress-plan.XXXXXX)" || exit 2
for path in \
  tools/r7a4d2_short_candidate_repair_expanded_stress_plan.py \
  tests/test_r7a4d2_short_candidate_repair_expanded_stress_plan.py
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_CANDIDATE_REPAIR_AND_EXPANDED_STRESS_PLAN_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile "$TMP/tools/r7a4d2_short_candidate_repair_expanded_stress_plan.py"; then
  echo 'STATE=HOLD_SHORT_CANDIDATE_REPAIR_AND_EXPANDED_STRESS_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_EXPANDED_PLAN="$TMP/tools/r7a4d2_short_candidate_repair_expanded_stress_plan.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_candidate_repair_expanded_stress_plan.py"; then
  echo 'STATE=HOLD_SHORT_CANDIDATE_REPAIR_AND_EXPANDED_STRESS_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$ROOT:$TMP" python3 "$TMP/tools/r7a4d2_short_candidate_repair_expanded_stress_plan.py" --root "$ROOT"
RC=$?

echo 'R7A4D2_SHORT_CANDIDATE_REPAIR_AND_EXPANDED_STRESS_PLAN_COMPLETE'
echo "RC=$RC"
exit "$RC"
