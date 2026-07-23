#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
TMP=""
OUTDIR="$ROOT/runtime/r7a4d2_ma5_observer_material_reclassify"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/reclassify_and_plan_${STAMP}.log"

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_MA5_OBSERVER_MATERIAL_RECLASSIFY_AND_SURVIVOR_OOS_PLAN_START' \
  'MODE=READ_ONLY_EVIDENCE_RECLASSIFICATION_PLUS_FIXED_BATCH_PLAN' \
  'MA5_STANDALONE_ALLOWED=false' \
  'MA5_EXIT_REPAIR_ALLOWED=false' \
  'CANDIDATE_RESELECTION_ALLOWED=false' \
  'PARAMETER_OPTIMIZATION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'WORKTREE_POLICY=DO_NOT_TOUCH'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_MA5_OBSERVER_MATERIAL_RECLASSIFY_INPUT'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

mkdir -p "$OUTDIR" || exit 2
TMP="$(mktemp -d /tmp/r7a4d2-ma5-reclassify.XXXXXX)" || exit 2
TARGET="$TMP/r7a4d2_ma5_observer_material_reclassify_and_survivor_oos_plan.py"

if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_ma5_observer_material_reclassify_and_survivor_oos_plan.py" > "$TARGET"; then
  echo 'STATE=HOLD_MA5_OBSERVER_MATERIAL_RECLASSIFY_INPUT'
  echo 'BLOCKERS=["TARGET_MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$TARGET"; then
  echo 'STATE=HOLD_MA5_OBSERVER_MATERIAL_RECLASSIFY_INPUT'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo "TARGET_SHA=$SHA"
echo "TARGET_SCRIPT_SHA256=$(sha256sum "$TARGET" | awk '{print $1}')"
echo "EXECUTION_LOG=$LOG"
echo 'RECLASSIFICATION_EXECUTION_START=true'

python3 "$TARGET" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}

echo
echo '===== MA5 RECLASSIFY + SURVIVOR OOS PLAN SUMMARY ====='
grep -E '^(STATE=|BLOCKER_COUNT=|MA5_CLASSIFICATION=|MA5_STANDALONE_ALLOWED=|MA5_EXIT_REPAIR_ALLOWED=|MA5_OOS_BASE_NET_R=|MA5_OOS_ADVERSE_NET_R=|MA5_OOS_SEVERE_NET_R=|REMAINING_OOS_CANDIDATE_COUNT=|OOS_CANDIDATE=|RECLASS_JSON=|BATCH_PLAN_JSON=|INPUT_MUTATION_COUNT=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 160

echo "FINAL_RC=$RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$RC"
