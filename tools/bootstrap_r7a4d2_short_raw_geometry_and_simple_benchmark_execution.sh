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
  'R7A4D2_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_START' \
  'MODE=READ_ONLY_ACTUAL_RAW_SIGNAL_GEOMETRY_AND_SAME_DATA_BENCHMARK_EXECUTION' \
  'EXPECTED_EXECUTION_LANE_COUNT=36' \
  'EXPECTED_FROZEN_SEGMENT_COUNT=24' \
  'EXPECTED_RAW_GEOMETRY_SCAN_COUNT=864' \
  'STRATEGY_LANE_COUNT=25' \
  'BENCHMARK_LANE_COUNT=11' \
  'UNIVERSAL_RR_APPLIED=false' \
  'FIXED_CANDIDATE_QUOTA_ALLOWED=false' \
  'FUTURE_PNL_SELECTION_ALLOWED=false' \
  'PAST_ONLY_WARMUP_REQUIRED=true' \
  'MEASUREMENT_WINDOW_ONLY_SIGNAL_CAPTURE=true' \
  'SAME_DATA_COST_TIMING_COLLISION_REQUIRED=true' \
  'STRATEGY_SOURCE_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'FULL_3600_REEXECUTION_ALLOWED=false' \
  'EVENT_REPLAY_2880_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind/adapter_bind_v1.json" \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json" \
  "$ROOT/backend/strategy25/canonical_strategy_registry_v1.json" \
  "$ROOT/backend/strategy25/canonical_strategy25_config_v1.json"
 do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-raw-geometry.XXXXXX)" || exit 2
for path in \
  tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py \
  tools/r7a4d_historical_simulation_3600.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 - "$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
source = path.read_text(encoding="utf-8")
old = "1_700_000_000_000 + index * 60_000"
new = "1_700_000_100_000 + index * 60_000"
count = source.count(old)
if count != 1:
    raise SystemExit(f"SELF_TEST_TIMESTAMP_PATCH_ANCHOR_INVALID:{count}")
path.write_text(source.replace(old, new, 1), encoding="utf-8")
print("STATE=PASS_RAW_GEOMETRY_SELF_TEST_TIME_ALIGNMENT_PATCH")
print("SELF_TEST_5M_BUCKET_ALIGNMENT=true")
print("PATCH_SCOPE=temporary_execution_copy_only")
PY
then
  echo 'STATE=HOLD_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["RAW_GEOMETRY_SELF_TEST_TIME_ALIGNMENT_PATCH_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile \
  "$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py" \
  "$TMP/tools/r7a4d_historical_simulation_3600.py"; then
  echo 'STATE=HOLD_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py" --self-test; then
  echo 'STATE=HOLD_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["RAW_GEOMETRY_EXECUTION_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --runner "$TMP/tools/r7a4d_historical_simulation_3600.py" \
  --a4d-contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?

echo 'R7A4D2_SHORT_RAW_GEOMETRY_AND_SIMPLE_BENCHMARK_EXECUTION_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
