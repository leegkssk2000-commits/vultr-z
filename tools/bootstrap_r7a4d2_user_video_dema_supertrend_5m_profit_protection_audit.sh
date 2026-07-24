#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
EXPECTED_SHA="${2:-}"
BRANCH='r7a4d-historical-simulation-3600-v1'
RUNNER='tools/r7a4d2_user_video_dema_supertrend_5m_profit_protection_audit.py'
CHILD='backend/strategies/authentic/tradinglab_dema_supertrend_video_v1.py'
CONTRACT='research/user_video_dema_supertrend_5m_profit_protection_audit_v1.json'
UTILS='tools/r7a4d2_js_techtrading_supertrend_pullback_exact_oos_replay.py'
SOURCE_SUMMARY="$ROOT/runtime/r7a4d2_user_supplied_video_bundle_upgrade/user_supplied_video_bundle_upgrade_summary_v1.json"
LOSS_SUMMARY="$ROOT/runtime/r7a4d2_user_video_dema_supertrend_loss_anatomy/user_video_dema_supertrend_loss_anatomy_v1.json"
OUTDIR="$ROOT/runtime/r7a4d2_user_video_dema_supertrend_5m_profit_protection_audit"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/user_video_dema_supertrend_5m_profit_protection_audit_${STAMP}.log"
TMPROOT="$(mktemp -d /tmp/r7a4d2-5m-profit-protection.XXXXXX)"
WT="$TMPROOT/worktree"

cleanup() {
  git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
  rm -rf "$TMPROOT"
}
trap cleanup EXIT

fail() {
  echo 'STATE=HOLD_USER_VIDEO_DEMA_SUPERTREND_5M_PROFIT_PROTECTION_INPUT'
  echo "BLOCKERS=[\"$1\"]"
  echo 'RC=2'
  exit 2
}

printf '%s\n' \
  'R7A4D2_USER_VIDEO_DEMA_SUPERTREND_5M_PROFIT_PROTECTION_AUDIT_START' \
  'MODE=READ_ONLY_BAR_LEVEL_FIXED_VARIANT_EXIT_OVERLAY_AUDIT' \
  'SOURCE_VIDEO=https://www.youtube.com/watch?v=g-PLctW8aU0' \
  'SOURCE_STRATEGY=tradinglab_dema200_supertrend12x3_video_v1' \
  'TARGET_TIMEFRAME=5m' \
  'VARIANT_0=BASELINE_SUPERTREND_TRAIL' \
  'VARIANT_1=P30_AT_0_5R_ONLY' \
  'VARIANT_2=P30_AT_0_5R_COST_BE' \
  'VARIANT_3=P30_AT_0_5R_COST_BE_LOCK_0_25R_AT_1R' \
  'SAME_BAR_POLICY=EXISTING_STOP_FIRST_THEN_NEW_RAISED_STOP_ELIGIBLE' \
  'POST_SELECTION_ALLOWED=false' \
  'COUNTERFACTUAL_MFE_ORDERING_ALLOWED=false' \
  'SOURCE_STRATEGY_MUTATION_ALLOWED=false' \
  'CANONICAL25_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'PROMOTION_ALLOWED=false' \
  'WORKTREE_POLICY=DO_NOT_TOUCH'

[[ -d "$ROOT/.git" ]] || fail 'ROOT_NOT_GIT_REPOSITORY'
[[ -n "$EXPECTED_SHA" ]] || fail 'EXPECTED_SHA_REQUIRED'
[[ -f "$SOURCE_SUMMARY" ]] || fail "SOURCE_SUMMARY_MISSING:$SOURCE_SUMMARY"
[[ -f "$LOSS_SUMMARY" ]] || fail "LOSS_SUMMARY_MISSING:$LOSS_SUMMARY"
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
echo "SOURCE_SUMMARY_SHA256=$(sha256sum "$SOURCE_SUMMARY" | awk '{print $1}')"
echo "LOSS_SUMMARY_SHA256=$(sha256sum "$LOSS_SUMMARY" | awk '{print $1}')"
python3 -m py_compile "$WT/$RUNNER" || fail 'RUNNER_PY_COMPILE_FAILED'
python3 -m py_compile "$WT/$CHILD" || fail 'CHILD_PY_COMPILE_FAILED'
echo 'RUNNER_PY_COMPILE_PASS=true'
echo 'CHILD_PY_COMPILE_PASS=true'

echo "EXECUTION_LOG=$LOG"
echo 'PROFIT_PROTECTION_AUDIT_EXECUTION_START=true'
set +e
python3 "$WT/$RUNNER" \
  --data-root "$ROOT" \
  --code-root "$WT" \
  --target-sha "$REMOTE_SHA" \
  --source-summary "$SOURCE_SUMMARY" \
  --loss-summary "$LOSS_SUMMARY" \
  --output-dir "$OUTDIR" \
  2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}
set -e

echo
echo '===== 5M PROFIT PROTECTION AUDIT SUMMARY ====='
grep -E '^(PROTECTION_CELL=|PROTECTION_VARIANT_RESULT=|STATE=|BASELINE_PARITY_PASS=|ECONOMIC_SURVIVOR_COUNT=|ECONOMIC_SURVIVORS=|MECHANISTIC_IMPROVEMENTS=|PROMOTION_ALLOWED=|SELECTION_ALLOWED=|SUMMARY_JSON=|MUTATION_COUNT=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 180

echo "FINAL_RC=$RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$RC"
