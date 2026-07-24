#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
EXPECTED_SHA="${2:-}"
BRANCH='r7a4d-historical-simulation-3600-v1'
PART_BASE='tools/payloads/r7a4d2_supertrend_external_parity_and_oos_replay.py.part'
EXPECTED_RUNNER_SHA='30b7bb00f3659f5aeea71e3015021802760c3e5e248279c7f6b7f60673bf6c87'
OUTDIR="$ROOT/runtime/r7a4d2_supertrend_external_parity_and_oos_replay"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/supertrend_external_parity_oos_${STAMP}.log"
TMPROOT="$(mktemp -d /tmp/r7a4d2-supertrend-external-parity.XXXXXX)"
WT="$TMPROOT/worktree"
RUNNER="$TMPROOT/r7a4d2_supertrend_external_parity_and_oos_replay.py"

cleanup() {
  git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
  rm -rf "$TMPROOT"
}
trap cleanup EXIT

fail() {
  echo 'STATE=HOLD_SUPERTREND_AUTHENTIC_EXTERNAL_PARITY_AND_OOS_REPLAY_INPUT'
  echo "BLOCKERS=[\"$1\"]"
  echo 'RC=2'
  exit 2
}

printf '%s\n' \
  'R7A4D2_SUPERTREND_EXTERNAL_PARITY_AND_OOS_REPLAY_START' \
  'MODE=READ_ONLY_OFFICIAL_TRADINGVIEW_FORMULA_PARITY_THEN_CONTINUOUS_OOS_REPLAY' \
  'LEGACY_PARENT_IMMUTABLE=true' \
  'AUTHENTIC_CHILD_IMMUTABLE=true' \
  'PARAMETER_OPTIMIZATION_ALLOWED=false' \
  'TIMEFRAME_POST_SELECTION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'SIGNAL_TIME=CONFIRMED_BAR_CLOSE' \
  'FILL_TIME=NEXT_BAR_OPEN_TRADINGVIEW_DEFAULT' \
  'TERMINAL_FORCE_CLOSE=false' \
  'WORKTREE_POLICY=DO_NOT_TOUCH'

[[ -d "$ROOT/.git" ]] || fail 'ROOT_NOT_GIT_REPOSITORY'
[[ -n "$EXPECTED_SHA" ]] || fail 'EXPECTED_SHA_REQUIRED'
mkdir -p "$OUTDIR" || fail 'OUTPUT_DIR_CREATE_FAILED'

git -C "$ROOT" fetch --no-tags origin "$BRANCH" >/dev/null 2>&1 || fail 'GITHUB_FETCH_FAILED'
REMOTE_SHA="$(git -C "$ROOT" rev-parse FETCH_HEAD 2>/dev/null || true)"
echo "REMOTE_SHA=$REMOTE_SHA"
echo "EXPECTED_SHA=$EXPECTED_SHA"
[[ "$REMOTE_SHA" == "$EXPECTED_SHA" ]] || fail 'UNEXPECTED_GITHUB_HEAD'

git -C "$ROOT" worktree add --detach "$WT" "$REMOTE_SHA" >/dev/null 2>&1 || fail 'TEMP_WORKTREE_CREATE_FAILED'
for suffix in 00 01 02 03; do
  part="$WT/${PART_BASE}${suffix}"
  [[ -f "$part" ]] || fail "RUNNER_PART_MISSING_${suffix}"
  cat "$part" >> "$RUNNER" || fail "RUNNER_PART_CONCAT_FAILED_${suffix}"
done
RUNNER_SHA="$(sha256sum "$RUNNER" | awk '{print $1}')"
echo "RUNNER_SHA256=$RUNNER_SHA"
echo "EXPECTED_RUNNER_SHA256=$EXPECTED_RUNNER_SHA"
echo "RUNNER_SHA_LENGTH=${#RUNNER_SHA}"
echo "EXPECTED_RUNNER_SHA_LENGTH=${#EXPECTED_RUNNER_SHA}"
[[ ${#RUNNER_SHA} -eq 64 ]] || fail 'RUNNER_SHA_LENGTH_INVALID'
[[ ${#EXPECTED_RUNNER_SHA} -eq 64 ]] || fail 'EXPECTED_RUNNER_SHA_LENGTH_INVALID'
[[ "$RUNNER_SHA" == "$EXPECTED_RUNNER_SHA" ]] || fail 'RUNNER_SHA_MISMATCH'
python3 -m py_compile "$RUNNER" || fail 'RUNNER_PY_COMPILE_FAILED'
[[ -f "$WT/backend/strategies/authentic/supertrend_flip_authentic.py" ]] || fail 'AUTHENTIC_CHILD_MISSING'

echo "EXECUTION_LOG=$LOG"
echo 'EXTERNAL_PARITY_AND_OOS_EXECUTION_START=true'
set +e
python3 "$RUNNER" \
  --data-root "$ROOT" \
  --code-root "$WT" \
  --target-sha "$REMOTE_SHA" \
  --output-dir "$OUTDIR" \
  2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}
set -e

echo
echo '===== SUPERTREND EXTERNAL PARITY + OOS REPLAY SUMMARY ====='
grep -E '^(STATE=|BLOCKER_COUNT=|OFFICIAL_FORMULA_PARITY_PASS=|PLATFORM_CSV_PARITY_EXECUTED_COUNT=|PLATFORM_CSV_PARITY_FAILURE_COUNT=|REPLAY_RESULT=|TIMEFRAME_RESULT=|SUMMARY_JSON=|INPUT_MUTATION_COUNT=|STRATEGY_MUTATION_COUNT=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 80

echo "FINAL_RC=$RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$RC"
