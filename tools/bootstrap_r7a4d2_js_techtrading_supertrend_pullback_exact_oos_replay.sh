#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
EXPECTED_SHA="${2:-}"
BRANCH='r7a4d-historical-simulation-3600-v1'
RUNNER_PATH='tools/r7a4d2_js_techtrading_supertrend_pullback_exact_oos_replay.py'
CHILD_PATH='backend/strategies/authentic/js_techtrading_supertrend_pullback_authentic.py'
CONTRACT_PATH='research/js_techtrading_supertrend_pullback_authentic_contract_v1.json'
SOURCE_PATH='research/external_sources/js_techtrading_supertrend_strategy_basic_v5.pine'
OUTDIR="$ROOT/runtime/r7a4d2_js_techtrading_supertrend_pullback_exact_oos_replay"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/js_techtrading_supertrend_pullback_exact_oos_${STAMP}.log"
TMPROOT="$(mktemp -d /tmp/r7a4d2-js-supertrend-exact-oos.XXXXXX)"
WT="$TMPROOT/worktree"

cleanup() {
  git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
  rm -rf "$TMPROOT"
}
trap cleanup EXIT

fail() {
  echo 'STATE=HOLD_JS_TECHTRADING_SUPERTREND_PULLBACK_EXACT_OOS_INPUT'
  echo "BLOCKERS=[\"$1\"]"
  echo 'RC=2'
  exit 2
}

printf '%s\n' \
  'R7A4D2_JS_TECHTRADING_SUPERTREND_PULLBACK_EXACT_OOS_START' \
  'MODE=READ_ONLY_SOURCE_CODE_LOCKED_PULLBACK_STRATEGY_AND_TRADINGVIEW_BROKER_EMULATOR_REPLAY' \
  'SOURCE_AUTHOR=JS_TechTrading' \
  'SOURCE_COMMIT=69969aeaf271b2f7b5a7632a1bde43069a0cbe26' \
  'SOURCE_BLOB_SHA=b9a53b75c1af44354fa54d9f919c8e27e0bb8bb5' \
  'STRATEGY_TYPE=Pullback' \
  'ATR_LENGTH=10' \
  'SUPERTREND_FACTOR=3.0' \
  'EMA_ENABLED=true' \
  'EMA_LENGTH=200' \
  'RSI_ENABLED=true' \
  'RSI_LENGTH=14' \
  'RSI_LONG_MIN=50' \
  'RSI_SHORT_MAX=50' \
  'STOP_LOSS_PCT=1.0' \
  'TAKE_PROFIT_PCT=1.0' \
  'QTY_PCT_OF_EQUITY=1.0' \
  'SIGNAL_TIME=CONFIRMED_BAR_CLOSE' \
  'FILL_TIME=NEXT_BAR_OPEN' \
  'ENTRY_BAR_PROTECTION=false' \
  'TERMINAL_FORCE_CLOSE=false' \
  'LEGACY_PARENT_IMMUTABLE=true' \
  'EXISTING_FLIP_CHILD_IMMUTABLE=true' \
  'PARAMETER_OPTIMIZATION_ALLOWED=false' \
  'TIMEFRAME_POST_SELECTION_ALLOWED=false' \
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
for path in "$RUNNER_PATH" "$CHILD_PATH" "$CONTRACT_PATH" "$SOURCE_PATH"; do
  [[ -f "$WT/$path" ]] || fail "REQUIRED_FILE_MISSING:$path"
done

echo "RUNNER_SHA256=$(sha256sum "$WT/$RUNNER_PATH" | awk '{print $1}')"
echo "CHILD_SHA256=$(sha256sum "$WT/$CHILD_PATH" | awk '{print $1}')"
echo "CONTRACT_SHA256=$(sha256sum "$WT/$CONTRACT_PATH" | awk '{print $1}')"
echo "SOURCE_SNAPSHOT_SHA256=$(sha256sum "$WT/$SOURCE_PATH" | awk '{print $1}')"
python3 -m py_compile "$WT/$RUNNER_PATH" || fail 'RUNNER_PY_COMPILE_FAILED'
python3 -m py_compile "$WT/$CHILD_PATH" || fail 'CHILD_PY_COMPILE_FAILED'
echo 'RUNNER_PY_COMPILE_PASS=true'
echo 'CHILD_PY_COMPILE_PASS=true'

echo "EXECUTION_LOG=$LOG"
echo 'EXACT_SOURCE_CONTRACT_AND_OOS_EXECUTION_START=true'
set +e
python3 "$WT/$RUNNER_PATH" \
  --data-root "$ROOT" \
  --code-root "$WT" \
  --target-sha "$REMOTE_SHA" \
  --output-dir "$OUTDIR" \
  2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}
set -e

echo
echo '===== JS TECHTRADING SUPERTREND PULLBACK EXACT OOS SUMMARY ====='
grep -E '^(STATE=|BLOCKER_COUNT=|SOURCE_CONTRACT_PASS=|SIGNAL_PARITY_PASS=|SOURCE_COMMIT=|SOURCE_BLOB_SHA=|REPLAY_RESULT=|TIMEFRAME_RESULT=|SUMMARY_JSON=|INPUT_MUTATION_COUNT=|STRATEGY_MUTATION_COUNT=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 80

echo "FINAL_RC=$RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$RC"
