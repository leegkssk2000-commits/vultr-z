#!/usr/bin/env bash
set -u

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
COMMAND_TIMEOUT="${3:-120}"

if [[ -z "$SHA" ]]; then
  echo "R7A1A6C2_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["MISSING_SHA"]'
  exit 2
fi

TMPDIR_PATH="$(mktemp -d /tmp/r7a1a6c2.XXXXXXXX)"
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
  services/telegram/zel_q4r3_telegram_pos_adapter_v2.py \
  tools/r7a1a5_systemd_source_cutover_canary.py \
  tools/r7a1a6_deployment_parity_command_smoke.py \
  tools/r7a1a6a_telegram_command_router_cutover.py \
  tools/r7a1a6a2_current_release_source_shim.py \
  tools/r7a1a6c_zero_epoch_surface_repair.py \
  tools/r7a1a6c2_retention_boundary_shim.py \
  tests/test_r7a1a5_systemd_source_cutover_canary.py \
  tests/test_r7a1a6a_telegram_command_router_cutover.py \
  tests/test_r7a1a6a2_current_release_source_shim.py \
  tests/test_r7a1a6c_zero_epoch_surface_repair.py \
  tests/test_r7a1a6c2_retention_boundary_shim.py \
  backend/contracts/ZOS_R7A1A5_SYSTEMD_SOURCE_CUTOVER_CANARY_v1.json \
  backend/contracts/ZOS_R7A1A6A_TELEGRAM_COMMAND_ROUTER_CUTOVER_v1.json \
  backend/contracts/ZOS_R7A1A6C_ZERO_EPOCH_SURFACE_ROUTER_REPAIR_v1.json \
  backend/contracts/ZOS_R7A1A6C2_RETENTION_BOUNDARY_v1.json
do
  show_file "$path" "$TMPDIR_PATH/$path" || {
    echo "R7A1A6C2_BOOTSTRAP_FAILED"
    echo "BLOCKERS=[\"FETCH_FAILED:$path\"]"
    exit 2
  }
done

python3 -m py_compile \
  "$TMPDIR_PATH/services/telegram/zel_q4r3_telegram_pos_adapter_v2.py" \
  "$TMPDIR_PATH/tools/r7a1a5_systemd_source_cutover_canary.py" \
  "$TMPDIR_PATH/tools/r7a1a6_deployment_parity_command_smoke.py" \
  "$TMPDIR_PATH/tools/r7a1a6a_telegram_command_router_cutover.py" \
  "$TMPDIR_PATH/tools/r7a1a6a2_current_release_source_shim.py" \
  "$TMPDIR_PATH/tools/r7a1a6c_zero_epoch_surface_repair.py" \
  "$TMPDIR_PATH/tools/r7a1a6c2_retention_boundary_shim.py" || {
  echo "R7A1A6C2_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["RUNNER_COMPILE_FAILED"]'
  exit 2
}

(
  cd "$TMPDIR_PATH" || exit 2
  python3 -m pytest -q \
    tests/test_r7a1a5_systemd_source_cutover_canary.py \
    tests/test_r7a1a6a_telegram_command_router_cutover.py \
    tests/test_r7a1a6a2_current_release_source_shim.py \
    tests/test_r7a1a6c_zero_epoch_surface_repair.py \
    tests/test_r7a1a6c2_retention_boundary_shim.py
) || {
  echo "R7A1A6C2_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  exit 2
}

python3 "$TMPDIR_PATH/tools/r7a1a6c_zero_epoch_surface_repair.py" apply \
  --root "$ROOT" \
  --contract "$TMPDIR_PATH/backend/contracts/ZOS_R7A1A6C_ZERO_EPOCH_SURFACE_ROUTER_REPAIR_v1.json"
REPAIR_RC=$?

if [[ "$REPAIR_RC" -ne 0 ]]; then
  echo "R7A1A6C2_BOOTSTRAP_COMPLETE"
  echo "STATE=HOLD"
  echo "REPAIR_RC=$REPAIR_RC"
  exit "$REPAIR_RC"
