#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
TMP=""
OUTDIR="$ROOT/runtime/r7a4d2_canonical25_wave1_authenticity_decision_gate"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/wave1_authenticity_decision_gate_${STAMP}.log"

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_CANONICAL25_WAVE1_AUTHENTICITY_DECISION_GATE_START' \
  'MODE=READ_ONLY_GIT_OBJECT_DECISION_AND_CONTRACT_VERIFY' \
  'LEGACY_PARENT_IMMUTABLE=true' \
  'AUTHENTIC_BASELINE_CHILD_ONLY=true' \
  'PARALLEL_REDESIGN_ALLOWED=false' \
  'PERFORMANCE_UPGRADE_ALLOWED=false' \
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
  echo 'STATE=HOLD_CANONICAL25_WAVE1_AUTHENTICITY_DECISION_GATE_INPUT'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

mkdir -p "$OUTDIR" || exit 2
TMP="$(mktemp -d /tmp/r7a4d2-wave1-auth-decision.XXXXXX)" || exit 2
TARGET="$TMP/r7a4d2_canonical25_wave1_authenticity_decision_gate.py"

if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_canonical25_wave1_authenticity_decision_gate.py" > "$TARGET"; then
  echo 'STATE=HOLD_CANONICAL25_WAVE1_AUTHENTICITY_DECISION_GATE_INPUT'
  echo 'BLOCKERS=["TARGET_MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$TARGET"; then
  echo 'STATE=HOLD_CANONICAL25_WAVE1_AUTHENTICITY_DECISION_GATE_INPUT'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo "TARGET_SHA=$SHA"
echo "TARGET_SCRIPT_SHA256=$(sha256sum "$TARGET" | awk '{print $1}')"
echo "EXECUTION_LOG=$LOG"
echo 'WAVE1_AUTHENTICITY_DECISION_GATE_EXECUTION_START=true'

python3 "$TARGET" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}

echo
echo '===== CANONICAL25 WAVE1 AUTHENTICITY DECISION SUMMARY ====='
grep -E '^(STATE=|BLOCKER_COUNT=|WAVE1_STRATEGY_COUNT=|COMMON_CONTRACT_COUNT=|COMMON_CONTRACT_IDS=|SELECTED_FIRST_STRATEGY=|SELECTED_FIRST_CHILD=|AUTH_DECISION=|LEGACY_PARENT_IMMUTABLE=|PARALLEL_REDESIGN_ALLOWED=|PERFORMANCE_UPGRADE_ALLOWED=|PROMOTION_ALLOWED=|SOURCE_HASH_MISMATCH_COUNT=|INPUT_MUTATION_COUNT=|SUMMARY_JSON=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 160

echo "FINAL_RC=$RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$RC"
