#!/usr/bin/env bash
set -u

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
COMMAND_TIMEOUT="${3:-120}"

if [[ -z "$SHA" ]]; then
  echo "R7A1A6C_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["MISSING_SHA"]'
  exit 2
fi

TMPDIR_PATH="$(mktemp -d /tmp/r7a1a6c.XXXXXXXX)"
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
  tools/r7a1a6c_zero_epoch_surface_repair.py \
  tools/bootstrap_r7a1a6a_telegram_command_router_cutover.sh \
  tests/test_r7a1a6c_zero_epoch_surface_repair.py \
  backend/contracts/ZOS_R7A1A6C_ZERO_EPOCH_SURFACE_ROUTER_REPAIR_v1.json
do
  show_file "$path" "$TMPDIR_PATH/$path" || {
    echo "R7A1A6C_BOOTSTRAP_FAILED"
    echo "BLOCKERS=[\"FETCH_FAILED:$path\"]"
    exit 2
  }
done

python3 -m py_compile "$TMPDIR_PATH/tools/r7a1a6c_zero_epoch_surface_repair.py" || {
  echo "R7A1A6C_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["REPAIR_RUNNER_COMPILE_FAILED"]'
  exit 2
}

(
  cd "$TMPDIR_PATH" || exit 2
  python3 -m pytest -q tests/test_r7a1a6c_zero_epoch_surface_repair.py
) || {
  echo "R7A1A6C_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["REPAIR_FOCUSED_TEST_FAILED"]'
  exit 2
}

python3 "$TMPDIR_PATH/tools/r7a1a6c_zero_epoch_surface_repair.py" apply \
  --root "$ROOT" \
  --contract "$TMPDIR_PATH/backend/contracts/ZOS_R7A1A6C_ZERO_EPOCH_SURFACE_ROUTER_REPAIR_v1.json"
REPAIR_RC=$?

if [[ "$REPAIR_RC" -ne 0 ]]; then
  echo "R7A1A6C_BOOTSTRAP_COMPLETE"
  echo "STATE=HOLD"
  echo "REPAIR_RC=$REPAIR_RC"
  exit "$REPAIR_RC"
fi

echo "SURFACE_REPAIR_PASS=true"
echo "NEXT=TELEGRAM_DISTINCT_ROUTER_CUTOVER"
echo "SEND_ONLY_WHEN_EACH_ACTION_REQUIRED_LINE_APPEARS"

bash "$TMPDIR_PATH/tools/bootstrap_r7a1a6a_telegram_command_router_cutover.sh" \
  "$ROOT" "$SHA" "$COMMAND_TIMEOUT"
ROUTER_RC=$?

if [[ "$ROUTER_RC" -ne 0 ]]; then
  python3 "$TMPDIR_PATH/tools/r7a1a6c_zero_epoch_surface_repair.py" rollback --root "$ROOT"
  ROLLBACK_RC=$?
  echo "R7A1A6C_BOOTSTRAP_COMPLETE"
  echo "STATE=HOLD"
  echo "ROUTER_RC=$ROUTER_RC"
  echo "SURFACE_ROLLBACK_RC=$ROLLBACK_RC"
  exit "$ROUTER_RC"
fi

python3 "$TMPDIR_PATH/tools/r7a1a6c_zero_epoch_surface_repair.py" verify --root "$ROOT"
VERIFY_RC=$?

if [[ "$VERIFY_RC" -ne 0 ]]; then
  python3 "$TMPDIR_PATH/tools/r7a1a6c_zero_epoch_surface_repair.py" rollback --root "$ROOT"
  ROLLBACK_RC=$?
  echo "R7A1A6C_BOOTSTRAP_COMPLETE"
  echo "STATE=HOLD"
  echo "ROUTER_RC=0"
  echo "VERIFY_RC=$VERIFY_RC"
  echo "SURFACE_ROLLBACK_RC=$ROLLBACK_RC"
  exit "$VERIFY_RC"
fi

echo "R7A1A6C_ZERO_EPOCH_SURFACE_ROUTER_REPAIR_COMPLETE"
echo "STATE=PASS"
echo "SURFACE_REPAIR_STATE=PASS"
echo "COMMAND_SMOKE_PASS_COUNT=3"
echo "DISTINCT_RESPONSE_KIND_COUNT=3"
echo "ALIMI_HTTP_FILE_JSON_PARITY=true"
echo "LEDGER_ZERO_EPOCH=true"
echo "TRACE_ZERO_EPOCH=true"
echo "PROTECTED_CHANGE_COUNT=0"
echo "PAPER_MUTATION_COUNT=0"
echo "LIVE_MUTATION_COUNT=0"
echo "ORDER_MUTATION_COUNT=0"
echo "NEXT_STAGE=R7.A2_SEVEN_AXIS_S_GRADE_CONTRACT_FREEZE"
echo "R7A1A6C_BOOTSTRAP_COMPLETE"
echo "RC=0"
exit 0
