#!/usr/bin/env bash
set -u

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
BIND_TIMEOUT="${3:-120}"

if [[ -z "$SHA" ]]; then
  echo "R7A1A4C_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["MISSING_SHA"]'
  exit 2
fi

TMPDIR_PATH="$(mktemp -d /tmp/r7a1a4c.XXXXXXXX)"
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

show_file "tools/r7a1a4c_environment_binding_canary.py" "$TMPDIR_PATH/tools/r7a1a4c_environment_binding_canary.py" || {
  echo "R7A1A4C_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["RUNNER_FETCH_FAILED"]'
  exit 2
}
show_file "tests/test_r7a1a4c_environment_binding_canary.py" "$TMPDIR_PATH/tests/test_r7a1a4c_environment_binding_canary.py" || {
  echo "R7A1A4C_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["TEST_FETCH_FAILED"]'
  exit 2
}
show_file "backend/contracts/ZOS_R7A1A4C_ENVIRONMENT_BINDING_CANARY_v1.json" "$TMPDIR_PATH/backend/contracts/ZOS_R7A1A4C_ENVIRONMENT_BINDING_CANARY_v1.json" || {
  echo "R7A1A4C_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["CONTRACT_FETCH_FAILED"]'
  exit 2
}

python3 -m py_compile "$TMPDIR_PATH/tools/r7a1a4c_environment_binding_canary.py" || {
  echo "R7A1A4C_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["RUNNER_COMPILE_FAILED"]'
  exit 2
}

(
  cd "$TMPDIR_PATH" || exit 2
  python3 -m pytest -q tests/test_r7a1a4c_environment_binding_canary.py
) || {
  echo "R7A1A4C_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  exit 2
}

python3 "$TMPDIR_PATH/tools/r7a1a4c_environment_binding_canary.py" \
  --root "$ROOT" \
  --sha "$SHA" \
  --bind-timeout "$BIND_TIMEOUT"
RC=$?

echo "R7A1A4C_BOOTSTRAP_COMPLETE"
echo "RC=$RC"
exit "$RC"
