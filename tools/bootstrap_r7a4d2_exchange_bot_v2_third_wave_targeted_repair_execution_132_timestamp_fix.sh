#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
TMP=""
RC=2

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_EXCHANGE_BOT_V2_THIRD_WAVE_TIMESTAMP_FIX_START' \
  'MODE=READ_ONLY_INDICATOR_HELPER_TIMESTAMP_DTYPE_REBIND' \
  'EXPECTED_TIMESTAMP_DTYPE=float64' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'MARKET_SOURCE_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_EXCHANGE_BOT_V2_THIRD_WAVE_TIMESTAMP_FIX_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

TMP="$(mktemp -d /tmp/r7a4d2-third-wave-timestamp-fix.XXXXXX)" || exit 2
INNER="$TMP/bootstrap_inner.sh"
COMPAT="$TMP/r7a4d2_third_wave_indicator_helper_compat.py"

if ! git -C "$ROOT" show \
  "$SHA:tools/r7a4d2_third_wave_indicator_helper_compat.py" > "$COMPAT"
then
  echo 'STATE=HOLD_EXCHANGE_BOT_V2_THIRD_WAVE_TIMESTAMP_FIX_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["COMPAT_HELPER_MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 -m py_compile "$COMPAT" || ! python3 "$COMPAT"; then
  echo 'STATE=HOLD_EXCHANGE_BOT_V2_THIRD_WAVE_TIMESTAMP_FIX_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["COMPAT_HELPER_SELF_TEST_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! git -C "$ROOT" show \
  "$SHA:tools/bootstrap_r7a4d2_exchange_bot_v2_third_wave_targeted_repair_execution_132.sh" > "$INNER"
then
  echo 'STATE=HOLD_EXCHANGE_BOT_V2_THIRD_WAVE_TIMESTAMP_FIX_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["INNER_BOOTSTRAP_MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

if ! python3 - "$INNER" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old_path = "tools/r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_execution_132.py"
new_path = "tools/r7a4d2_third_wave_indicator_helper_compat.py"
if text.count(old_path) != 2:
    raise SystemExit(f"INDICATOR_HELPER_BIND_ANCHOR_INVALID:{text.count(old_path)}")
text = text.replace(old_path, new_path)
text = text.replace(
    "INDICATOR_HELPER_SOURCE=r7a4d2_exchange_bot_v2_remaining_11_lane_uplift_execution_132.py",
    "INDICATOR_HELPER_SOURCE=r7a4d2_third_wave_indicator_helper_compat.py",
)
path.write_text(text, encoding="utf-8")
PY
then
  echo 'STATE=HOLD_EXCHANGE_BOT_V2_THIRD_WAVE_TIMESTAMP_FIX_INPUT'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["INNER_BOOTSTRAP_REBIND_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo 'STATE=PASS_EXCHANGE_BOT_V2_THIRD_WAVE_TIMESTAMP_DTYPE_REBIND'
echo 'INDICATOR_HELPER_SOURCE=r7a4d2_third_wave_indicator_helper_compat.py'
echo 'TIMESTAMP_NORMALIZATION=left_float64,right_float64'
echo 'PATCH_SCOPE=temporary_execution_copy_only'

bash "$INNER" "$ROOT" "$SHA"
RC=$?

echo 'R7A4D2_EXCHANGE_BOT_V2_THIRD_WAVE_TIMESTAMP_FIX_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
