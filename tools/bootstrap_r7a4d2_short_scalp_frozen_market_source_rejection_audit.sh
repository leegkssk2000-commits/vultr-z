#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
TMP=""
RC=2

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_SHORT_SCALP_FROZEN_MARKET_SOURCE_REJECTION_AUDIT_START' \
  'MODE=READ_ONLY_SELECTED_LINEAGE_REQUIRED_VS_AUXILIARY_SOURCE_AUDIT' \
  'SELECTED_MANIFEST_REQUIRED_SOURCE_REJECT_BLOCKS=true' \
  'AUXILIARY_REJECT_BLOCKS=false' \
  'SHA_OHLC_TIMESTAMP_MINIMUM_ROWS_REQUIRED=true' \
  'MINIMUM_SOURCE_ROWS=640' \
  'REQUIRED_DERIVED_TIMEFRAMES=5m,15m' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'FULL_3600_REEXECUTION_ALLOWED=false' \
  'EVENT_REPLAY_2880_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_SCALP_FROZEN_MARKET_SOURCE_REJECTION_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4_simulation_replay_input_freeze/frozen_input_manifest_v1.json" \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json"
 do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_SCALP_FROZEN_MARKET_SOURCE_REJECTION_AUDIT_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-frozen-source-audit.XXXXXX)" || exit 2
for path in \
  tools/r7a4d2_short_scalp_frozen_market_source_rejection_audit.py \
  tools/r7a4c_historical_simulation_input_lineage.py \
  tests/test_r7a4d2_short_scalp_frozen_market_source_rejection_audit.py \
  backend/contracts/ZOS_R7A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE_v1.json
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_SCALP_FROZEN_MARKET_SOURCE_REJECTION_AUDIT_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile \
  "$TMP/tools/r7a4d2_short_scalp_frozen_market_source_rejection_audit.py" \
  "$TMP/tools/r7a4c_historical_simulation_input_lineage.py"; then
  echo 'STATE=HOLD_SHORT_SCALP_FROZEN_MARKET_SOURCE_REJECTION_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_FROZEN_SOURCE_AUDIT="$TMP/tools/r7a4d2_short_scalp_frozen_market_source_rejection_audit.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_scalp_frozen_market_source_rejection_audit.py"; then
  echo 'STATE=HOLD_SHORT_SCALP_FROZEN_MARKET_SOURCE_REJECTION_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["FROZEN_SOURCE_REJECTION_AUDIT_FOCUSED_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$TMP:$ROOT" python3 "$TMP/tools/r7a4d2_short_scalp_frozen_market_source_rejection_audit.py" \
  --root "$ROOT" \
  --runner "$TMP/tools/r7a4c_historical_simulation_input_lineage.py" \
  --contract "$TMP/backend/contracts/ZOS_R7A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE_v1.json"
RC=$?

echo 'R7A4D2_SHORT_SCALP_FROZEN_MARKET_SOURCE_REJECTION_AUDIT_COMPLETE'
echo "RC=$RC"
exit "$RC"