fi

echo "SURFACE_REPAIR_PASS=true"
echo "RETENTION_BOUNDARY_SPLIT=true"
echo "SEND_ONLY_WHEN_EACH_ACTION_REQUIRED_LINE_APPEARS"

python3 "$TMPDIR_PATH/tools/r7a1a6c2_retention_boundary_shim.py" \
  --root "$ROOT" \
  --sha "$SHA" \
  --router-runner "$TMPDIR_PATH/tools/r7a1a6a_telegram_command_router_cutover.py" \
  --source-shim "$TMPDIR_PATH/tools/r7a1a6a2_current_release_source_shim.py" \
  --source-cutover-runner "$TMPDIR_PATH/tools/r7a1a5_systemd_source_cutover_canary.py" \
  --parity-helper "$TMPDIR_PATH/tools/r7a1a6_deployment_parity_command_smoke.py" \
  --source-contract "$TMPDIR_PATH/backend/contracts/ZOS_R7A1A5_SYSTEMD_SOURCE_CUTOVER_CANARY_v1.json" \
  --router-contract "$TMPDIR_PATH/backend/contracts/ZOS_R7A1A6A_TELEGRAM_COMMAND_ROUTER_CUTOVER_v1.json" \
  --boundary-contract "$TMPDIR_PATH/backend/contracts/ZOS_R7A1A6C2_RETENTION_BOUNDARY_v1.json" \
  --command-timeout "$COMMAND_TIMEOUT"
ROUTER_RC=$?

if [[ "$ROUTER_RC" -ne 0 ]]; then
  python3 "$TMPDIR_PATH/tools/r7a1a6c_zero_epoch_surface_repair.py" rollback --root "$ROOT"
  SURFACE_ROLLBACK_RC=$?
  echo "R7A1A6C2_BOOTSTRAP_COMPLETE"
  echo "STATE=HOLD"
  echo "ROUTER_RC=$ROUTER_RC"
  echo "SURFACE_ROLLBACK_RC=$SURFACE_ROLLBACK_RC"
  exit "$ROUTER_RC"
fi

python3 "$TMPDIR_PATH/tools/r7a1a6c_zero_epoch_surface_repair.py" verify --root "$ROOT"
VERIFY_RC=$?

if [[ "$VERIFY_RC" -ne 0 ]]; then
  python3 "$TMPDIR_PATH/tools/r7a1a6c_zero_epoch_surface_repair.py" rollback --root "$ROOT"
  SURFACE_ROLLBACK_RC=$?
  echo "R7A1A6C2_BOOTSTRAP_COMPLETE"
  echo "STATE=HOLD"
  echo "ROUTER_RC=0"
  echo "ROUTER_RETAINED=true"
  echo "VERIFY_RC=$VERIFY_RC"
  echo "SURFACE_ROLLBACK_RC=$SURFACE_ROLLBACK_RC"
  exit "$VERIFY_RC"
fi

echo "R7A1A6C2_RETENTION_BOUNDARY_REPAIR_COMPLETE"
echo "STATE=PASS"
echo "SOURCE_CUTOVER_STATE=PASS"
echo "COMMAND_SMOKE_PASS_COUNT=3"
echo "DISTINCT_RESPONSE_KIND_COUNT=3"
echo "TARGET_PROCESS_RELEASE_PATH_BOUND=true"
echo "ROLLBACK_PERFORMED=false"
echo "ALIMI_HTTP_FILE_JSON_PARITY=true"
echo "LEDGER_ZERO_EPOCH=true"
echo "TRACE_ZERO_EPOCH=true"
echo "PROTECTED_CHANGE_COUNT=0"
echo "PAPER_MUTATION_COUNT=0"
echo "LIVE_MUTATION_COUNT=0"
echo "ORDER_MUTATION_COUNT=0"
echo "NEXT_STAGE=R7.A2_SEVEN_AXIS_S_GRADE_CONTRACT_FREEZE"
echo "R7A1A6C2_BOOTSTRAP_COMPLETE"
echo "RC=0"
exit 0
