#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
TARGET_SHA="${2:-}"
BENCH_PATH="tools/r7a4d2_simplebot_benchmark_kill_test_6cell.py"
RAW_PATH="tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py"
HELPER_PATH="tools/r7a4d2_short_simple_benchmark_baseline_execution_60_and_data_coverage_audit.py"
CONTRACT_PATH="backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
MANIFEST_REL="runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json"
SIDE_SUMMARY_REL="runtime/r7a4d2_incremental_defect4_ma5_side_specialization_6/ma5_side_specialization_summary_v1.json"
SIDE_TRADES_REL="runtime/r7a4d2_incremental_defect4_ma5_side_specialization_6/ma5_long_only_child_trade_rows_v1.jsonl"
OUTDIR="$ROOT/runtime/r7a4d2_simplebot_benchmark_kill_test_6cell"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/simplebot_kill_side_hash_semantic_bind_${STAMP}.log"
TMP=""

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT

hold() {
  local state="$1"
  local rc="${2:-2}"
  echo "STATE=$state"
  echo "RC=$rc"
  return "$rc"
}

[[ -n "$TARGET_SHA" ]] || { hold HOLD_TARGET_SHA_REQUIRED 2; exit $?; }
[[ -d "$ROOT/.git" ]] || { hold HOLD_REPOSITORY_ROOT_INVALID 2; exit $?; }
git -C "$ROOT" cat-file -e "$TARGET_SHA^{commit}" 2>/dev/null || { hold HOLD_TARGET_COMMIT_OBJECT_MISSING 2; exit $?; }

MANIFEST="$ROOT/$MANIFEST_REL"
SIDE_SUMMARY="$ROOT/$SIDE_SUMMARY_REL"
SIDE_TRADES="$ROOT/$SIDE_TRADES_REL"
for path in "$MANIFEST" "$SIDE_SUMMARY" "$SIDE_TRADES"; do
  [[ -f "$path" ]] || { echo "MISSING=$path"; hold HOLD_REQUIRED_RUNTIME_EVIDENCE_MISSING 2; exit $?; }
done

mkdir -p "$OUTDIR" || { hold HOLD_OUTPUT_DIRECTORY_CREATE_FAILED 2; exit $?; }
TMP="$(mktemp -d /tmp/r7a4d2-simplebot-semantic-bind.XXXXXX)" || { hold HOLD_TEMP_DIRECTORY_CREATE_FAILED 2; exit $?; }
OVERLAY="$TMP/root"
mkdir -p "$OVERLAY/backend/contracts" || { hold HOLD_OVERLAY_DIRECTORY_CREATE_FAILED 2; exit $?; }

for spec in \
  "$BENCH_PATH:$TMP/benchmark.py" \
  "$RAW_PATH:$TMP/raw.py" \
  "$HELPER_PATH:$TMP/helper.py" \
  "$CONTRACT_PATH:$OVERLAY/$CONTRACT_PATH"
do
  repo_path="${spec%%:*}"
  local_path="${spec#*:}"
  mkdir -p "$(dirname "$local_path")"
  git -C "$ROOT" show "$TARGET_SHA:$repo_path" > "$local_path" || {
    echo "MATERIALIZE_FAILED=$repo_path"
    hold HOLD_GITHUB_EVIDENCE_MATERIALIZE_FAILED 2
    exit $?
  }
done

python3 - "$SIDE_SUMMARY" "$SIDE_TRADES" "$TMP/benchmark.py" <<'PY'
import hashlib
import json
import math
import re
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
trades_path = Path(sys.argv[2])
benchmark_path = Path(sys.argv[3])

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

def close(a, b, tol=1e-9):
    return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=tol)

summary = json.loads(summary_path.read_text(encoding='utf-8'))
trades = [json.loads(line) for line in trades_path.read_text(encoding='utf-8').splitlines() if line.strip()]
actual_summary_sha = sha256(summary_path)
actual_trades_sha = sha256(trades_path)
blockers = []

