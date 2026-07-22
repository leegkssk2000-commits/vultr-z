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
  'R7A4D2_MARKET_SEGMENT_EXPANSION_FOR_SHORT_CANDIDATES_START' \
  'MODE=READ_ONLY_FROZEN_MARKET_UNIVERSE_DISJOINT_SEGMENT_SIGNAL_DISCOVERY' \
  'SEGMENT_BARS=320' \
  'PREROLL_BARS=320' \
  'MAX_SCAN_SEGMENTS_PER_BUCKET=48' \
  'MAX_SIGNALS_PER_SEGMENT=4' \
  'SHORT_EXECUTION_ALLOWED=false' \
  'LONG_EXECUTION_ALLOWED=false' \
  'CANONICAL_LONG_INTENTS_TRACE_SKIPPED=true' \
  'UNKNOWN_INTENT_FAIL_CLOSED=true' \
  'SIGNAL_TRACE_ALLOWED=true' \
  'PERFORMANCE_BASED_SEGMENT_SELECTION_ALLOWED=false' \
  'PRODUCTION_ADMISSION_EXPANSION_ALLOWED=false' \
  'GRID_REBALANCE_QUARANTINED=true' \
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
  echo 'STATE=HOLD_MARKET_SEGMENT_EXPANSION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_admission_candidate_stress_66/stress66_proof_v1.json" \
  "$ROOT/runtime/r7a4d2_short_admission_allowlist_plan/allowlist_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_execution_harness_plan/short_execution_harness_plan_v1.json" \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json" \
  "$ROOT/runtime/r7a4_simulation_replay_input_freeze/frozen_input_manifest_v1.json"
 do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_MARKET_SEGMENT_EXPANSION_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-market-expansion.XXXXXX)" || exit 2
for path in \
  tools/r7a4d_historical_simulation_3600.py \
  tools/r7a4d2_entry_chain_minimal_patch.py \
  tools/r7a4d2_short_execution_harness_minimal_patch.py \
  tools/r7a4d2_short_rr_sidecar_patch.py \
  tools/r7a4d2_short_rr_exact_math_patch.py \
  tools/r7a4d2_short_candidate_trace_patch.py \
  tools/r7a4d2_short_discovery_trace_only_patch.py \
  tools/r7a4d2_market_expansion_failure_audit_patch.py \
  tools/r7a4d2_market_segment_expansion_for_short_candidates.py \
  tests/test_r7a4d2_short_rr_sidecar_counterfactual.py \
  tests/test_r7a4d2_short_discovery_trace_only_patch.py \
  tests/test_r7a4d2_market_segment_expansion_for_short_candidates.py \
  backend/contracts/ZOS_R7A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE_v1.json \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
 do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_MARKET_SEGMENT_EXPANSION_INPUT'
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
  "$TMP/tools/r7a4d2_market_expansion_failure_audit_patch.py" \
  "$TMP/tools/r7a4d2_market_segment_expansion_for_short_candidates.py"; then
  echo 'STATE=HOLD_MARKET_SEGMENT_EXPANSION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_DISCOVERY_PATCH="$TMP/tools/r7a4d2_short_discovery_trace_only_patch.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_discovery_trace_only_patch.py"; then
  echo 'STATE=HOLD_MARKET_SEGMENT_EXPANSION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["DISCOVERY_PATCH_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4d2_entry_chain_minimal_patch.py" \
  --input "$TMP/tools/r7a4d_historical_simulation_3600.py" \
  --output "$TMP/tools/r7a4d2_entry_patched_runner.py" || exit 2

python3 "$TMP/tools/r7a4d2_short_execution_harness_minimal_patch.py" \
  --input "$TMP/tools/r7a4d2_entry_patched_runner.py" \
  --output "$TMP/tools/r7a4d2_dual_side_runner.py" || exit 2

