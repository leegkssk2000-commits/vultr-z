#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
TMP=""
OUTDIR="$ROOT/runtime/r7a4d2_canonical25_role_and_replay_coverage_audit"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/canonical25_role_replay_audit_${STAMP}.log"

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_CANONICAL25_ROLE_AND_REPLAY_COVERAGE_AUDIT_START' \
  'MODE=READ_ONLY_CANONICAL25_ROLE_BIND_AND_DIRECT_REPLAY_COVERAGE' \
  'FAILED_11_LANE_AXIS_FROZEN=true' \
  'OLD_A4D_PERFORMANCE_FINAL_ALLOWED=false' \
  'PERFORMANCE_BASED_RESELECTION_ALLOWED=false' \
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
  echo 'STATE=HOLD_CANONICAL25_ROLE_AND_REPLAY_COVERAGE_AUDIT_INPUT'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

mkdir -p "$OUTDIR" || exit 2
TMP="$(mktemp -d /tmp/r7a4d2-canonical25-audit.XXXXXX)" || exit 2
TARGET="$TMP/r7a4d2_canonical25_role_and_replay_coverage_audit.py"

if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_canonical25_role_and_replay_coverage_audit.py" > "$TARGET"; then
  echo 'STATE=HOLD_CANONICAL25_ROLE_AND_REPLAY_COVERAGE_AUDIT_INPUT'
  echo 'BLOCKERS=["TARGET_MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$TARGET"; then
  echo 'STATE=HOLD_CANONICAL25_ROLE_AND_REPLAY_COVERAGE_AUDIT_INPUT'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo "TARGET_SHA=$SHA"
echo "TARGET_SCRIPT_SHA256=$(sha256sum "$TARGET" | awk '{print $1}')"
echo "EXECUTION_LOG=$LOG"
echo 'CANONICAL25_AUDIT_EXECUTION_START=true'

python3 "$TARGET" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}

echo
echo '===== CANONICAL25 ROLE + REPLAY COVERAGE SUMMARY ====='
grep -E '^(STATE=|BLOCKER_COUNT=|CANONICAL_STRATEGY_COUNT=|REPLAY_READY_LONG_ONLY_COUNT=|REPLAY_READY_UNIFIED_LONG_SHORT_COUNT=|PRE_REPLAY_CLOSURE_COUNT=|MARKET_COVERAGE_HOLD_COUNT=|CLASSIFICATION_HISTOGRAM=|CANONICAL25_RESULT=|FAILED_11_LANE_AXIS_FROZEN=|OLD_A4D_PERFORMANCE_FINAL_ALLOWED=|AUDIT_JSON=|PLAN_JSON=|INPUT_MUTATION_COUNT=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 220

echo "FINAL_RC=$RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$RC"
