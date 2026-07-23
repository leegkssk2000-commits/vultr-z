#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
TMP=""
OUTDIR="$ROOT/runtime/r7a4d2_supertrend_authentic_child_implementation_and_formula_fixtures"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/supertrend_authentic_formula_fixtures_${STAMP}.log"

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_SUPERTREND_AUTHENTIC_CHILD_IMPLEMENTATION_AND_FORMULA_FIXTURES_START' \
  'MODE=GIT_OBJECT_AUTHENTIC_CHILD_FORMULA_FIXTURE_VERIFY' \
  'LEGACY_PARENT_IMMUTABLE=true' \
  'AUTHENTIC_CHILD_IMPLEMENTATION_SCOPE=RESEARCH_ONLY' \
  'ECONOMIC_TEST_ALLOWED=false' \
  'PERFORMANCE_CLAIM_ALLOWED=false' \
  'PARAMETER_OPTIMIZATION_ALLOWED=false' \
  'THRESHOLD_RELAXATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'PROMOTION_ALLOWED=false' \
  'WORKTREE_POLICY=DO_NOT_TOUCH'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SUPERTREND_AUTHENTIC_CHILD_IMPLEMENTATION_AND_FORMULA_FIXTURES_INPUT'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

mkdir -p "$OUTDIR" || exit 2
TMP="$(mktemp -d /tmp/r7a4d2-supertrend-authentic-fixtures.XXXXXX)" || exit 2
TARGET="$TMP/r7a4d2_supertrend_authentic_child_implementation_and_formula_fixtures.py"
CHILD="$TMP/supertrend_flip_authentic.py"

if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_supertrend_authentic_child_implementation_and_formula_fixtures.py" > "$TARGET"; then
  echo 'STATE=HOLD_SUPERTREND_AUTHENTIC_CHILD_IMPLEMENTATION_AND_FORMULA_FIXTURES_INPUT'
  echo 'BLOCKERS=["VERIFIER_MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! git -C "$ROOT" show "$SHA:backend/strategies/authentic/supertrend_flip_authentic.py" > "$CHILD"; then
  echo 'STATE=HOLD_SUPERTREND_AUTHENTIC_CHILD_IMPLEMENTATION_AND_FORMULA_FIXTURES_INPUT'
  echo 'BLOCKERS=["CHILD_MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$TARGET" "$CHILD"; then
  echo 'STATE=HOLD_SUPERTREND_AUTHENTIC_CHILD_IMPLEMENTATION_AND_FORMULA_FIXTURES_INPUT'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo "TARGET_SHA=$SHA"
echo "VERIFIER_SHA256=$(sha256sum "$TARGET" | awk '{print $1}')"
echo "CHILD_SHA256=$(sha256sum "$CHILD" | awk '{print $1}')"
echo "EXECUTION_LOG=$LOG"
echo 'SUPERTREND_AUTHENTIC_FIXTURE_EXECUTION_START=true'

python3 "$TARGET" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}

echo
echo '===== SUPERTREND AUTHENTIC CHILD + FORMULA FIXTURE SUMMARY ====='
grep -E '^(STATE=|BLOCKER_COUNT=|CHILD_STRATEGY_ID=|CHILD_SOURCE_SHA256=|LEGACY_PARENT_SHA256=|LEGACY_PARENT_IMMUTABLE=|ATR_METHOD=|ATR_LENGTH=|SUPERTREND_FACTOR=|FORMULA_FIXTURE_CLASS_COUNT=|FORMULA_FIXTURE=|FORBIDDEN_IDENTIFIER_COUNT=|BIDIRECTIONAL_INTENT_COUNT=|SHORT_INTENT_SUPPRESSED_COUNT=|NATIVE_SEGMENT_EXIT_COUNT=|ECONOMIC_TEST_EXECUTED=|PERFORMANCE_CLAIM_ALLOWED=|INPUT_MUTATION_COUNT=|SUMMARY_JSON=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 160

echo "FINAL_RC=$RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$RC"
