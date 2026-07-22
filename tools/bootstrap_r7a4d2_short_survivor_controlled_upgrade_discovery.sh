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
  'R7A4D2_SHORT_SURVIVOR_CONTROLLED_UPGRADE_DISCOVERY_START' \
  'MODE=READ_ONLY_TWO_SURVIVOR_BASELINE_PLUS_THREE_SINGLE_AXIS_ARMS_DISCOVERY' \
  'SURVIVOR_LANE_COUNT=2' \
  'EXPECTED_SURVIVOR_LANES=strategy:vwap_revert:5m,strategy:grid_rebalance:1m' \
  'ARM_COUNT_PER_LANE=4' \
  'BASELINE_FROZEN=true' \
  'SINGLE_AXIS_ARM_REQUIRED=true' \
  'DISCOVERY_FOLDS_ONLY=true' \
  'COST_PROFILE_COUNT=3' \
  'PERTURBATION_COUNT=2' \
  'STOP_FIRST_COLLISION_REQUIRED=true' \
  'OVERLAPPING_POSITION_ALLOWED=false' \
  'FUTURE_VALIDATION_SELECTION_ALLOWED=false' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'MARKET_SOURCE_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_SURVIVOR_CONTROLLED_UPGRADE_DISCOVERY_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_mutation_and_lane_economic_diagnose/diagnose_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution_plan/execution_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/aggregate_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/proof_v1.json" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/scan_results_v1.jsonl" \
  "$ROOT/runtime/r7a4d2_short_raw_geometry_and_simple_benchmark_execution/signal_geometry_v1.jsonl" \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_SURVIVOR_CONTROLLED_UPGRADE_DISCOVERY_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-survivor-upgrade.XXXXXX)" || exit 2
for path in \
  tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py \
  tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_SURVIVOR_CONTROLLED_UPGRADE_DISCOVERY_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 - "$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
source = path.read_text(encoding="utf-8")
old = '''    protected_paths = [Path(str(value)) for value in contract.get("protected_paths", [])]
    before = snapshot(canonical_paths + protected_paths)

    source_sha_by_path = {
        str(row.get("source_path")): str(row.get("source_sha256") or "")
        for row in manifest.get("selected_segments", []) if isinstance(row, dict)
    }
'''
new = '''    source_sha_by_path = {
        str(row.get("source_path")): str(row.get("source_sha256") or "")
        for row in manifest.get("selected_segments", []) if isinstance(row, dict)
    }
    for source_path in sorted({str(row["source_path"]) for row in segments.values()}):
        canonical_paths.append(root / safe_repo_path(source_path))
    protected_paths = [Path(str(value)) for value in contract.get("protected_paths", [])]
    before = snapshot(canonical_paths + protected_paths)
'''
count = source.count(old)
if count != 1:
    raise SystemExit(f"MARKET_SOURCE_SNAPSHOT_PATCH_ANCHOR_INVALID:{count}")
path.write_text(source.replace(old, new, 1), encoding="utf-8")
print("STATE=PASS_SURVIVOR_UPGRADE_MARKET_SOURCE_SNAPSHOT_PATCH")
print("MARKET_SOURCE_MUTATION_GUARDED=true")
print("PATCH_SCOPE=temporary_execution_copy_only")
PY
then
  echo 'STATE=HOLD_SHORT_SURVIVOR_CONTROLLED_UPGRADE_DISCOVERY_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["MARKET_SOURCE_SNAPSHOT_PATCH_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile \
  "$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py" \
  "$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py"; then
  echo 'STATE=HOLD_SHORT_SURVIVOR_CONTROLLED_UPGRADE_DISCOVERY_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py" --self-test; then
  echo 'STATE=HOLD_SHORT_SURVIVOR_CONTROLLED_UPGRADE_DISCOVERY_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["CONTROLLED_UPGRADE_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --raw-module "$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py" \
  --a4d-contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?

echo 'R7A4D2_SHORT_SURVIVOR_CONTROLLED_UPGRADE_DISCOVERY_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
