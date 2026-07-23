#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
TMP=""
OUTDIR="$ROOT/runtime/r7a4d2_canonical25_source_to_code_wave1"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/wave1_verify_${STAMP}.log"

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_CANONICAL25_SOURCE_TO_CODE_RULE_AUDIT_WAVE1_START' \
  'MODE=READ_ONLY_GIT_OBJECT_SOURCE_TO_CODE_AUTHENTICITY_VERIFY' \
  'WAVE1=TURTLE_RBREAKER_SQUEEZE_SUPERTREND_BOLLINGER' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'PARAMETER_OPTIMIZATION_ALLOWED=false' \
  'PERFORMANCE_UPGRADE_ALLOWED=false' \
  'PARALLEL_REDESIGN_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'WORKTREE_POLICY=DO_NOT_TOUCH'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_CANONICAL25_SOURCE_TO_CODE_WAVE1_INPUT'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

mkdir -p "$OUTDIR" || exit 2
TMP="$(mktemp -d /tmp/r7a4d2-wave1-auth.XXXXXX)" || exit 2

FILES=(
  'backend/strategy25/canonical_strategy_registry_v1.json'
  'research/canonical25_source_to_code_wave1_v1.json'
  'backend/strategies/turtle_trend.py'
  'backend/strategies/rbreaker_like.py'
  'backend/strategies/squeeze_break.py'
  'backend/strategies/supertrend_pullback.py'
  'backend/strategies/bb_revert.py'
  'tools/r7a4d2_canonical25_source_to_code_wave1_verify.py'
)

for rel in "${FILES[@]}"; do
  mkdir -p "$TMP/$(dirname "$rel")" || exit 2
  if ! git -C "$ROOT" show "$SHA:$rel" > "$TMP/$rel"; then
    echo 'STATE=HOLD_CANONICAL25_SOURCE_TO_CODE_WAVE1_INPUT'
    echo "BLOCKERS=[\"GIT_OBJECT_MATERIALIZE_FAILED:$rel\"]"
    echo 'RC=2'
    exit 2
  fi
done

TARGET="$TMP/tools/r7a4d2_canonical25_source_to_code_wave1_verify.py"
if ! python3 -m py_compile "$TARGET"; then
  echo 'STATE=HOLD_CANONICAL25_SOURCE_TO_CODE_WAVE1_INPUT'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo "TARGET_SHA=$SHA"
echo "TARGET_SCRIPT_SHA256=$(sha256sum "$TARGET" | awk '{print $1}')"
echo "AUDIT_MAP_SHA256=$(sha256sum "$TMP/research/canonical25_source_to_code_wave1_v1.json" | awk '{print $1}')"
echo "EXECUTION_LOG=$LOG"
echo 'GIT_OBJECT_MATERIALIZATION=true'
echo 'WAVE1_VERIFY_EXECUTION_START=true'

python3 "$TARGET" \
  --materialized-root "$TMP" \
  --output-root "$ROOT" \
  --target-sha "$SHA" \
  2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}

echo
echo '===== CANONICAL25 SOURCE-TO-CODE WAVE1 SUMMARY ====='
grep -E '^(STATE=|BLOCKER_COUNT=|WAVE1_STRATEGY_COUNT=|AUTHENTIC_MATCH_COUNT=|PARTIAL_OR_DERIVATIVE_COUNT=|CRITICAL_HEURISTIC_OR_NONCANONICAL_COUNT=|WAVE1_RESULT=|COMMON_DEFECT=|STRATEGY_MUTATION_ALLOWED=|PERFORMANCE_UPGRADE_ALLOWED=|SUMMARY_JSON=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 140

echo "FINAL_RC=$RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$RC"
