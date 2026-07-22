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
  'R7A4D2_SHORT_FOUR_WAY_LINEAGE_SELECTIVE_REBASELINE_AUDIT_START' \
  'MODE=READ_ONLY_ACTUAL_REGISTRY_TARGET_PLAN_LINEAGE_AUDIT' \
  'EXPECTED_STRATEGY_COUNT=11' \
  'EXPECTED_STRATEGY_LANE_COUNT=25' \
  'UNCHANGED_EVIDENCE_PRESERVATION_REQUIRED=true' \
  'AFFECTED_LANE_ONLY_REBASELINE_REQUIRED=true' \
  'FULL_864_REEXECUTION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'EXECUTION_PLAN_MUTATION_ALLOWED=false' \
  'MARKET_SOURCE_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_FOUR_WAY_LINEAGE_SELECTIVE_REBASELINE_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/backend/strategy25/canonical_strategy_registry_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_FOUR_WAY_LINEAGE_SELECTIVE_REBASELINE_AUDIT_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-four-way-lineage-audit.XXXXXX)" || exit 2
mkdir -p "$TMP/tools"
if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_short_four_way_lineage_selective_rebaseline_audit.py" \
  > "$TMP/tools/r7a4d2_short_four_way_lineage_selective_rebaseline_audit.py"; then
  echo 'STATE=HOLD_SHORT_FOUR_WAY_LINEAGE_SELECTIVE_REBASELINE_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["MATERIALIZE_FAILED:tools/r7a4d2_short_four_way_lineage_selective_rebaseline_audit.py"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$TMP/tools/r7a4d2_short_four_way_lineage_selective_rebaseline_audit.py"; then
  echo 'STATE=HOLD_SHORT_FOUR_WAY_LINEAGE_SELECTIVE_REBASELINE_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TMP/tools/r7a4d2_short_four_way_lineage_selective_rebaseline_audit.py" --self-test; then
  echo 'STATE=HOLD_SHORT_FOUR_WAY_LINEAGE_SELECTIVE_REBASELINE_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["FOUR_WAY_LINEAGE_AUDIT_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4d2_short_four_way_lineage_selective_rebaseline_audit.py" \
  --root "$ROOT" \
  --target-sha "$SHA"
RC=$?

echo 'R7A4D2_SHORT_FOUR_WAY_LINEAGE_SELECTIVE_REBASELINE_AUDIT_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
