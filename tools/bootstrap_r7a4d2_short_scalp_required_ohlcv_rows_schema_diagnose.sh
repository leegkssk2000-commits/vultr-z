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
  'OHLC_SAME_PRICE_SCALE_RATIO_REQUIRED=0.99' \
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

python3 - "$TMP/tools/r7a4d2_short_scalp_required_ohlcv_rows_schema_diagnose.py" "$TMP/tests/test_r7a4d2_short_scalp_required_ohlcv_rows_schema_diagnose.py" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
test = Path(sys.argv[2])
text = source.read_text(encoding="utf-8")

patches = [
    (
        """    numeric_count = 0
    positive_count = 0
    geometry_count = 0
    nonzero_spread_count = 0
""",
        """    numeric_count = 0
    positive_count = 0
    geometry_count = 0
    nonzero_spread_count = 0
    same_price_scale_count = 0
    price_scale_ratios: list[float] = []
""",
    ),
    (
        """        open_v, high_v, low_v, close_v = [float(value) for value in values]
        numeric_count += 1
""",
        """        open_v, high_v, low_v, close_v = [float(value) for value in values]
        numeric_count += 1
        price_floor = min(abs(open_v), abs(high_v), abs(low_v), abs(close_v))
        price_ceiling = max(abs(open_v), abs(high_v), abs(low_v), abs(close_v))
        if price_floor > 0:
            price_scale_ratio = price_ceiling / price_floor
            price_scale_ratios.append(price_scale_ratio)
            if price_scale_ratio <= 1.25:
                same_price_scale_count += 1
""",
    ),
    (
        """        \"nonzero_spread_ratio\": ratio(nonzero_spread_count, total),
    }
""",
        """        \"nonzero_spread_ratio\": ratio(nonzero_spread_count, total),
        \"same_price_scale_ratio\": ratio(same_price_scale_count, total),
        \"median_price_scale_ratio\": statistics.median(price_scale_ratios) if price_scale_ratios else None,
        \"p95_price_scale_ratio\": percentile(price_scale_ratios, 0.95),
    }
""",
    ),
    (
        """            if ohlc[\"numeric_ratio\"] < 0.95 or ohlc[\"geometry_ratio\"] < 0.95 or ohlc[\"positive_ratio\"] < 0.95:
""",
        """            if (
                ohlc[\"numeric_ratio\"] < 0.95
                or ohlc[\"geometry_ratio\"] < 0.95
                or ohlc[\"positive_ratio\"] < 0.95
                or ohlc[\"same_price_scale_ratio\"] < 0.95
            ):
""",
    ),
    (
        """        and float(top[0][\"ohlc_profile\"][\"geometry_ratio\"]) >= 0.99
        and float(top[0][\"timestamp_profile\"][\"strict_increase_ratio\"]) >= 0.99
""",
        """        and float(top[0][\"ohlc_profile\"][\"geometry_ratio\"]) >= 0.99
        and float(top[0][\"ohlc_profile\"][\"same_price_scale_ratio\"]) >= 0.99
        and float(top[0][\"timestamp_profile\"][\"strict_increase_ratio\"]) >= 0.99
""",
    ),
]

for old, new in patches:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"PRICE_SCALE_PATCH_ANCHOR_INVALID:{count}:{old[:48]!r}")
    text = text.replace(old, new, 1)
source.write_text(text, encoding="utf-8")

test_text = test.read_text(encoding="utf-8")
old_test = """        # Auxiliary zero-volume column must not be eligible as a positive OHLC price.
        volume = 0.0
"""
new_test = """        # Positive auxiliary volume must still be rejected as an OHLC price by scale parity.
        volume = 1000.0 + index
"""
if test_text.count(old_test) != 1:
    raise SystemExit(f"POSITIVE_VOLUME_TEST_PATCH_ANCHOR_INVALID:{test_text.count(old_test)}")
test.write_text(test_text.replace(old_test, new_test, 1), encoding="utf-8")
PY
PATCH_RC=$?
if [[ "$PATCH_RC" != "0" ]]; then
  echo 'STATE=HOLD_SHORT_SCALP_REQUIRED_OHLCV_ROWS_SCHEMA_DIAGNOSE_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["OHLC_PRICE_SCALE_RUNTIME_PATCH_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo 'STATE=PASS_OHLC_PRICE_SCALE_RUNTIME_PATCH'
echo 'POSITIVE_VOLUME_COLUMN_EXCLUDED_FROM_OHLC=true'

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
