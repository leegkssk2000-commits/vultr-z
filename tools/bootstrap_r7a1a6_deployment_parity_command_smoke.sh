#!/usr/bin/env bash
set -u

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
COMMAND_TIMEOUT="${3:-90}"

if [[ -z "$SHA" ]]; then
  echo "R7A1A6_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["MISSING_SHA"]'
  exit 2
fi

TMPDIR_PATH="$(mktemp -d /tmp/r7a1a6.XXXXXXXX)"
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
  tools/r7a1a6_deployment_parity_command_smoke.py \
  tests/test_r7a1a6_deployment_parity_command_smoke.py \
  backend/contracts/ZOS_R7A1A6_DEPLOYMENT_PARITY_COMMAND_SMOKE_v1.json
do
  show_file "$path" "$TMPDIR_PATH/$path" || {
    echo "R7A1A6_BOOTSTRAP_FAILED"
    echo "BLOCKERS=[\"FETCH_FAILED:$path\"]"
    exit 2
  }
done

python3 -m py_compile "$TMPDIR_PATH/tools/r7a1a6_deployment_parity_command_smoke.py" || {
  echo "R7A1A6_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["RUNNER_COMPILE_FAILED"]'
  exit 2
}

(
  cd "$TMPDIR_PATH" || exit 2
  python3 -m pytest -q tests/test_r7a1a6_deployment_parity_command_smoke.py
) || {
  echo "R7A1A6_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  exit 2
}

python3 "$TMPDIR_PATH/tools/r7a1a6_deployment_parity_command_smoke.py" \
  --root "$ROOT" \
  --sha "$SHA" \
  --contract "$TMPDIR_PATH/backend/contracts/ZOS_R7A1A6_DEPLOYMENT_PARITY_COMMAND_SMOKE_v1.json" \
  --command-timeout "$COMMAND_TIMEOUT"
RC=$?

echo "R7A1A6_BOOTSTRAP_COMPLETE"
echo "RC=$RC"
exit "$RC"
