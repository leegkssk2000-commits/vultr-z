#!/usr/bin/env bash
set -u
ROOT="${1:-/home/z/z}"
SHA="${2:-}"
RC=0
TMP=""
cleanup(){ [[ -n "$TMP" ]] && rm -rf "$TMP"; }
trap cleanup EXIT

[[ -n "$SHA" ]] || { echo 'BLOCKERS=["MISSING_SHA"]'; exit 2; }
git -C "$ROOT" -c safe.directory="$ROOT" cat-file -e "$SHA^{commit}" || exit 2
TMP="$(mktemp -d /tmp/r7_restore25.XXXXXXXX)"
mkdir -p "$TMP/tools" "$TMP/backend/contracts"

git -C "$ROOT" -c safe.directory="$ROOT" show "$SHA:tools/r7_restore25_canonical_source_recovery.py" \
  > "$TMP/tools/r7_restore25_canonical_source_recovery.py" || RC=2
git -C "$ROOT" -c safe.directory="$ROOT" show "$SHA:backend/contracts/ZOS_R7_RESTORE25_CANONICAL_SOURCE_RECOVERY_v1.json" \
  > "$TMP/backend/contracts/ZOS_R7_RESTORE25_CANONICAL_SOURCE_RECOVERY_v1.json" || RC=2

if [[ "$RC" -eq 0 ]]; then
  python3 -m py_compile "$TMP/tools/r7_restore25_canonical_source_recovery.py" || RC=2
fi
if [[ "$RC" -eq 0 ]]; then
  grep -q 'ARTIFACT_PAIR_NORMALIZED_AST_IDENTICAL' "$TMP/tools/r7_restore25_canonical_source_recovery.py" || RC=2
  grep -q 'HISTORICAL_GIT_BLOB_MATCHES_ARTIFACT_AST' "$TMP/tools/r7_restore25_canonical_source_recovery.py" || RC=2
  grep -q 'rollback(created, overwritten)' "$TMP/tools/r7_restore25_canonical_source_recovery.py" || RC=2
fi

if [[ "$RC" -eq 0 ]]; then
  echo R7_RESTORE25_START
  echo MODE=ATOMIC_CANONICAL_SOURCE_RECOVERY
  echo SOURCE_MUTATION_SCOPE=backend/strategies_only
  echo REGISTRY_MUTATION_SCOPE=backend/strategy25/canonical_strategy_registry_v1.json
  echo ROUTER_MUTATION_ALLOWED=false
  echo SERVICE_MUTATION_ALLOWED=false
  echo SIMULATION_REPLAY_EXECUTION_ALLOWED=false
  echo SHADOW_START_ALLOWED=false
  echo PAPER_LIVE_ORDER_ALLOWED=false
  python3 "$TMP/tools/r7_restore25_canonical_source_recovery.py" \
    --root "$ROOT" \
    --target-sha "$SHA" \
    --contract "$TMP/backend/contracts/ZOS_R7_RESTORE25_CANONICAL_SOURCE_RECOVERY_v1.json" \
    --apply || RC=$?
fi

echo R7_RESTORE25_BOOTSTRAP_COMPLETE
echo RC="$RC"
exit "$RC"
