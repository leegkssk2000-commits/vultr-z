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
  'R7A4D2_SHORT_SCALP_TIMEFRAME_CANDIDATE_DISCOVERY_36_START' \
  'MODE=READ_ONLY_CANONICAL_SCALP_SHORT_SIGNAL_AND_NATURAL_R_DISTANCE_DISCOVERY' \
  'STRATEGY_ID=scalp_snap' \
  'SIDE=short' \
  'ARCHITECTURES=5m_5m,15m_15m,15m_5m' \
  'CANDIDATE_TARGET_PER_ARCHITECTURE=12' \
  'DISCOVERY_TARGET_PER_ARCHITECTURE=6' \
  'VALIDATION_TARGET_PER_ARCHITECTURE=6' \
  'CANDIDATE_TARGET_COUNT=36' \
  'EXECUTION_CELL_TARGET_COUNT=216' \
  'CONDITIONAL_REQUIRED_RAW_DISTANCE_PCT=0.9696969697' \
  'ROBUST_REQUIRED_RAW_DISTANCE_PCT=1.28' \
  'SCENARIO_FOLD_SOURCE=window_enumeration' \
  'FUTURE_PNL_SELECTION_ALLOWED=false' \
  'SHORT_EXECUTION_ALLOWED=false' \
  'LONG_EXECUTION_ALLOWED=false' \
  'SOURCE_FILE_MUTATION_ALLOWED=false' \
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
  echo 'STATE=HOLD_SHORT_SCALP_TIMEFRAME_CANDIDATE_DISCOVERY_36'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

REQUIRED="$ROOT/runtime/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind/adapter_bind_v1.json"
if [[ ! -f "$REQUIRED" ]]; then
  echo 'STATE=HOLD_SHORT_SCALP_TIMEFRAME_CANDIDATE_DISCOVERY_36'
  echo 'BLOCKER_COUNT=1'
  printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$REQUIRED"
  echo 'RC=2'
  exit 2
fi

TMP="$(mktemp -d /tmp/r7a4d2-scalp-discovery36.XXXXXX)" || exit 2
for path in \
  tools/r7a4d_historical_simulation_3600.py \
  tools/r7a4d2_entry_chain_minimal_patch.py \
  tools/r7a4d2_short_execution_harness_minimal_patch.py \
  tools/r7a4d2_short_rr_sidecar_patch.py \
  tools/r7a4d2_short_rr_exact_math_patch.py \
  tools/r7a4d2_short_candidate_trace_patch.py \
  tools/r7a4d2_short_discovery_trace_only_patch.py \
  tools/r7a4d2_short_scalp_discovery_fold_patch.py \
  tools/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind.py \
  tools/r7a4d2_short_scalp_timeframe_candidate_discovery_36.py \
  tests/test_r7a4d2_short_discovery_trace_only_patch.py \
  tests/test_r7a4d2_short_scalp_discovery_fold_patch.py \
  tests/test_r7a4d2_short_scalp_timeframe_candidate_discovery_36.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_SCALP_TIMEFRAME_CANDIDATE_DISCOVERY_36'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile \
  "$TMP/tools/r7a4d2_entry_chain_minimal_patch.py" \
  "$TMP/tools/r7a4d2_short_execution_harness_minimal_patch.py" \
  "$TMP/tools/r7a4d2_short_rr_sidecar_patch.py" \
  "$TMP/tools/r7a4d2_short_rr_exact_math_patch.py" \
  "$TMP/tools/r7a4d2_short_candidate_trace_patch.py" \
  "$TMP/tools/r7a4d2_short_discovery_trace_only_patch.py" \
  "$TMP/tools/r7a4d2_short_scalp_discovery_fold_patch.py" \
  "$TMP/tools/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind.py" \
  "$TMP/tools/r7a4d2_short_scalp_timeframe_candidate_discovery_36.py"; then
  echo 'STATE=HOLD_SHORT_SCALP_TIMEFRAME_CANDIDATE_DISCOVERY_36'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4d2_entry_chain_minimal_patch.py" \
  --input "$TMP/tools/r7a4d_historical_simulation_3600.py" \
  --output "$TMP/tools/runner_entry.py" || exit 2
python3 "$TMP/tools/r7a4d2_short_execution_harness_minimal_patch.py" \
  --input "$TMP/tools/runner_entry.py" \
  --output "$TMP/tools/runner_short.py" || exit 2
python3 "$TMP/tools/r7a4d2_short_rr_sidecar_patch.py" \
  --input "$TMP/tools/runner_short.py" \
  --output "$TMP/tools/runner_rr_linear.py" || exit 2
python3 "$TMP/tools/r7a4d2_short_rr_exact_math_patch.py" \
  --input "$TMP/tools/runner_rr_linear.py" \
  --output "$TMP/tools/runner_rr.py" || exit 2
python3 "$TMP/tools/r7a4d2_short_candidate_trace_patch.py" \
  --input "$TMP/tools/runner_rr.py" \
  --output "$TMP/tools/runner_trace.py" || exit 2
python3 "$TMP/tools/r7a4d2_short_discovery_trace_only_patch.py" \
  --input "$TMP/tools/runner_trace.py" \
  --output "$TMP/tools/runner_discovery.py" || exit 2
python3 "$TMP/tools/r7a4d2_short_scalp_discovery_fold_patch.py" \
  --input "$TMP/tools/r7a4d2_short_scalp_timeframe_candidate_discovery_36.py" \
  --output "$TMP/tools/scalp_discovery_fold_bound.py" || exit 2

if ! python3 -m py_compile \
  "$TMP/tools/runner_discovery.py" \
  "$TMP/tools/scalp_discovery_fold_bound.py"; then
  echo 'STATE=HOLD_SHORT_SCALP_TIMEFRAME_CANDIDATE_DISCOVERY_36'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["DISCOVERY_PATCHED_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_DISCOVERY_PATCH="$TMP/tools/r7a4d2_short_discovery_trace_only_patch.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_discovery_trace_only_patch.py"; then
  echo 'STATE=HOLD_SHORT_SCALP_TIMEFRAME_CANDIDATE_DISCOVERY_36'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["DISCOVERY_TRACE_PATCH_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_SCALP_DISCOVERY_FOLD_PATCH="$TMP/tools/r7a4d2_short_scalp_discovery_fold_patch.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_scalp_discovery_fold_patch.py"; then
  echo 'STATE=HOLD_SHORT_SCALP_TIMEFRAME_CANDIDATE_DISCOVERY_36'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["SCALP_DISCOVERY_FOLD_PATCH_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_SCALP_DISCOVERY_36="$TMP/tools/scalp_discovery_fold_bound.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_scalp_timeframe_candidate_discovery_36.py"; then
  echo 'STATE=HOLD_SHORT_SCALP_TIMEFRAME_CANDIDATE_DISCOVERY_36'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["SCALP_DISCOVERY_FOCUSED_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$ROOT:$TMP" python3 "$TMP/tools/scalp_discovery_fold_bound.py" \
  --root "$ROOT" \
  --runner "$TMP/tools/runner_discovery.py" \
  --adapter "$TMP/tools/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind.py" \
  --contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?

echo 'R7A4D2_SHORT_SCALP_TIMEFRAME_CANDIDATE_DISCOVERY_36_COMPLETE'
echo "RC=$RC"
exit "$RC"
