#!/usr/bin/env bash
set -u

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
TRACE_SECONDS="${3:-120}"
VERIFY_SECONDS="${4:-90}"

if [[ -z "$SHA" ]]; then
  echo "R7A1A6C3_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["MISSING_SHA"]'
  exit 2
fi

TMPDIR_PATH="$(mktemp -d /tmp/r7a1a6c3.XXXXXXXX)"
cleanup() {
  rm -rf "$TMPDIR_PATH"
}
trap cleanup EXIT

show_file() {
  local repo_path="$1"
  local output_path="$2"
  mkdir -p "$(dirname "$output_path")"
  git -C "$ROOT" -c safe.directory="$ROOT" show "$SHA:$repo_path" > "$output_path"
}

for path in \
  tools/r7a1a6c3_overwriter_eradication.py \
  tools/r7a1a6c3_runtime_shim.py \
  tools/r7a1a6c_zero_epoch_surface_repair.py \
  tests/test_r7a1a6c3_runtime_shim.py \
  backend/contracts/ZOS_R7A1A6C3_OVERWRITER_ERADICATION_v1.json \
  backend/contracts/ZOS_R7A1A6C_ZERO_EPOCH_SURFACE_ROUTER_REPAIR_v1.json
do
  show_file "$path" "$TMPDIR_PATH/$path" || {
    echo "R7A1A6C3_BOOTSTRAP_FAILED"
    echo "BLOCKERS=[\"FETCH_FAILED:$path\"]"
    exit 2
  }
done

python3 -m py_compile \
  "$TMPDIR_PATH/tools/r7a1a6c3_overwriter_eradication.py" \
  "$TMPDIR_PATH/tools/r7a1a6c3_runtime_shim.py" \
  "$TMPDIR_PATH/tools/r7a1a6c_zero_epoch_surface_repair.py" || {
  echo "R7A1A6C3_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["RUNNER_COMPILE_FAILED"]'
  exit 2
}

(
  cd "$TMPDIR_PATH" || exit 2
  python3 -m pytest -q tests/test_r7a1a6c3_runtime_shim.py
) || {
  echo "R7A1A6C3_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  exit 2
}

echo "R7A1A6C3_START"
echo "MODE=TRACE_ACTUAL_WRITER_QUARANTINE_REPAIR_VERIFY"
echo "NO_TELEGRAM_COMMAND_REQUIRED=true"
echo "TRACE_SECONDS=$TRACE_SECONDS"
echo "VERIFY_SECONDS=$VERIFY_SECONDS"

python3 "$TMPDIR_PATH/tools/r7a1a6c3_runtime_shim.py" \
  --base "$TMPDIR_PATH/tools/r7a1a6c3_overwriter_eradication.py" \
  --repair-runner "$TMPDIR_PATH/tools/r7a1a6c_zero_epoch_surface_repair.py" \
  --root "$ROOT" \
  --contract "$TMPDIR_PATH/backend/contracts/ZOS_R7A1A6C3_OVERWRITER_ERADICATION_v1.json" \
  --repair-contract "$TMPDIR_PATH/backend/contracts/ZOS_R7A1A6C_ZERO_EPOCH_SURFACE_ROUTER_REPAIR_v1.json" \
  --trace-seconds "$TRACE_SECONDS" \
  --verify-seconds "$VERIFY_SECONDS"
RC=$?

echo "R7A1A6C3_BOOTSTRAP_COMPLETE"
echo "RC=$RC"
exit "$RC"
