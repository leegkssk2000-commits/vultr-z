#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
TMP=""
OUTDIR="$ROOT/runtime/r7a4d2_remaining_oos_batch_result_semantic_repair"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/semantic_repair_${STAMP}.log"

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_REMAINING_OOS_BATCH_RESULT_SEMANTIC_REPAIR_START' \
  'MODE=READ_ONLY_POSTPROCESS_CLASSIFICATION_REPAIR' \
  'BLIND_REDESIGN_ALLOWED=false' \
  'PARAMETER_OPTIMIZATION_ALLOWED=false' \
  'THRESHOLD_RELAXATION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'WORKTREE_POLICY=DO_NOT_TOUCH'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_REMAINING_OOS_BATCH_SEMANTIC_REPAIR_INPUT'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

mkdir -p "$OUTDIR" || exit 2
TMP="$(mktemp -d /tmp/r7a4d2-semantic-repair.XXXXXX)" || exit 2
TARGET="$TMP/r7a4d2_remaining_oos_batch_result_semantic_repair.py"

if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_remaining_oos_batch_result_semantic_repair.py" > "$TARGET"; then
  echo 'STATE=HOLD_REMAINING_OOS_BATCH_SEMANTIC_REPAIR_INPUT'
  echo 'BLOCKERS=["TARGET_MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$TARGET"; then
  echo 'STATE=HOLD_REMAINING_OOS_BATCH_SEMANTIC_REPAIR_INPUT'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo "TARGET_SHA=$SHA"
echo "TARGET_SCRIPT_SHA256=$(sha256sum "$TARGET" | awk '{print $1}')"
echo "EXECUTION_LOG=$LOG"
echo 'SEMANTIC_REPAIR_EXECUTION_START=true'

python3 "$TARGET" --root "$ROOT" --target-sha "$SHA" 2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}

echo
echo '===== REMAINING OOS SEMANTIC REPAIR SUMMARY ====='
grep -E '^(STATE=|BLOCKER_COUNT=|ROBUST_SURVIVOR_COUNT=|CONDITIONAL_SURVIVOR_COUNT=|ECONOMIC_FAIL_COUNT=|DATA_COVERAGE_HOLD_COUNT=|EXECUTION_HOLD_COUNT=|SEMANTIC_RESULT=|BLIND_REDESIGN_ALLOWED=|SUMMARY_JSON=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 180

echo "FINAL_RC=$RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$RC"
