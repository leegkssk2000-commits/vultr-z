#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
EXPECTED_SHA="${2:-}"
BRANCH='r7a4d-historical-simulation-3600-v1'
RUNNER_PATH='tools/r7a4d2_js_techtrading_supertrend_pullback_loss_anatomy.py'
INPUT_SUMMARY="$ROOT/runtime/r7a4d2_js_techtrading_supertrend_pullback_exact_oos_replay/js_techtrading_supertrend_pullback_exact_oos_summary_v1.json"
OUTDIR="$ROOT/runtime/r7a4d2_js_techtrading_supertrend_pullback_loss_anatomy"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/js_techtrading_supertrend_pullback_loss_anatomy_${STAMP}.log"
TMPROOT="$(mktemp -d /tmp/r7a4d2-js-supertrend-loss-anatomy.XXXXXX)"
WT="$TMPROOT/worktree"

cleanup() {
  git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
  rm -rf "$TMPROOT"
}
trap cleanup EXIT

fail() {
  echo 'STATE=HOLD_JS_TECHTRADING_SUPERTREND_PULLBACK_LOSS_ANATOMY_INPUT'
  echo "BLOCKERS=[\"$1\"]"
  echo 'RC=2'
  exit 2
}

printf '%s\n' \
  'R7A4D2_JS_TECHTRADING_SUPERTREND_PULLBACK_LOSS_ANATOMY_START' \
  'MODE=READ_ONLY_EXACT_OOS_TRADE_LEVEL_LOSS_DECOMPOSITION' \
  'DECOMPOSE_BY=timeframe,symbol,side,exit_reason,mfe,mae,hold,cost' \
  'SOURCE_STRATEGY_MUTATION_ALLOWED=false' \
  'PARAMETER_OPTIMIZATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'WORKTREE_POLICY=DO_NOT_TOUCH'

[[ -d "$ROOT/.git" ]] || fail 'ROOT_NOT_GIT_REPOSITORY'
[[ -n "$EXPECTED_SHA" ]] || fail 'EXPECTED_SHA_REQUIRED'
[[ -f "$INPUT_SUMMARY" ]] || fail 'EXACT_OOS_SUMMARY_MISSING'
mkdir -p "$OUTDIR" || fail 'OUTPUT_DIR_CREATE_FAILED'

git -C "$ROOT" fetch --no-tags origin "$BRANCH" >/dev/null 2>&1 || fail 'GITHUB_FETCH_FAILED'
REMOTE_SHA="$(git -C "$ROOT" rev-parse FETCH_HEAD 2>/dev/null || true)"
echo "REMOTE_SHA=$REMOTE_SHA"
echo "EXPECTED_SHA=$EXPECTED_SHA"
[[ "$REMOTE_SHA" == "$EXPECTED_SHA" ]] || fail 'UNEXPECTED_GITHUB_HEAD'

git -C "$ROOT" worktree add --detach "$WT" "$REMOTE_SHA" >/dev/null 2>&1 || fail 'TEMP_WORKTREE_CREATE_FAILED'
[[ -f "$WT/$RUNNER_PATH" ]] || fail 'LOSS_ANATOMY_RUNNER_MISSING'
echo "RUNNER_SHA256=$(sha256sum "$WT/$RUNNER_PATH" | awk '{print $1}')"
echo "INPUT_SUMMARY_SHA256=$(sha256sum "$INPUT_SUMMARY" | awk '{print $1}')"
python3 -m py_compile "$WT/$RUNNER_PATH" || fail 'RUNNER_PY_COMPILE_FAILED'
echo 'RUNNER_PY_COMPILE_PASS=true'

echo "EXECUTION_LOG=$LOG"
echo 'LOSS_ANATOMY_EXECUTION_START=true'
set +e
python3 "$WT/$RUNNER_PATH" \
  --summary "$INPUT_SUMMARY" \
  --output-dir "$OUTDIR" \
  2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}
set -e

echo
echo '===== JS TECHTRADING SUPERTREND PULLBACK LOSS ANATOMY SUMMARY ====='
grep -E '^(STATE=|BLOCKER_COUNT=|TIMEFRAME_DECOMP=|SIDE_DECOMP=|CELL_DECOMP=|GLOBAL_DECOMP=|OUTPUT_JSON=|MUTATION_COUNT=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 100

echo "FINAL_RC=$RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$RC"
