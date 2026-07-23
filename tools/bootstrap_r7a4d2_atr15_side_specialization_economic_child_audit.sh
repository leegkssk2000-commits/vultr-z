#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
OUTDIR="$ROOT/runtime/r7a4d2_atr15_side_specialization_economic_child_audit"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/atr15_short_child_audit_${STAMP}.log"
TMP=""

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_ATR15_SIDE_SPECIALIZATION_ECONOMIC_CHILD_AUDIT_START' \
  'MODE=READ_ONLY_PARENT_IMMUTABLE_SHORT_SIDE_FILTER_ONLY' \
  'EXPECTED_LANE=dual_atr_volatility_bot:15m' \
  'EXPECTED_VARIANT=atr15_persistence_5m_trigger' \
  'EXPECTED_SIDE=short' \
  'EXPECTED_STRESS_CELLS=6' \
  'SAME_OOS_SELECTION_BIAS=true' \
  'PROMOTION_ALLOWED=false' \
  'PARALLEL_REDESIGN_ALLOWED=false' \
  'BLIND_REDESIGN_ALLOWED=false' \
  'PARAMETER_OPTIMIZATION_ALLOWED=false' \
  'THRESHOLD_RELAXATION_ALLOWED=false' \
  'STOP_TARGET_MUTATION_ALLOWED=false' \
  'EXIT_LOGIC_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'WORKTREE_POLICY=DO_NOT_TOUCH'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_ATR15_SIDE_SPECIALIZATION_ECONOMIC_CHILD_AUDIT_INPUT'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

mkdir -p "$OUTDIR" || exit 2
TMP="$(mktemp -d /tmp/r7a4d2-atr15-short-child.XXXXXX)" || exit 2
TARGET="$TMP/r7a4d2_atr15_side_specialization_economic_child_audit.py"

if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_atr15_side_specialization_economic_child_audit.py" > "$TARGET"; then
  echo 'STATE=HOLD_ATR15_SIDE_SPECIALIZATION_ECONOMIC_CHILD_AUDIT_INPUT'
  echo 'BLOCKERS=["TARGET_MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$TARGET"; then
  echo 'STATE=HOLD_ATR15_SIDE_SPECIALIZATION_ECONOMIC_CHILD_AUDIT_INPUT'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo "TARGET_SHA=$SHA"
echo "TARGET_SCRIPT_SHA256=$(sha256sum "$TARGET" | awk '{print $1}')"
echo "EXECUTION_LOG=$LOG"
echo 'ATR15_SHORT_CHILD_AUDIT_EXECUTION_START=true'

python3 "$TARGET" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}

echo
echo '===== ATR15 SHORT CHILD AUDIT SUMMARY ====='
grep -E '^(STATE=|BLOCKER_COUNT=|CHILD_CLASSIFICATION=|SELECTED_SIDE=|PRIMARY_EVENTS=|PRIMARY_SYMBOLS=|PRIMARY_FOLDS=|PRIMARY_POS_FOLDS=|PRIMARY_GROSS_R=|PRIMARY_DRAG_R=|PRIMARY_NET_R=|PRIMARY_PF=|CHILD_PROFILE=|WORST_SEVERE_NET_R=|WORST_SEVERE_PF=|ROBUST_SAME_OOS=|CONDITIONAL_SAME_OOS=|SAME_OOS_SELECTION_BIAS=|PROMOTION_ALLOWED=|SUMMARY_JSON=|INPUT_MUTATION_COUNT=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 160

echo "FINAL_RC=$RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$RC"
