#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
EXPECTED_SHA="${2:-}"
BRANCH='r7a4d-historical-simulation-3600-v1'
RUNNER='tools/r7a4d2_user_supplied_video_bundle_upgrade.py'
CHILD='backend/strategies/authentic/tradinglab_dema_supertrend_video_v1.py'
CONTRACT='research/user_supplied_pullback_video_bundle_v1.json'
UTILS='tools/r7a4d2_js_techtrading_supertrend_pullback_exact_oos_replay.py'
OUTDIR="$ROOT/runtime/r7a4d2_user_supplied_video_bundle_upgrade"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/user_supplied_video_bundle_upgrade_${STAMP}.log"
TMPROOT="$(mktemp -d /tmp/r7a4d2-user-video-upgrade.XXXXXX)"
WT="$TMPROOT/worktree"

cleanup() {
  git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
  rm -rf "$TMPROOT"
}
trap cleanup EXIT

fail() {
  echo 'STATE=HOLD_USER_SUPPLIED_VIDEO_BUNDLE_UPGRADE_INPUT'
  echo "BLOCKERS=[\"$1\"]"
  echo 'RC=2'
  exit 2
}

printf '%s\n' \
  'R7A4D2_USER_SUPPLIED_VIDEO_BUNDLE_UPGRADE_START' \
  'MODE=READ_ONLY_USER_VIDEO_SSOT_PLUS_GEMINI_SUMMARY_AND_OOS' \
  'VIDEO_1=https://www.youtube.com/watch?v=R2hZlnh37fQ' \
  'VIDEO_2=https://www.youtube.com/watch?v=g-PLctW8aU0' \
  'VIDEO_3=https://www.youtube.com/watch?v=cKKLujAdvzk' \
  'VIDEO_1_CLASS=MANUAL_PULLBACK_CONFLUENCE_CONTRACT' \
  'VIDEO_2_CLASS=EXECUTABLE_DEMA200_SUPERTREND12X3_CONTRACT' \
  'VIDEO_3_CLASS=MANUAL_PULLBACK_CONFLUENCE_RSI_CONTRACT' \
  'LEGACY_TRADING_NERD_MTF_ROUTE_USED=false' \
  'EARLY_ENTRY_ENABLED=false' \
  'FIBONACCI_BOLLINGER_EXIT_ENABLED=false' \
  'TIMEFRAMES=5m,15m' \
  'SYMBOLS=XRPUSDT,LINKUSDT,BTCUSDT,ETHUSDT,SOLUSDT' \
  'POST_SELECTION_ALLOWED=false' \
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
mkdir -p "$OUTDIR" || fail 'OUTPUT_DIR_CREATE_FAILED'

git -C "$ROOT" fetch --no-tags origin "$BRANCH" >/dev/null 2>&1 || fail 'GITHUB_FETCH_FAILED'
REMOTE_SHA="$(git -C "$ROOT" rev-parse FETCH_HEAD 2>/dev/null || true)"
echo "REMOTE_SHA=$REMOTE_SHA"
echo "EXPECTED_SHA=$EXPECTED_SHA"
[[ "$REMOTE_SHA" == "$EXPECTED_SHA" ]] || fail 'UNEXPECTED_GITHUB_HEAD'

git -C "$ROOT" worktree add --detach "$WT" "$REMOTE_SHA" >/dev/null 2>&1 || fail 'TEMP_WORKTREE_CREATE_FAILED'
for path in "$RUNNER" "$CHILD" "$CONTRACT" "$UTILS"; do
  [[ -f "$WT/$path" ]] || fail "REQUIRED_FILE_MISSING:$path"
done

echo "RUNNER_SHA256=$(sha256sum "$WT/$RUNNER" | awk '{print $1}')"
echo "CHILD_SHA256=$(sha256sum "$WT/$CHILD" | awk '{print $1}')"
echo "CONTRACT_SHA256=$(sha256sum "$WT/$CONTRACT" | awk '{print $1}')"
python3 -m py_compile "$WT/$RUNNER" || fail 'RUNNER_PY_COMPILE_FAILED'
python3 -m py_compile "$WT/$CHILD" || fail 'CHILD_PY_COMPILE_FAILED'
echo 'RUNNER_PY_COMPILE_PASS=true'
echo 'CHILD_PY_COMPILE_PASS=true'

echo "EXECUTION_LOG=$LOG"
echo 'USER_VIDEO_BUNDLE_UPGRADE_EXECUTION_START=true'
set +e
python3 "$WT/$RUNNER" \
  --data-root "$ROOT" \
  --code-root "$WT" \
  --target-sha "$REMOTE_SHA" \
  --output-dir "$OUTDIR" \
  2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}
set -e

echo
echo '===== USER VIDEO BUNDLE UPGRADE SUMMARY ====='
grep -E '^(MANUAL_VIDEO_CONTRACT=|DEMA_ST_VIDEO_REPLAY=|DEMA_ST_TIMEFRAME_RESULT=|STATE=|SOURCE_VIDEO_COUNT=|MANUAL_CONTRACT_COUNT=|EXECUTABLE_VIDEO_STRATEGY_COUNT=|PROMOTION_CANDIDATES=|PROMOTION_ALLOWED=|SUMMARY_JSON=|MUTATION_COUNT=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 160

echo "FINAL_RC=$RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$RC"
