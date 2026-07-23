#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
OUTDIR="$ROOT/runtime/r7a4d2_economic_fail_all_loss_mechanism_audit"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/economic_fail_mechanism_audit_${STAMP}.log"
TMP=""

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_ECONOMIC_FAIL_ALL_LOSS_MECHANISM_AUDIT_START' \
  'MODE=READ_ONLY_BASE_PRIMARY_CELL_PLUS_1M_PATH_ANATOMY' \
  'ECONOMIC_FAIL_CANDIDATE_COUNT=4' \
  'PRIMARY_CELL=cost_profile_0:timing_0' \
  'AUDIT_AXES=gross_cost_side_regime_symbol_exit_mfe_mae_intrabar_order' \
  'BLIND_REDESIGN_ALLOWED=false' \
  'PARAMETER_OPTIMIZATION_ALLOWED=false' \
  'THRESHOLD_RELAXATION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'WORKTREE_POLICY=DO_NOT_TOUCH'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_ECONOMIC_FAIL_ALL_LOSS_MECHANISM_AUDIT_INPUT'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

mkdir -p "$OUTDIR" || exit 2
TMP="$(mktemp -d /tmp/r7a4d2-economic-fail-audit.XXXXXX)" || exit 2
TARGET="$TMP/r7a4d2_economic_fail_all_loss_mechanism_audit.py"

if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_economic_fail_all_loss_mechanism_audit.py" > "$TARGET"; then
  echo 'STATE=HOLD_ECONOMIC_FAIL_ALL_LOSS_MECHANISM_AUDIT_INPUT'
  echo 'BLOCKERS=["TARGET_MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$TARGET"; then
  echo 'STATE=HOLD_ECONOMIC_FAIL_ALL_LOSS_MECHANISM_AUDIT_INPUT'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo "TARGET_SHA=$SHA"
echo "TARGET_SCRIPT_SHA256=$(sha256sum "$TARGET" | awk '{print $1}')"
echo "EXECUTION_LOG=$LOG"
echo 'ECONOMIC_FAIL_MECHANISM_AUDIT_EXECUTION_START=true'

python3 "$TARGET" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}

echo
echo '===== ECONOMIC FAIL ALL-LOSS MECHANISM AUDIT SUMMARY ====='
grep -E '^(STATE=|BLOCKER_COUNT=|ECONOMIC_FAIL_CANDIDATE_COUNT=|COMMON_FAILURE_MODE=|SINGLE_AXIS_REDESIGN_QUEUE_COUNT=|MECHANISM_RESULT=|EVENT_ROWS_JSONL=|GROUP_ROWS_JSONL=|SUMMARY_JSON=|MUTATION_PATH_COUNT=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 200

echo "FINAL_RC=$RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$RC"
