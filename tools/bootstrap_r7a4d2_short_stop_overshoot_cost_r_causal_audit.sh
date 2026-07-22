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
  'R7A4D2_SHORT_STOP_OVERSHOOT_AND_COST_R_CAUSAL_AUDIT_START' \
  'MODE=READ_ONLY_TRADE_LEVEL_STOP_GAP_SLIPPAGE_COST_R_AND_LATENCY_CAUSAL_AUDIT' \
  'EXPECTED_SCALP_CELL_COUNT=24' \
  'EXPECTED_SCALP_CANDIDATE_COUNT=4' \
  'NOMINAL_LOSS_CAP_R=0.75' \
  'NOMINAL_FULL_TP_R=2.5' \
  'STOP_OVERSHOOT_DECOMPOSITION=policy_stop_to_raw_gap_exit_to_slippage_exit' \
  'COST_R_DECOMPOSITION=recorded_fee_funding_plus_contractual_fee_slippage_floor' \
  'PERTURBATION_DECAY_AUDIT_REQUIRED=true' \
  'SINGLE_SURVIVOR_RETEST_LOCK_REQUIRED=true' \
  'BASELINE_MARKET_COVERAGE_EXPANSION_STILL_REQUIRED=true' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'ENTRY_THRESHOLD_RELAXATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'FULL_3600_REEXECUTION_ALLOWED=false' \
  'EVENT_REPLAY_2880_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_STOP_OVERSHOOT_AND_COST_R_CAUSAL_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

PROOF="$ROOT/runtime/r7a4d2_short_scalp_counterfactual24_baseline_expansion36/counterfactual_expansion_proof_v1.json"
if [[ ! -f "$PROOF" ]]; then
  echo 'STATE=HOLD_SHORT_STOP_OVERSHOOT_AND_COST_R_CAUSAL_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  printf 'BLOCKERS=["REQUIRED_PROOF_MISSING:%s"]\n' "$PROOF"
  echo 'RC=2'
  exit 2
fi

TMP="$(mktemp -d /tmp/r7a4d2-cost-r-audit.XXXXXX)" || exit 2
for path in \
  tools/r7a4d2_short_stop_overshoot_cost_r_causal_audit.py \
  tests/test_r7a4d2_short_stop_overshoot_cost_r_causal_audit.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_STOP_OVERSHOOT_AND_COST_R_CAUSAL_AUDIT_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile "$TMP/tools/r7a4d2_short_stop_overshoot_cost_r_causal_audit.py"; then
  echo 'STATE=HOLD_SHORT_STOP_OVERSHOOT_AND_COST_R_CAUSAL_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_COST_R_AUDIT="$TMP/tools/r7a4d2_short_stop_overshoot_cost_r_causal_audit.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_stop_overshoot_cost_r_causal_audit.py"; then
  echo 'STATE=HOLD_SHORT_STOP_OVERSHOOT_AND_COST_R_CAUSAL_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["COST_R_CAUSAL_AUDIT_FOCUSED_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$TMP:$ROOT" python3 "$TMP/tools/r7a4d2_short_stop_overshoot_cost_r_causal_audit.py" \
  --root "$ROOT" \
  --contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?

echo 'R7A4D2_SHORT_STOP_OVERSHOOT_AND_COST_R_CAUSAL_AUDIT_COMPLETE'
echo "RC=$RC"
exit "$RC"
