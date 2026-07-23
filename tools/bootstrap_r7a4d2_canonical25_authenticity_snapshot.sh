#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
TMP=""
OUTDIR="$ROOT/runtime/r7a4d2_canonical25_authenticity_snapshot"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/authenticity_snapshot_${STAMP}.log"

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_CANONICAL25_AUTHENTICITY_SNAPSHOT_START' \
  'MODE=READ_ONLY_GIT_OBJECT_MATERIALIZATION_AND_RULE_EXTRACTION' \
  'LOCAL_CONTRACT_REQUIRED=false' \
  'EXTERNAL_SOURCE_MAP_REQUIRED=true' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'PARAMETER_OPTIMIZATION_ALLOWED=false' \
  'PERFORMANCE_UPGRADE_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'WORKTREE_POLICY=DO_NOT_TOUCH'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_CANONICAL25_AUTHENTICITY_SNAPSHOT_INPUT'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

mkdir -p "$OUTDIR" || exit 2
TMP="$(mktemp -d /tmp/r7a4d2-canonical25-auth.XXXXXX)" || exit 2
TARGET="$TMP/r7a4d2_canonical25_authenticity_snapshot.py"

if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_canonical25_authenticity_snapshot.py" > "$TARGET"; then
  echo 'STATE=HOLD_CANONICAL25_AUTHENTICITY_SNAPSHOT_INPUT'
  echo 'BLOCKERS=["TARGET_SCRIPT_MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! git -C "$ROOT" archive "$SHA" \
  backend/strategy25/canonical_strategy_registry_v1.json \
  backend/strategy25/canonical_strategy25_config_v1.json \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json \
  backend/strategies \
  research/canonical25_authenticity_source_map_v1.json \
  | tar -x -C "$TMP"; then
  echo 'STATE=HOLD_CANONICAL25_AUTHENTICITY_SNAPSHOT_INPUT'
  echo 'BLOCKERS=["GIT_EVIDENCE_ARCHIVE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$TARGET"; then
  echo 'STATE=HOLD_CANONICAL25_AUTHENTICITY_SNAPSHOT_INPUT'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo "TARGET_SHA=$SHA"
echo "TARGET_SCRIPT_SHA256=$(sha256sum "$TARGET" | awk '{print $1}')"
echo "MATERIALIZED_CONTRACT_SHA256=$(sha256sum "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json" | awk '{print $1}')"
echo "SOURCE_MAP_SHA256=$(sha256sum "$TMP/research/canonical25_authenticity_source_map_v1.json" | awk '{print $1}')"
echo "EXECUTION_LOG=$LOG"
echo 'AUTHENTICITY_SNAPSHOT_EXECUTION_START=true'

python3 "$TARGET" \
  --materialized-root "$TMP" \
  --output-root "$ROOT" \
  --target-sha "$SHA" \
  2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}

echo
echo '===== CANONICAL25 AUTHENTICITY SNAPSHOT SUMMARY ====='
grep -E '^(STATE=|BLOCKER_COUNT=|CANONICAL_STRATEGY_COUNT=|GIT_OBJECT_MATERIALIZATION=|AUTH_SNAPSHOT=|SNAPSHOT_JSON=|STRATEGY_MUTATION_ALLOWED=|PERFORMANCE_UPGRADE_ALLOWED=|NEXT_STAGE=|BLOCKERS=|RC=)' "$LOG" | tail -n 220

echo "FINAL_RC=$RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$RC"
