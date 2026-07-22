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
  'R7A4D2_SHORT_SCALP_REQUIRED_OHLCV_ROWS_SCHEMA_DIAGNOSE_START' \
  'MODE=READ_ONLY_REQUIRED_SOURCE_ROWS_FIXED_COLUMN_LAYOUT_DIAGNOSE' \
  'EXPECTED_REQUIRED_SOURCE_COUNT=5' \
  'ROWS_CONTAINER_REQUIRED=true' \
  'MATRIX_ROW_LAYOUT_DIAGNOSIS=true' \
  'TIMESTAMP_MONOTONICITY_REQUIRED=true' \
  'OHLC_GEOMETRY_RATIO_REQUIRED=0.99' \
  'UNIQUE_LAYOUT_REQUIRED=true' \
  'SHARED_LAYOUT_ACROSS_REQUIRED_SOURCES=true' \
  'COLUMN_ORDER_GUESSING_ALLOWED=false' \
  'SOURCE_FILE_MUTATION_ALLOWED=false' \
  'FROZEN_MANIFEST_MUTATION_ALLOWED=false' \
  'SELECTED_MANIFEST_MUTATION_ALLOWED=false' \
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
  echo 'STATE=HOLD_SHORT_SCALP_REQUIRED_OHLCV_ROWS_SCHEMA_DIAGNOSE_INPUT'
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
    echo 'STATE=HOLD_SHORT_SCALP_REQUIRED_OHLCV_ROWS_SCHEMA_DIAGNOSE_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-required-rows-schema.XXXXXX)" || exit 2
for path in \
  tools/r7a4d2_short_scalp_required_ohlcv_rows_schema_diagnose.py \
  tests/test_r7a4d2_short_scalp_required_ohlcv_rows_schema_diagnose.py \
  backend/contracts/ZOS_R7A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE_v1.json
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_SCALP_REQUIRED_OHLCV_ROWS_SCHEMA_DIAGNOSE_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile "$TMP/tools/r7a4d2_short_scalp_required_ohlcv_rows_schema_diagnose.py"; then
  echo 'STATE=HOLD_SHORT_SCALP_REQUIRED_OHLCV_ROWS_SCHEMA_DIAGNOSE_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_ROWS_SCHEMA_DIAGNOSE="$TMP/tools/r7a4d2_short_scalp_required_ohlcv_rows_schema_diagnose.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_scalp_required_ohlcv_rows_schema_diagnose.py"; then
  echo 'STATE=HOLD_SHORT_SCALP_REQUIRED_OHLCV_ROWS_SCHEMA_DIAGNOSE_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["ROWS_SCHEMA_DIAGNOSE_FOCUSED_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$TMP:$ROOT" python3 "$TMP/tools/r7a4d2_short_scalp_required_ohlcv_rows_schema_diagnose.py" \
  --root "$ROOT" \
  --contract "$TMP/backend/contracts/ZOS_R7A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE_v1.json"
RC=$?

echo 'R7A4D2_SHORT_SCALP_REQUIRED_OHLCV_ROWS_SCHEMA_DIAGNOSE_COMPLETE'
echo "RC=$RC"
exit "$RC"
