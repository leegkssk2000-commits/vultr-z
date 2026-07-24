#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
EXPECTED_SHA="${2:-}"
BRANCH='r7a4d-historical-simulation-3600-v1'
RUNNER='tools/r7a4d2_trading_nerd_mtf_supertrend_video_oos.py'
CHILD='backend/strategies/authentic/trading_nerd_mtf_supertrend_video.py'
CONTRACT='research/trading_nerd_mtf_supertrend_video_contract_v1.json'
OUTDIR="$ROOT/runtime/r7a4d2_trading_nerd_mtf_supertrend_video_oos"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/trading_nerd_mtf_supertrend_video_oos_${STAMP}.log"
TMPROOT="$(mktemp -d /tmp/r7a4d2-trading-nerd-mtf.XXXXXX)"
WT="$TMPROOT/worktree"

cleanup() {
  git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
  rm -rf "$TMPROOT"
}
trap cleanup EXIT

fail() {
  echo 'STATE=HOLD_TRADING_NERD_MTF_SUPERTREND_VIDEO_OOS_INPUT'
  echo "BLOCKERS=[\"$1\"]"
  echo 'RC=2'
  exit 2
}

printf '%s\n' \
  'R7A4D2_TRADING_NERD_MTF_SUPERTREND_VIDEO_OOS_START' \
  'MODE=READ_ONLY_YOUTUBE_TRADINGVIEW_PUBLIC_RULE_CONTRACT_OOS' \
  'YOUTUBE_URL=https://www.youtube.com/watch?v=Yl5WCVMllC4' \
  'TRADINGVIEW_URL=https://www.tradingview.com/script/cPjnon3O-MTF-Supertrend-Trading-Nerd/' \
  'CORE=HTF_CONFIRMED_SUPERTREND_DIRECTION_PLUS_LTF_SUPERTREND_FLIP' \
  'EXIT=CURRENT_TIMEFRAME_SUPERTREND_TRAILING_STOP' \
  'TAKE_PROFIT=DISABLED_DEFAULT' \
  'ADX_FILTER=DISABLED_BASELINE' \
  'HTF_FLIP_ENTRY=DISABLED_BASELINE' \
  'PAIRS=5m_to_15m,5m_to_60m,15m_to_60m,15m_to_240m' \
  'POST_SELECTION_ALLOWED=false' \
  'LEGACY_PARENT_MUTATION_ALLOWED=false' \
  'FAILED_PULLBACK_CHILD_MUTATION_ALLOWED=false' \
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
for path in "$RUNNER" "$CHILD" "$CONTRACT"; do
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
echo 'VIDEO_RULE_CONTRACT_OOS_EXECUTION_START=true'
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
echo '===== TRADING NERD MTF SUPERTREND VIDEO OOS SUMMARY ====='
grep -E '^(VIDEO_REPLAY_RESULT=|VIDEO_PAIR_RESULT=|STATE=|PROMOTION_CANDIDATE_COUNT=|PROMOTION_CANDIDATES=|PROMOTION_ALLOWED=|SUMMARY_JSON=|MUTATION_COUNT=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 120

echo "FINAL_RC=$RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$RC"