python3 "$TMP/tools/r7a4d2_short_rr_sidecar_patch.py" \
  --input "$TMP/tools/r7a4d2_dual_side_runner.py" \
  --output "$TMP/tools/r7a4d2_rr_sidecar_linear_runner.py" || exit 2

python3 "$TMP/tools/r7a4d2_short_rr_exact_math_patch.py" \
  --input "$TMP/tools/r7a4d2_rr_sidecar_linear_runner.py" \
  --output "$TMP/tools/r7a4d2_rr_sidecar_runner.py" || exit 2

if ! R7A4D2_RR_RUNNER="$TMP/tools/r7a4d2_rr_sidecar_runner.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_short_rr_sidecar_counterfactual.py"; then
  echo 'STATE=HOLD_MARKET_SEGMENT_EXPANSION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["RR_RUNNER_REGRESSION_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4d2_short_candidate_trace_patch.py" \
  --input "$TMP/tools/r7a4d2_rr_sidecar_runner.py" \
  --output "$TMP/tools/r7a4d2_candidate_trace_runner.py" || exit 2

python3 "$TMP/tools/r7a4d2_short_discovery_trace_only_patch.py" \
  --input "$TMP/tools/r7a4d2_candidate_trace_runner.py" \
  --output "$TMP/tools/r7a4d2_discovery_trace_runner.py" || exit 2

if ! grep -q 'SHORT_DISCOVERY_TRACE_ONLY_V1 = True' "$TMP/tools/r7a4d2_discovery_trace_runner.py" || \
   ! grep -q 'SHORT_POLICY_ALLOWED_REGIMES = frozenset()' "$TMP/tools/r7a4d2_discovery_trace_runner.py" || \
   ! grep -q 'DISCOVERY_NON_SHORT_INTENTS = frozenset' "$TMP/tools/r7a4d2_discovery_trace_runner.py" || \
   ! grep -q 'discovery_non_short_intent_skip_count += 1' "$TMP/tools/r7a4d2_discovery_trace_runner.py"; then
  echo 'STATE=HOLD_MARKET_SEGMENT_EXPANSION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["DISCOVERY_RUNNER_FAIL_CLOSED_MARKER_MISSING"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4d2_market_expansion_failure_audit_patch.py" \
  --input "$TMP/tools/r7a4d2_market_segment_expansion_for_short_candidates.py" \
  --output "$TMP/tools/r7a4d2_market_segment_expansion_audited.py" || exit 2

if ! grep -q '"failure_error_histogram"' "$TMP/tools/r7a4d2_market_segment_expansion_audited.py" || \
   ! grep -q 'FAILURE_ERROR_HISTOGRAM=' "$TMP/tools/r7a4d2_market_segment_expansion_audited.py"; then
  echo 'STATE=HOLD_MARKET_SEGMENT_EXPANSION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["FAILURE_AUDIT_MARKER_MISSING"]'
  echo 'RC=2'
  exit 2
fi

if ! R7A4D2_MARKET_EXPANSION="$TMP/tools/r7a4d2_market_segment_expansion_audited.py" \
  PYTHONPATH="$TMP:$ROOT" python3 -m pytest -q \
  "$TMP/tests/test_r7a4d2_market_segment_expansion_for_short_candidates.py"; then
  echo 'STATE=HOLD_MARKET_SEGMENT_EXPANSION_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["MARKET_EXPANSION_HELPER_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

PYTHONPATH="$ROOT:$TMP" python3 "$TMP/tools/r7a4d2_market_segment_expansion_audited.py" \
  --root "$ROOT" \
  --runner "$TMP/tools/r7a4d2_discovery_trace_runner.py" \
  --a4c-contract "$TMP/backend/contracts/ZOS_R7A4C_HISTORICAL_SIMULATION_INPUT_LINEAGE_v1.json" \
  --a4d-contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?

echo 'R7A4D2_MARKET_SEGMENT_EXPANSION_FOR_SHORT_CANDIDATES_COMPLETE'
echo "RC=$RC"
exit "$RC"