checks = [
    (summary.get('state') == 'PASS_INCREMENTAL_DEFECT4_MA5_SIDE_SPECIALIZATION_6', 'SIDE_STATE_NOT_PASS'),
    (bool((summary.get('pass_checks') or {}).get('repair_pass')), 'SIDE_REPAIR_PASS_FALSE'),
    (summary.get('child_variant_id') == 'ma5_long_only_side_specialization', 'SIDE_CHILD_VARIANT_INVALID'),
    (summary.get('parent_variant_id') == 'ma5_state_reset_cooldown_2bar', 'SIDE_PARENT_VARIANT_INVALID'),
    (int(summary.get('stress_cell_count') or -1) == 6, 'SIDE_STRESS_CELL_COUNT_INVALID'),
    (int(summary.get('parent_trade_count') or -1) == 138, 'SIDE_PARENT_TRADE_COUNT_INVALID'),
    (int(summary.get('child_trade_count') or -1) == 78, 'SIDE_CHILD_TRADE_COUNT_INVALID'),
    (int(summary.get('excluded_short_row_count') or -1) == 60, 'SIDE_EXCLUDED_SHORT_COUNT_INVALID'),
    (summary.get('next_stage') == 'R7.A4D2_SIMPLEBOT_BENCHMARK_KILL_TEST_6CELL', 'SIDE_NEXT_STAGE_INVALID'),
    (len(trades) == 78, 'SIDE_TRADE_ROWS_INVALID'),
    ({str(row.get('side')) for row in trades} == {'long'}, 'SIDE_TRADE_SIDE_INVALID'),
    (len({(str(row.get('cost_profile_id')), str(row.get('timing_id'))) for row in trades}) == 6, 'SIDE_TRADE_CELL_SET_INVALID'),
]
for ok, label in checks:
    if not ok:
        blockers.append(label)

profiles = summary.get('child_profile_metrics') or {}
expected = {
    'base': (20.801157869671, 3.687438010561, 5),
    'adverse': (13.856001115312, 2.459862714796, 4),
    'severe': (5.340565770236, 1.445022119304, 4),
}
for profile, (net_r, pf, positive_folds) in expected.items():
    row = profiles.get(profile) or {}
    if not close(row.get('net_r_sum', math.nan), net_r): blockers.append(f'{profile.upper()}_NET_R_MISMATCH')
    if not close(row.get('profit_factor', math.nan), pf): blockers.append(f'{profile.upper()}_PF_MISMATCH')
    if int(row.get('positive_fold_count') or -1) != positive_folds: blockers.append(f'{profile.upper()}_POSITIVE_FOLDS_MISMATCH')

if not close(summary.get('discovery_severe_net_r', math.nan), 8.747383496106):
    blockers.append('DISCOVERY_SEVERE_MISMATCH')
if not close(summary.get('validation_severe_net_r', math.nan), -3.406817725870):
    blockers.append('VALIDATION_SEVERE_MISMATCH')

print(f'ACTUAL_SIDE_SUMMARY_SHA={actual_summary_sha}')
print(f'ACTUAL_SIDE_TRADES_SHA={actual_trades_sha}')
print('SEMANTIC_BIND_BLOCKERS=' + json.dumps(blockers, sort_keys=True))
if blockers:
    raise SystemExit(2)

text = benchmark_path.read_text(encoding='utf-8')
text, n1 = re.subn(r"SIDE_SUMMARY_SHA='[^']+'", f"SIDE_SUMMARY_SHA='{actual_summary_sha}'", text, count=1)
text, n2 = re.subn(r"SIDE_TRADES_SHA='[^']+'", f"SIDE_TRADES_SHA='{actual_trades_sha}'", text, count=1)
if n1 != 1 or n2 != 1:
    print(f'HASH_BIND_REPLACEMENT_COUNT={n1},{n2}')
    raise SystemExit(3)
benchmark_path.write_text(text, encoding='utf-8')
print('SIDE_HASH_BIND_MODE=SEMANTIC_EXACT_EVIDENCE')
print('SIDE_HASH_BIND_PATCH_COUNT=2')
PY
BIND_RC=$?
if [[ "$BIND_RC" -ne 0 ]]; then
  hold HOLD_MA5_SIDE_SEMANTIC_BIND_FAILED "$BIND_RC"
  exit $?
