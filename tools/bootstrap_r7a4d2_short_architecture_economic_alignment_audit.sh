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
  'R7A4D2_SHORT_ARCHITECTURE_ECONOMIC_ALIGNMENT_AUDIT_START' \
  'MODE=READ_ONLY_EXISTING_600_RESULT_ARCHITECTURE_AND_ECONOMIC_ALIGNMENT_AUDIT' \
  'NEW_STRATEGY_EXECUTION_ALLOWED=false' \
  'NEW_MARKET_REPLAY_ALLOWED=false' \
  'SHORT_TARGET_SELECTION_BASIS_AUDIT=true' \
  'STRATEGY_FAMILY_HETEROGENEITY_AUDIT=true' \
  'NATIVE_TIMEFRAME_CONTRACT_AUDIT=true' \
  'UNIVERSAL_RR_ALIGNMENT_AUDIT=true' \
  'SIMPLE_BENCHMARK_PRESENCE_AUDIT=true' \
  'EXISTING_POLICY_RESULTS_REAGGREGATION=true' \
  'SCALP_CANDIDATE_QUOTA_ALIGNMENT_AUDIT=true' \
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
  echo 'STATE=HOLD_SHORT_ARCHITECTURE_ECONOMIC_ALIGNMENT_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_execution_harness_plan/short_execution_harness_plan_v1.json" \
  "$ROOT/runtime/r7a4d_semantic_parity_audit/semantic_parity_audit_v1.json" \
  "$ROOT/runtime/r7a4d2_short_rr_policy_plan/short_rr_policy_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_rr_sidecar_counterfactual/counterfactual_proof_v1.json" \
  "$ROOT/runtime/r7a4d2_short_rr_sidecar_counterfactual/policy_results_600_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_scalp_timeframe_candidate_discovery_36/candidate_discovery_v1.json" \
  "$ROOT/backend/strategy25/canonical_strategy_registry_v1.json" \
  "$ROOT/backend/strategy25/canonical_strategy25_config_v1.json"
 do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_ARCHITECTURE_ECONOMIC_ALIGNMENT_AUDIT_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-architecture-audit.XXXXXX)" || exit 2
mkdir -p "$TMP/tools"
if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_short_architecture_economic_alignment_audit.py" \
  > "$TMP/tools/r7a4d2_short_architecture_economic_alignment_audit.py"; then
  echo 'STATE=HOLD_SHORT_ARCHITECTURE_ECONOMIC_ALIGNMENT_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["MATERIALIZE_FAILED:tools/r7a4d2_short_architecture_economic_alignment_audit.py"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$TMP/tools/r7a4d2_short_architecture_economic_alignment_audit.py"; then
  echo 'STATE=HOLD_SHORT_ARCHITECTURE_ECONOMIC_ALIGNMENT_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TMP/tools/r7a4d2_short_architecture_economic_alignment_audit.py" --self-test; then
  echo 'STATE=HOLD_SHORT_ARCHITECTURE_ECONOMIC_ALIGNMENT_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["ARCHITECTURE_AUDIT_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4d2_short_architecture_economic_alignment_audit.py" --root "$ROOT"
RC=$?

echo 'R7A4D2_SHORT_ARCHITECTURE_ECONOMIC_ALIGNMENT_AUDIT_COMPLETE'
echo "RC=$RC"
exit "$RC"
