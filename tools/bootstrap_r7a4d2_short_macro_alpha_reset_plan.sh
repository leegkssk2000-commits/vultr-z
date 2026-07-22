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
  'R7A4D2_SHORT_MACRO_ALPHA_RESET_PLAN_START' \
  'MODE=READ_ONLY_REVOKE_FALSE_S_GRADE_FREEZE_14_RESET_11_TO_FOUR_FACTOR_ENGINES_AND_FIVE_SIMPLE_BENCHMARKS' \
  'EXPECTED_CANONICAL_STRATEGY_COUNT=25' \
  'EXPECTED_KEPT_STRATEGY_COUNT=14' \
  'EXPECTED_RESET_STRATEGY_COUNT=11' \
  'EXPECTED_FACTOR_ENGINE_COUNT=4' \
  'EXPECTED_BENCHMARK_COUNT=5' \
  'EXPECTED_BENCHMARK_LANE_COUNT=10' \
  'EXPECTED_BENCHMARK_CELL_TARGET=60' \
  'DISCOVERY_S_GRADE_LABEL_ALLOWED=false' \
  'MICROSTRUCTURE_SCALP_WITH_OHLCV_ONLY_ALLOWED=false' \
  'PURGED_WALK_FORWARD_REQUIRED=true' \
  'PBO_REQUIRED=true' \
  'DEFLATED_SHARPE_REQUIRED=true' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_SHORT_MACRO_ALPHA_RESET_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

for required in \
  "$ROOT/backend/strategy25/canonical_strategy_registry_v1.json" \
  "$ROOT/runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json" \
  "$ROOT/runtime/r7a4d2_short_native_family_architecture_discovery_execution_132/architecture_discovery_lock_v1.json" \
  "$ROOT/runtime/r7a4d2_short_native_architecture_disjoint_validation_and_near_miss_rescue_plan/strict_validation_and_rescue_plan_v1.json"
do
  if [[ ! -f "$required" ]]; then
    echo 'STATE=HOLD_SHORT_MACRO_ALPHA_RESET_PLAN_INPUT'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["REQUIRED_EVIDENCE_MISSING:%s"]\n' "$required"
    echo 'RC=2'
    exit 2
  fi
done

TMP="$(mktemp -d /tmp/r7a4d2-short-macro-alpha-reset.XXXXXX)" || exit 2
mkdir -p "$TMP/tools"

TARGET="$TMP/tools/r7a4d2_short_macro_alpha_reset_plan.py"
if ! git -C "$ROOT" show "$SHA:tools/r7a4d2_short_macro_alpha_reset_plan.py" > "$TARGET"; then
  echo 'STATE=HOLD_SHORT_MACRO_ALPHA_RESET_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["MATERIALIZE_FAILED:tools/r7a4d2_short_macro_alpha_reset_plan.py"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 - "$TARGET" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = 'int(validation.get("validated_strict_survivor_count") or -1)'
new = 'int(validation.get("validated_strict_survivor_count", -1))'
count = text.count(old)
if count != 1:
    raise SystemExit(f"ZERO_SURVIVOR_GUARD_PATCH_TARGET_INVALID:{count}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("STATE=PASS_SHORT_MACRO_ALPHA_RESET_ZERO_SURVIVOR_GUARD_PATCH")
print("ZERO_VALIDATED_SURVIVOR_PRESERVED=true")
print("PATCH_SCOPE=temporary_execution_copy_only")
print("RC=0")
PY
then
  echo 'STATE=HOLD_SHORT_MACRO_ALPHA_RESET_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["ZERO_SURVIVOR_GUARD_PATCH_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$TARGET"; then
  echo 'STATE=HOLD_SHORT_MACRO_ALPHA_RESET_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 "$TARGET" --self-test; then
  echo 'STATE=HOLD_SHORT_MACRO_ALPHA_RESET_PLAN_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["MACRO_ALPHA_RESET_PLAN_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 "$TARGET" \
  --root "$ROOT" \
  --target-sha "$SHA"
RC=$?

echo 'R7A4D2_SHORT_MACRO_ALPHA_RESET_PLAN_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
