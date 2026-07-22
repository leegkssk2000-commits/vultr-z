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
  'R7A4D2_SHORT_SELECTIVE_VWAP_REPAIR_EXECUTION_54_AND_REMAINING_UPLIFT_AUDIT_START' \
  'MODE=READ_ONLY_VWAP_NATIVE_REFERENCE_PLUS_NINE_REPAIR_ARMS_AND_REMAINING_STRATEGY_UPLIFT_AUDIT' \
  'EXPECTED_VWAP_LANE_COUNT=3' \
  'EXPECTED_VWAP_REPAIR_ARM_COUNT=9' \
  'EXPECTED_VWAP_REPAIR_CELL_COUNT=54' \
  'EXPECTED_VWAP_NATIVE_REFERENCE_CELL_COUNT=18' \
  'EXPECTED_REMAINING_STRATEGY_COUNT=10' \
  'DISCOVERY_SEGMENT_COUNT=12' \
  'COST_PROFILE_COUNT=3' \
  'PERTURBATION_COUNT=2' \
  'SEVERE_CELL_ECONOMIC_PASS_REQUIRED=true' \
  'MINIMUM_DISCOVERY_TRADE_COUNT=8' \
  'MINIMUM_POSITIVE_STRESS_CELL_COUNT=4' \
  'MAX_DRAWDOWN_NONWORSENING_VS_NATIVE_REQUIRED=true' \
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
  echo 'STATE=HOLD_SHORT_SELECTIVE_VWAP_REPAIR_EXECUTION_54_AND_REMAINING_UPLIFT_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/runtime/r7a4d2_short_selective_vwap_economic_diagnose_and_repair_plan_rebuild/repair_plan_v1.json" \
  "$ROOT/runtime/r7a4d2_short_selective_raw_geometry_preservation_verification_repair/verified_effective_execution_plan_v3.json" \
  "$ROOT/runtime/r7a4d2_short_selective_raw_geometry_rebaseline_execution/merged_signal_geometry_v2.jsonl" \
  "$ROOT/runtime/r7a4d2_short_selective_raw_geometry_rebaseline_execution/merged_scan_results_v2.jsonl" \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json" \
  "$ROOT/runtime/r7a4d2_short_second_order_repair_causal_audit/causal_audit_v1.json" \
  "$ROOT/runtime/r7a4d2_short_all_lane_architecture_repair_execution/repair_arm_cell_results_v1.jsonl"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_SELECTIVE_VWAP_REPAIR_EXECUTION_54_AND_REMAINING_UPLIFT_AUDIT_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-vwap-economics.XXXXXX)" || exit 2
for path in \
  tools/r7a4d2_short_selective_vwap_repair_execution_54_and_remaining_uplift_audit.py \
  tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py \
  tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py \
  backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD_SHORT_SELECTIVE_VWAP_REPAIR_EXECUTION_54_AND_REMAINING_UPLIFT_AUDIT_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'RC=2'
    exit 2
  fi
done

PATCH_TARGET="$TMP/tools/r7a4d2_short_selective_vwap_repair_execution_54_and_remaining_uplift_audit.py"
if ! python3 - "$PATCH_TARGET" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
replacements = {
    'float(finite(severe.get("max_drawdown_pct"), 1e100) or 1e100)': 'float(finite(severe.get("max_drawdown_pct"), 1e100))',
    'float(finite(native_severe.get("max_drawdown_pct"), 1e100) or 1e100)': 'float(finite(native_severe.get("max_drawdown_pct"), 1e100))',
    'float(finite(row["severe_metrics"].get("expectancy_r"), -1e100) or -1e100)': 'float(finite(row["severe_metrics"].get("expectancy_r"), -1e100))',
    'float(finite(row["severe_metrics"].get("profit_factor"), -1e100) or -1e100)': 'float(finite(row["severe_metrics"].get("profit_factor"), -1e100))',
    'float(finite(row["severe_metrics"].get("net_pnl_sum_pct"), -1e100) or -1e100)': 'float(finite(row["severe_metrics"].get("net_pnl_sum_pct"), -1e100))',
    'float(finite(row["severe_metrics"].get("max_drawdown_pct"), 1e100) or 1e100)': 'float(finite(row["severe_metrics"].get("max_drawdown_pct"), 1e100))',
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"PATCH_PATTERN_MISSING:{old}")
    text = text.replace(old, new)

needle = '''                    "fold": int(segment.get("fold") or 0),
                    "signal_bar_index": int(signal["signal_bar_index"]),
'''
replacement = '''                    "fold": int(segment.get("fold") or 0),
                    "symbol": str(frame.iloc[int(signal["signal_bar_index"])].get("symbol") or segment.get("symbol") or ""),
                    "signal_bar_index": int(signal["signal_bar_index"]),
'''
count = text.count(needle)
if count != 1:
    raise SystemExit(f"SYMBOL_PROVENANCE_PATCH_TARGET_COUNT_INVALID:{count}")
text = text.replace(needle, replacement, 1)
path.write_text(text, encoding="utf-8")
print("STATE=PASS_SHORT_VWAP_RUNTIME_GUARD_PATCH")
print("ZERO_DRAWDOWN_GUARD_PATCHED=true")
print("SYMBOL_FIELD_BOUND=true")
print("PATCH_SCOPE=temporary_execution_copy_only")
print("RC=0")
PY
then
  echo 'STATE=HOLD_SHORT_SELECTIVE_VWAP_REPAIR_EXECUTION_54_AND_REMAINING_UPLIFT_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["VWAP_RUNTIME_GUARD_PATCH_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! grep -q '"symbol": str(frame.iloc\[int(signal\["signal_bar_index"\])\].get("symbol")' "$PATCH_TARGET"; then
  echo 'STATE=HOLD_SHORT_SELECTIVE_VWAP_REPAIR_EXECUTION_54_AND_REMAINING_UPLIFT_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["VWAP_SYMBOL_PROVENANCE_PATCH_VERIFY_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile \
  "$PATCH_TARGET" \
  "$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py" \
  "$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py"
then
  echo 'STATE=HOLD_SHORT_SELECTIVE_VWAP_REPAIR_EXECUTION_54_AND_REMAINING_UPLIFT_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$PATCH_TARGET" --self-test; then
  echo 'STATE=HOLD_SHORT_SELECTIVE_VWAP_REPAIR_EXECUTION_54_AND_REMAINING_UPLIFT_AUDIT_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["VWAP_ECONOMIC_EXECUTION_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$PATCH_TARGET" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --raw-module "$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py" \
  --helper-module "$TMP/tools/r7a4d2_short_survivor_controlled_upgrade_discovery.py" \
  --a4d-contract "$TMP/backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
RC=$?

echo 'R7A4D2_SHORT_SELECTIVE_VWAP_REPAIR_EXECUTION_54_AND_REMAINING_UPLIFT_AUDIT_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
