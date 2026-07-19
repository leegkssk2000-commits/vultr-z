#!/usr/bin/env bash
set -u

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
SMOKE_TIMEOUT="${3:-120}"

if [[ -z "$SHA" ]]; then
  echo "R7A1A5_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["MISSING_SHA"]'
  exit 2
fi

TMPDIR_PATH="$(mktemp -d /tmp/r7a1a5.XXXXXXXX)"
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
  tests/test_r7a1a5_systemd_source_cutover_canary.py \
  backend/contracts/ZOS_R7A1A5_SYSTEMD_SOURCE_CUTOVER_CANARY_v1.json \
  services/telegram/zel_q4r3_telegram_pos_adapter_v2.py
do
  show_file "$path" "$TMPDIR_PATH/$path" || {
    echo "R7A1A5_BOOTSTRAP_FAILED"
    echo "BLOCKERS=[\"FETCH_FAILED:$path\"]"
    exit 2
  }
done

python3 -m py_compile \
  "$TMPDIR_PATH/tools/r7a1a5_systemd_source_cutover_canary.py" \
  "$TMPDIR_PATH/services/telegram/zel_q4r3_telegram_pos_adapter_v2.py" || {
  echo "R7A1A5_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["COMPILE_FAILED"]'
  exit 2
}

(
  cd "$TMPDIR_PATH" || exit 2
  python3 -m pytest -q tests/test_r7a1a5_systemd_source_cutover_canary.py
) || {
  echo "R7A1A5_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  exit 2
}

python3 "$TMPDIR_PATH/tools/r7a1a5_systemd_source_cutover_canary.py" \
  --root "$ROOT" \
  --sha "$SHA" \
  --contract "$TMPDIR_PATH/backend/contracts/ZOS_R7A1A5_SYSTEMD_SOURCE_CUTOVER_CANARY_v1.json" \
  --smoke-timeout "$SMOKE_TIMEOUT"
RC=$?

echo "R7A1A5_BOOTSTRAP_COMPLETE"
echo "RC=$RC"
exit "$RC"
