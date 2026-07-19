#!/usr/bin/env bash
set -u

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
BIND_TIMEOUT="${3:-120}"

if [[ -z "$SHA" ]]; then
  echo "R7A1A4C2_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["MISSING_SHA"]'
  exit 2
fi

TMPDIR_PATH="$(mktemp -d /tmp/r7a1a4c2.XXXXXXXX)"
cleanup() {
  rm -rf "$TMPDIR_PATH"
}
trap cleanup EXIT

show_file() {
  local repo_path="$1"
  local output_path="$2"
  git -C "$ROOT" -c safe.directory="$ROOT" show "$SHA:$repo_path" > "$output_path"
}

mkdir -p "$TMPDIR_PATH/tools" "$TMPDIR_PATH/tests" "$TMPDIR_PATH/backend/contracts"

for path in \
  tools/r7a1a4c_environment_binding_canary.py \
  tools/r7a1a4c2_environment_binding_canary.py \
  tests/test_r7a1a4c_environment_binding_canary.py \
  tests/test_r7a1a4c2_environment_binding_canary.py \
  backend/contracts/ZOS_R7A1A4C2_VOLATILE_VIEW_GUARD_SCOPE_v1.json
do
  show_file "$path" "$TMPDIR_PATH/$path" || {
    echo "R7A1A4C2_BOOTSTRAP_FAILED"
    echo "BLOCKERS=[\"FETCH_FAILED:$path\"]"
    exit 2
  }
done

python3 -m py_compile \
  "$TMPDIR_PATH/tools/r7a1a4c_environment_binding_canary.py" \
  "$TMPDIR_PATH/tools/r7a1a4c2_environment_binding_canary.py" || {
  echo "R7A1A4C2_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["RUNNER_COMPILE_FAILED"]'
  exit 2
}

(
  cd "$TMPDIR_PATH" || exit 2
  python3 -m pytest -q \
    tests/test_r7a1a4c_environment_binding_canary.py \
    tests/test_r7a1a4c2_environment_binding_canary.py
) || {
  echo "R7A1A4C2_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  exit 2
}

python3 "$TMPDIR_PATH/tools/r7a1a4c2_environment_binding_canary.py" \
  --root "$ROOT" \
  --sha "$SHA" \
  --base-runner "$TMPDIR_PATH/tools/r7a1a4c_environment_binding_canary.py" \
  --bind-timeout "$BIND_TIMEOUT"
RC=$?

echo "R7A1A4C2_BOOTSTRAP_COMPLETE"
echo "RC=$RC"
exit "$RC"
