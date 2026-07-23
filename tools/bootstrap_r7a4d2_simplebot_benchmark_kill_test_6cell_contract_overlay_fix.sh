#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
TARGET_SHA="${2:-}"
BRANCH="r7a4d-historical-simulation-3600-v1"
BENCH_PATH="tools/r7a4d2_simplebot_benchmark_kill_test_6cell.py"
RAW_PATH="tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py"
HELPER_PATH="tools/r7a4d2_short_simple_benchmark_baseline_execution_60_and_data_coverage_audit.py"
CONTRACT_PATH="backend/contracts/ZOS_R7A4D_HISTORICAL_SIMULATION_3600_v1.json"
MANIFEST_REL="runtime/r7a4c_historical_simulation_input_lineage/selected_input_manifest_v1.json"
OUTDIR="$ROOT/runtime/r7a4d2_simplebot_benchmark_kill_test_6cell"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUTDIR/simplebot_kill_contract_overlay_${STAMP}.log"
TMP=""

cleanup() {
  if [[ -n "$TMP" && -d "$TMP" ]]; then
    rm -rf "$TMP"
  fi
}
trap cleanup EXIT

hold() {
  local state="$1"
  local rc="${2:-2}"
  echo "STATE=$state"
  echo "RC=$rc"
  return "$rc"
}

if [[ -z "$TARGET_SHA" ]]; then
  hold "HOLD_TARGET_SHA_REQUIRED" 2
  exit $?
fi

if [[ ! -d "$ROOT/.git" ]]; then
  hold "HOLD_REPOSITORY_ROOT_INVALID" 2
  exit $?
fi

if ! git -C "$ROOT" cat-file -e "$TARGET_SHA^{commit}" 2>/dev/null; then
  hold "HOLD_TARGET_COMMIT_OBJECT_MISSING" 2
  exit $?
fi

MANIFEST="$ROOT/$MANIFEST_REL"
if [[ ! -f "$MANIFEST" ]]; then
  hold "HOLD_SELECTED_MANIFEST_MISSING" 2
  exit $?
fi

mkdir -p "$OUTDIR" || {
  hold "HOLD_OUTPUT_DIRECTORY_CREATE_FAILED" 2
  exit $?
}

TMP="$(mktemp -d /tmp/r7a4d2-simplebot-overlay.XXXXXX)" || {
  hold "HOLD_TEMP_DIRECTORY_CREATE_FAILED" 2
  exit $?
}
OVERLAY="$TMP/root"
mkdir -p "$OVERLAY/backend/contracts" || {
  hold "HOLD_OVERLAY_DIRECTORY_CREATE_FAILED" 2
  exit $?
}

for spec in \
  "$BENCH_PATH:$TMP/benchmark.py" \
  "$RAW_PATH:$TMP/raw.py" \
  "$HELPER_PATH:$TMP/helper.py" \
  "$CONTRACT_PATH:$OVERLAY/$CONTRACT_PATH"
do
  repo_path="${spec%%:*}"
  local_path="${spec#*:}"
  mkdir -p "$(dirname "$local_path")"
  if ! git -C "$ROOT" show "$TARGET_SHA:$repo_path" > "$local_path"; then
    echo "MATERIALIZE_FAILED=$repo_path"
    hold "HOLD_GITHUB_EVIDENCE_MATERIALIZE_FAILED" 2
    exit $?
  fi
done

python3 - "$ROOT" "$OVERLAY" "$MANIFEST" <<'PY'
import json
import os
import sys
from pathlib import Path, PurePosixPath

root = Path(sys.argv[1]).resolve()
overlay = Path(sys.argv[2]).resolve()
manifest_path = Path(sys.argv[3]).resolve()
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

components = {"runtime"}
for row in manifest.get("selected_segments", []):
    if not isinstance(row, dict):
        continue
    value = str(row.get("source_path") or "").strip()
    pure = PurePosixPath(value)
    if not value or pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise SystemExit(f"UNSAFE_SOURCE_PATH:{value}")
    components.add(pure.parts[0])

for component in sorted(components):
    if component == "backend":
        backend_source = root / "backend"
        backend_target = overlay / "backend"
        backend_target.mkdir(parents=True, exist_ok=True)
        if backend_source.is_dir():
            for child in backend_source.iterdir():
                if child.name == "contracts":
                    continue
                target = backend_target / child.name
                if not target.exists() and not target.is_symlink():
                    os.symlink(child, target, target_is_directory=child.is_dir())
        continue
    source = root / component
    target = overlay / component
    if not source.exists():
        raise SystemExit(f"SOURCE_COMPONENT_MISSING:{component}")
    if not target.exists() and not target.is_symlink():
        os.symlink(source, target, target_is_directory=source.is_dir())

print("OVERLAY_SOURCE_COMPONENTS=" + ",".join(sorted(components)))
PY
OVERLAY_RC=$?
if [[ "$OVERLAY_RC" -ne 0 ]]; then
  hold "HOLD_OVERLAY_SOURCE_BIND_FAILED" "$OVERLAY_RC"
  exit $?
fi

python3 -m py_compile "$TMP/benchmark.py" "$TMP/raw.py" "$TMP/helper.py"
COMPILE_RC=$?
if [[ "$COMPILE_RC" -ne 0 ]]; then
  hold "HOLD_PY_COMPILE_FAILED" "$COMPILE_RC"
  exit $?
fi

CONTRACT_SHA="$(sha256sum "$OVERLAY/$CONTRACT_PATH" | awk '{print $1}')"
BENCH_SHA="$(sha256sum "$TMP/benchmark.py" | awk '{print $1}')"

echo "MODE=READ_ONLY_GITHUB_CONTRACT_OVERLAY"
echo "TARGET_SHA=$TARGET_SHA"
echo "BENCHMARK_SCRIPT_SHA256=$BENCH_SHA"
echo "CONTRACT_SHA256=$CONTRACT_SHA"
echo "LOCAL_CONTRACT_REQUIRED=false"
echo "WORKTREE_POLICY=DO_NOT_TOUCH"
echo "EXECUTION_LOG=$LOG"
echo "SIMPLEBOT_KILL_TEST_START=true"

python3 "$TMP/benchmark.py" \
  --root "$OVERLAY" \
  --target-sha "$TARGET_SHA" \
  --raw-module "$TMP/raw.py" \
  --helper-module "$TMP/helper.py" \
  2>&1 | tee "$LOG"
JOB_RC=${PIPESTATUS[0]}

echo
echo "===== SIMPLEBOT KILL-TEST SUMMARY ====="
grep -E '^(STATE=|BLOCKER_COUNT=|BENCHMARK_CELL_COUNT=|MA5_SEVERE_|MA5_WORST_|SIMPLEBOT=|MA5_CLASSIFICATION=|NEXT_STAGE=|SUMMARY_JSON=|BLOCKERS=|RC=)' "$LOG" | tail -n 100

echo "FINAL_RC=$JOB_RC"
echo "FULL_LOG=$LOG"
echo "SSH_SESSION_PRESERVED=true"
echo "CURRENT_WORKTREE_UNTOUCHED=true"
echo "PROMPT_READY=true"
exit "$JOB_RC"
