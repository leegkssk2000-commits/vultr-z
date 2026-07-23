#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
OUTDIR="$ROOT/runtime/r7a4d2_economic_fail_mechanism_decision_gate"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/decision_gate_${STAMP}.log"
TMP=""

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_ECONOMIC_FAIL_MECHANISM_DECISION_GATE_START' \
  'MODE=READ_ONLY_ONE_REPRESENTATIVE_SINGLE_AXIS_SELECTION' \
  'EXPECTED_COMMON_FAILURE=NO_FAVORABLE_EXCURSION' \
  'EXPECTED_SELECTED_LANE=dual_atr_volatility_bot:15m' \
  'EXPECTED_SELECTED_VARIANT=atr15_persistence_5m_trigger' \
  'PARALLEL_REDESIGN_ALLOWED=false' \
  'BLIND_REDESIGN_ALLOWED=false' \
  'PARAMETER_OPTIMIZATION_ALLOWED=false' \
  'THRESHOLD_RELAXATION_ALLOWED=false' \
  'STOP_TARGET_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'WORKTREE_POLICY=DO_NOT_TOUCH'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_ECONOMIC_FAIL_MECHANISM_DECISION_GATE_INPUT'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

mkdir -p "$OUTDIR" || exit 2
TMP="$(mktemp -d /tmp/r7a4d2-mechanism-decision.XXXXXX)" || exit 2
TARGET="$TMP/r7a4d2_economic_fail_mechanism_decision_gate.py"

if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_economic_fail_mechanism_decision_gate.py" > "$TARGET"; then
  echo 'STATE=HOLD_ECONOMIC_FAIL_MECHANISM_DECISION_GATE_INPUT'
  echo 'BLOCKERS=["TARGET_MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$TARGET"; then
  echo 'STATE=HOLD_ECONOMIC_FAIL_MECHANISM_DECISION_GATE_INPUT'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo "TARGET_SHA=$SHA"
echo "TARGET_SCRIPT_SHA256=$(sha256sum "$TARGET" | awk '{print $1}')"
echo "EXECUTION_LOG=$LOG"
echo 'DECISION_GATE_EXECUTION_START=true'

python3 "$TARGET" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}

echo
echo '===== ECONOMIC FAIL MECHANISM DECISION GATE SUMMARY ====='
grep -E '^(STATE=|BLOCKER_COUNT=|COMMON_FAILURE_MODE=|SELECTED_LANE=|SELECTED_VARIANT=|SELECTED_ACTION=|SELECTED_SIDE=|SELECTED_SIDE_EVENTS=|SELECTED_SIDE_NET_R=|SELECTED_SIDE_PF=|PARENT_GROSS_R=|PARENT_DRAG_R=|PARENT_NET_R=|PARENT_PF=|PARALLEL_REDESIGN_ALLOWED=|DECISION_RESULT=|SUMMARY_JSON=|INPUT_MUTATION_COUNT=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 160

echo "FINAL_RC=$RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$RC"
