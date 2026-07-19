#!/usr/bin/env bash
set -u

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
SMOKE_TIMEOUT="${3:-90}"

if [[ -z "$SHA" ]]; then
  echo "R7A1A5A_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["MISSING_SHA"]'
  exit 2
fi

TMPDIR_PATH="$(mktemp -d /tmp/r7a1a5a.XXXXXXXX)"
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
  tools/r7a1a5_systemd_source_cutover_canary.py \
  tools/r7a1a5a_runtime_error_classification.py \
  tests/test_r7a1a5_systemd_source_cutover_canary.py \
  tests/test_r7a1a5a_runtime_error_classification.py \
  backend/contracts/ZOS_R7A1A5_SYSTEMD_SOURCE_CUTOVER_CANARY_v1.json \
  backend/contracts/ZOS_R7A1A5A_RUNTIME_ERROR_CLASSIFICATION_v1.json
do
  show_file "$path" "$TMPDIR_PATH/$path" || {
    echo "R7A1A5A_BOOTSTRAP_FAILED"
    echo "BLOCKERS=[\"FETCH_FAILED:$path\"]"
    exit 2
  }
done

python3 -m py_compile \
  "$TMPDIR_PATH/tools/r7a1a5_systemd_source_cutover_canary.py" \
  "$TMPDIR_PATH/tools/r7a1a5a_runtime_error_classification.py" || {
  echo "R7A1A5A_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["RUNNER_COMPILE_FAILED"]'
  exit 2
}

(
  cd "$TMPDIR_PATH" || exit 2
  python3 -m pytest -q \
    tests/test_r7a1a5_systemd_source_cutover_canary.py \
    tests/test_r7a1a5a_runtime_error_classification.py
) || {
  echo "R7A1A5A_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  exit 2
}

python3 "$TMPDIR_PATH/tools/r7a1a5a_runtime_error_classification.py" \
  --root "$ROOT" \
  --sha "$SHA" \
  --base-runner "$TMPDIR_PATH/tools/r7a1a5_systemd_source_cutover_canary.py" \
  --base-contract "$TMPDIR_PATH/backend/contracts/ZOS_R7A1A5_SYSTEMD_SOURCE_CUTOVER_CANARY_v1.json" \
  --classification-contract "$TMPDIR_PATH/backend/contracts/ZOS_R7A1A5A_RUNTIME_ERROR_CLASSIFICATION_v1.json" \
  --smoke-timeout "$SMOKE_TIMEOUT"
RC=$?

echo "R7A1A5A_BOOTSTRAP_COMPLETE"
echo "RC=$RC"
exit "$RC"
