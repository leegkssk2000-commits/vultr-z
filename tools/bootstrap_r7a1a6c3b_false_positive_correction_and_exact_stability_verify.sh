#!/usr/bin/env bash
set -u

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
TRACE_SECONDS="${3:-90}"
STABLE_SECONDS="${4:-30}"
RC=0

TMPDIR_PATH=""
cleanup() {
  if [[ -n "$TMPDIR_PATH" ]]; then
    rm -rf "$TMPDIR_PATH"
  fi
}
trap cleanup EXIT

show_file() {
  local repo_path="$1"
  local output_path="$2"
  mkdir -p "$(dirname "$output_path")"
  git -C "$ROOT" -c safe.directory="$ROOT" show "$SHA:$repo_path" > "$output_path"
}

if [[ -z "$SHA" ]]; then
  echo "R7A1A6C3B_BOOTSTRAP_FAILED"
  echo 'BLOCKERS=["MISSING_SHA"]'
  RC=2
fi

if [[ "$RC" -eq 0 ]]; then
  TMPDIR_PATH="$(mktemp -d /tmp/r7a1a6c3b.XXXXXXXX)"
  for path in \
    tools/r7a1a6c3b_false_positive_correction_and_exact_stability_verify.py \
    tools/r7a1a6c_zero_epoch_surface_repair.py \
    tests/test_r7a1a6c3b_false_positive_correction.py \
    backend/contracts/ZOS_R7A1A6C3B_FALSE_POSITIVE_CORRECTION_AND_EXACT_STABILITY_VERIFY_v1.json \
    backend/contracts/ZOS_R7A1A6C_ZERO_EPOCH_SURFACE_ROUTER_REPAIR_v1.json
  do
    if ! show_file "$path" "$TMPDIR_PATH/$path"; then
      echo "R7A1A6C3B_BOOTSTRAP_FAILED"
      echo "BLOCKERS=[\"FETCH_FAILED:$path\"]"
      RC=2
      break
    fi
  done
fi

if [[ "$RC" -eq 0 ]]; then
  if ! python3 -m py_compile \
    "$TMPDIR_PATH/tools/r7a1a6c3b_false_positive_correction_and_exact_stability_verify.py" \
    "$TMPDIR_PATH/tools/r7a1a6c_zero_epoch_surface_repair.py"
  then
    echo "R7A1A6C3B_BOOTSTRAP_FAILED"
    echo 'BLOCKERS=["RUNNER_COMPILE_FAILED"]'
    RC=2
  fi
fi

if [[ "$RC" -eq 0 ]]; then
  if ! (
    cd "$TMPDIR_PATH" &&
    python3 -m pytest -q tests/test_r7a1a6c3b_false_positive_correction.py
  ); then
    echo "R7A1A6C3B_BOOTSTRAP_FAILED"
    echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
    RC=2
  fi
fi

if [[ "$RC" -eq 0 ]]; then
  echo "R7A1A6C3B_START"
  echo "MODE=FINGERPRINT_GATED_EXACT_STABILITY_VERIFY"
  echo "NO_TELEGRAM_COMMAND_REQUIRED=true"
  echo "NO_UNCONFIRMED_UNIT_QUARANTINE=true"
  echo "TRACE_SECONDS=$TRACE_SECONDS"
  echo "STABLE_SECONDS=$STABLE_SECONDS"

  if python3 "$TMPDIR_PATH/tools/r7a1a6c3b_false_positive_correction_and_exact_stability_verify.py" \
    --root "$ROOT" \
    --contract "$TMPDIR_PATH/backend/contracts/ZOS_R7A1A6C3B_FALSE_POSITIVE_CORRECTION_AND_EXACT_STABILITY_VERIFY_v1.json" \
    --repair-runner "$TMPDIR_PATH/tools/r7a1a6c_zero_epoch_surface_repair.py" \
    --repair-contract "$TMPDIR_PATH/backend/contracts/ZOS_R7A1A6C_ZERO_EPOCH_SURFACE_ROUTER_REPAIR_v1.json" \
    --trace-seconds "$TRACE_SECONDS" \
    --stable-seconds "$STABLE_SECONDS"
  then
    RC=0
  else
    RC=$?
  fi
fi

echo "R7A1A6C3B_BOOTSTRAP_COMPLETE"
echo "RC=$RC"