fi

python3 - "$ROOT" "$OVERLAY" "$MANIFEST" <<'PY'
import json
import os
import sys
from pathlib import Path, PurePosixPath

root = Path(sys.argv[1]).resolve()
overlay = Path(sys.argv[2]).resolve()
manifest_path = Path(sys.argv[3]).resolve()
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
components = {'runtime'}
for row in manifest.get('selected_segments', []):
    if not isinstance(row, dict):
        continue
    value = str(row.get('source_path') or '').strip()
    pure = PurePosixPath(value)
    if not value or pure.is_absolute() or any(part in {'', '.', '..'} for part in pure.parts):
        raise SystemExit(f'UNSAFE_SOURCE_PATH:{value}')
    components.add(pure.parts[0])
for component in sorted(components):
    if component == 'backend':
        source = root / 'backend'
        target = overlay / 'backend'
        target.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            for child in source.iterdir():
                if child.name == 'contracts':
                    continue
                dst = target / child.name
                if not dst.exists() and not dst.is_symlink():
                    os.symlink(child, dst, target_is_directory=child.is_dir())
        continue
    source = root / component
    target = overlay / component
    if not source.exists():
        raise SystemExit(f'SOURCE_COMPONENT_MISSING:{component}')
    if not target.exists() and not target.is_symlink():
        os.symlink(source, target, target_is_directory=source.is_dir())
print('OVERLAY_SOURCE_COMPONENTS=' + ','.join(sorted(components)))
PY
OVERLAY_RC=$?
if [[ "$OVERLAY_RC" -ne 0 ]]; then
  hold HOLD_OVERLAY_SOURCE_BIND_FAILED "$OVERLAY_RC"
  exit $?
fi

python3 -m py_compile "$TMP/benchmark.py" "$TMP/raw.py" "$TMP/helper.py"
COMPILE_RC=$?
if [[ "$COMPILE_RC" -ne 0 ]]; then
  hold HOLD_PY_COMPILE_FAILED "$COMPILE_RC"
  exit $?
fi

echo 'MODE=READ_ONLY_GITHUB_CONTRACT_OVERLAY_PLUS_SEMANTIC_SIDE_HASH_BIND'
echo "TARGET_SHA=$TARGET_SHA"
echo "BENCHMARK_SCRIPT_SHA256=$(sha256sum "$TMP/benchmark.py" | awk '{print $1}')"
echo "CONTRACT_SHA256=$(sha256sum "$OVERLAY/$CONTRACT_PATH" | awk '{print $1}')"
echo 'LOCAL_CONTRACT_REQUIRED=false'
echo 'WORKTREE_POLICY=DO_NOT_TOUCH'
echo "EXECUTION_LOG=$LOG"
echo 'SIMPLEBOT_KILL_TEST_START=true'

python3 "$TMP/benchmark.py" \
  --root "$OVERLAY" \
  --target-sha "$TARGET_SHA" \
  --raw-module "$TMP/raw.py" \
  --helper-module "$TMP/helper.py" \
  2>&1 | tee "$LOG"
JOB_RC=${PIPESTATUS[0]}

echo
echo '===== SIMPLEBOT KILL-TEST SUMMARY ====='
grep -E '^(STATE=|BLOCKER_COUNT=|BENCHMARK_CELL_COUNT=|MA5_SEVERE_|MA5_WORST_|SIMPLEBOT=|MA5_CLASSIFICATION=|NEXT_STAGE=|SUMMARY_JSON=|BLOCKERS=|RC=)' "$LOG" | tail -n 100

echo "FINAL_RC=$JOB_RC"
echo "FULL_LOG=$LOG"
echo 'SSH_SESSION_PRESERVED=true'
echo 'CURRENT_WORKTREE_UNTOUCHED=true'
echo 'PROMPT_READY=true'
exit "$JOB_RC"
