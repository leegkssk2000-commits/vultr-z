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
  'R7A4D2_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND_START' \
  'MODE=READ_ONLY_AUDITED_FIXED_LAYOUT_ADAPTER_AND_TIMEFRAME_DERIVATION' \
  'EXPECTED_LAYOUT_SIGNATURE=[6,0,1,2,3,4]' \
  'EXPECTED_REQUIRED_SOURCE_COUNT=5' \
  'DERIVED_TIMEFRAMES=5m,15m' \
  'COMPLETE_BUCKETS_ONLY=true' \
  'SOURCE_SHA_REQUIRED=true' \
  'SOURCE_FILE_MUTATION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'CANDIDATE_TARGET_COUNT=36' \
  'EXECUTION_CELL_TARGET_COUNT=216'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

EVIDENCE="$ROOT/runtime/r7a4d2_short_scalp_required_ohlcv_rows_schema_diagnose/rows_schema_diagnose_v1.json"
if [[ ! -f "$EVIDENCE" ]]; then
  echo 'STATE=HOLD_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND'
  echo 'BLOCKER_COUNT=1'
  printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$EVIDENCE"
  echo 'RC=2'
  exit 2
fi

TMP="$(mktemp -d /tmp/r7a4d2-schema-adapter-bind.XXXXXX)" || exit 2
for path in \
  tools/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind.py \
  tests/test_r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind.py
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile "$TMP/tools/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind.py"; then
  echo 'STATE=HOLD_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_SCHEMA_ADAPTER_BIND="$TMP/tools/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind.py"; then
  echo 'STATE=HOLD_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["SCHEMA_ADAPTER_BIND_FOCUSED_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$TMP:$ROOT" python3 "$TMP/tools/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind.py" --root "$ROOT"
RC=$?

echo 'R7A4D2_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND_COMPLETE'
echo "RC=$RC"
exit "$RC"
