#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
TMP=""

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT
export PYTHONDONTWRITEBYTECODE=1

printf '%s\n' \
  'R7A4D2_MA5_INDEPENDENT_OOS_KILL_ZERO_FIX_START' \
  'MODE=TEMPORARY_EXACT_SEMANTIC_GATE_FIX' \
  'FIX=BLOCKER_COUNT_ZERO_MUST_REMAIN_ZERO' \
  'PATCH_SCOPE=temporary_oos_copy_only' \
  'STRATEGY_MUTATION_ALLOWED=false' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'CONFIG_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false' \
  'WORKTREE_POLICY=DO_NOT_TOUCH'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD_MA5_INDEPENDENT_OOS_KILL_ZERO_FIX_INPUT'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'RC=2'
  exit 2
fi

TMP="$(mktemp -d /tmp/r7a4d2-ma5-oos-kill-zero.XXXXXX)" || exit 2
BOOT="$TMP/bootstrap.sh"

if ! git -C "$ROOT" show "$SHA:tools/bootstrap_r7a4d2_ma5_independent_oos_expansion.sh" > "$BOOT"; then
  echo 'STATE=HOLD_MA5_INDEPENDENT_OOS_KILL_ZERO_FIX_INPUT'
  echo 'BLOCKERS=["BASE_BOOTSTRAP_MATERIALIZE_FAILED"]'
  echo 'RC=2'
  exit 2
fi

python3 - "$BOOT" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
anchor = '''TARGET="$TMP/tools/r7a4d2_ma5_independent_oos_expansion.py"
RAW="$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py"
'''
insert = '''TARGET="$TMP/tools/r7a4d2_ma5_independent_oos_expansion.py"

python3 - "$TARGET" <<'PATCHPY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text(encoding="utf-8")
old = '(int(kill_summary.get("blocker_count") or -1) == 0, "KILL_TEST_BLOCKED"),'
new = '(int(kill_summary.get("blocker_count", -1)) == 0, "KILL_TEST_BLOCKED"),'
if s.count(old) != 1:
    raise SystemExit("KILL_ZERO_PATCH_ANCHOR_INVALID")
p.write_text(s.replace(old, new, 1), encoding="utf-8")
PATCHPY
PATCH_RC=$?
if [[ "$PATCH_RC" -ne 0 ]]; then
  echo 'STATE=HOLD_MA5_INDEPENDENT_OOS_KILL_ZERO_FIX_INPUT'
  echo 'BLOCKERS=["KILL_ZERO_PATCH_FAILED"]'
  echo 'RC=2'
  exit 2
fi

echo 'STATE=PASS_MA5_INDEPENDENT_OOS_KILL_ZERO_SEMANTIC_FIX'
echo 'PATCH_SCOPE=temporary_oos_copy_only'
echo 'KILL_BLOCKER_COUNT_ZERO_PRESERVED=true'
RAW="$TMP/tools/r7a4d2_short_raw_geometry_and_simple_benchmark_execution.py"
'''
if text.count(anchor) != 1:
    raise SystemExit("BOOTSTRAP_PATCH_ANCHOR_INVALID")
path.write_text(text.replace(anchor, insert, 1), encoding="utf-8")
PY
PATCH_RC=$?

if [[ "$PATCH_RC" -ne 0 ]]; then
  echo 'STATE=HOLD_MA5_INDEPENDENT_OOS_KILL_ZERO_FIX_INPUT'
  echo 'BLOCKERS=["BOOTSTRAP_PATCH_FAILED"]'
  echo 'RC=2'
  exit 2
fi

chmod 700 "$BOOT"
echo "PATCHED_BOOTSTRAP_SHA256=$(sha256sum "$BOOT" | awk '{print $1}')"

bash "$BOOT" "$ROOT" "$SHA"
RC=$?

echo 'R7A4D2_MA5_INDEPENDENT_OOS_KILL_ZERO_FIX_COMPLETE'
echo "RC=$RC"
exit "$RC"
