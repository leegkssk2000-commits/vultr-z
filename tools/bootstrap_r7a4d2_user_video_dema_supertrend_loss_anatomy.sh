#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
EXPECTED_SHA="${2:-}"
BRANCH='r7a4d-historical-simulation-3600-v1'
RUNNER='tools/r7a4d2_user_video_dema_supertrend_loss_anatomy.py'
INPUT="$ROOT/runtime/r7a4d2_user_supplied_video_bundle_upgrade/user_supplied_video_bundle_upgrade_summary_v1.json"
OUTDIR="$ROOT/runtime/r7a4d2_user_video_dema_supertrend_loss_anatomy"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/user_video_dema_supertrend_loss_anatomy_${STAMP}.log"
TMPROOT="$(mktemp -d /tmp/r7a4d2-dema-st-loss-anatomy.XXXXXX)"
WT="$TMPROOT/worktree"

cleanup() {
  git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
  rm -rf "$TMPROOT"
}
trap cleanup EXIT

fail() {
  echo 'STATE=HOLD_USER_VIDEO_DEMA_SUPERTREND_LOSS_ANATOMY_INPUT'
  echo "BLOCKERS=[\"$1\"]"
  echo 'RC=2'
  exit 2
}

printf '%s\n' \
  'R7A4D2_USER_VIDEO_DEMA_SUPERTREND_LOSS_ANATOMY_START' \
  'MODE=READ_ONLY_TRADE_LEVEL_MFE_MAE_EXIT_REASON_COST_DECOMPOSITION' \
  'SOURCE_VIDEO=https://www.youtube.com/watch?v=g-PLctW8aU0' \
  'SOURCE_STRATEGY=tradinglab_dema200_supertrend12x3_video_v1' \
  'DECOMPOSE=timeframe,symbol,side,exit_reason,mfe,mae,hold,cost' \
  'COUNTERFACTUAL_RETURN_CLAIM_ALLOWED=false' \
  'MFE_MAE_EVENT_ORDER_KNOWN=false' \
  'REDESIGN_ALLOWED=false' \
  'LEGACY_STRATEGY_MUTATION_ALLOWED=false' \
  'CANONICAL25_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'WORKTREE_POLICY=DO_NOT_TOUCH'

[[ -d "$ROOT/.git" ]] || fail 'ROOT_NOT_GIT_REPOSITORY'
[[ -n "$EXPECTED_SHA" ]] || fail 'EXPECTED_SHA_REQUIRED'
[[ -f "$INPUT" ]] || fail "SOURCE_SUMMARY_MISSING:$INPUT"
mkdir -p "$OUTDIR" || fail 'OUTPUT_DIR_CREATE_FAILED'

git -C "$ROOT" fetch --no-tags origin "$BRANCH" >/dev/null 2>&1 || fail 'GITHUB_FETCH_FAILED'
REMOTE_SHA="$(git -C "$ROOT" rev-parse FETCH_HEAD 2>/dev/null || true)"
echo "REMOTE_SHA=$REMOTE_SHA"
echo "EXPECTED_SHA=$EXPECTED_SHA"
[[ "$REMOTE_SHA" == "$EXPECTED_SHA" ]] || fail 'UNEXPECTED_GITHUB_HEAD'

git -C "$ROOT" worktree add --detach "$WT" "$REMOTE_SHA" >/dev/null 2>&1 || fail 'TEMP_WORKTREE_CREATE_FAILED'
[[ -f "$WT/$RUNNER" ]] || fail "REQUIRED_FILE_MISSING:$RUNNER"
echo "RUNNER_SHA256=$(sha256sum "$WT/$RUNNER" | awk '{print $1}')"
echo "INPUT_SHA256=$(sha256sum "$INPUT" | awk '{print $1}')"
python3 -m py_compile "$WT/$RUNNER" || fail 'RUNNER_PY_COMPILE_FAILED'
echo 'RUNNER_PY_COMPILE_PASS=true'

echo "EXECUTION_LOG=$LOG"
echo 'LOSS_ANATOMY_EXECUTION_START=true'
set +e
python3 "$WT/$RUNNER" \
  --input-summary "$INPUT" \
  --output-dir "$OUTDIR" \
  2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}
set -e

echo
echo '===== USER VIDEO DEMA SUPERTREND LOSS ANATOMY SUMMARY ====='
grep -E '^(LOSS_CELL=|LOSS_TIMEFRAME=|LOSS_OVERALL=|STATE=|SUMMARY_JSON=|MUTATION_COUNT=|REDESIGN_ALLOWED=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 120

echo "FINAL_RC=$RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$RC"
