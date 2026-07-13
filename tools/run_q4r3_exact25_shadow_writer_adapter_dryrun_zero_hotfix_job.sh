#!/usr/bin/env bash
set -Eeuo pipefail

WORKTREE=${Q4R3_ADAPTER_WORKTREE:-/tmp/q4r3-exact25-shadow-writer-adapter-dryrun-zero-hotfix}
SOURCE_RUNNER=$WORKTREE/tools/run_q4r3_exact25_shadow_writer_adapter_dryrun_job.sh
PATCHED_RUNNER=/tmp/q4r3_exact25_shadow_writer_adapter_dryrun_zero_hotfix.$$.sh

cleanup() {
  rm -f "$PATCHED_RUNNER"
}
trap cleanup EXIT

if [ ! -f "$SOURCE_RUNNER" ]; then
  echo "SOURCE_RUNNER_MISSING:$SOURCE_RUNNER" >&2
  exit 2
fi

/usr/bin/python3 - "$SOURCE_RUNNER" "$PATCHED_RUNNER" <<'PY'
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
text = source.read_text(encoding="utf-8")
old = 'int(payload.get("writer_invocation_count") or -1)'
new = 'int(payload.get("writer_invocation_count", -1))'
count = text.count(old)
if count != 1:
    raise SystemExit(f"ZERO_ASSERTION_PATCH_TARGET_COUNT:{count}")
target.write_text(text.replace(old, new, 1), encoding="utf-8")
PY

chmod 0755 "$PATCHED_RUNNER"
bash -n "$PATCHED_RUNNER"

grep -F 'int(payload.get("writer_invocation_count", -1))' "$PATCHED_RUNNER" >/dev/null
if grep -F 'int(payload.get("writer_invocation_count") or -1)' "$PATCHED_RUNNER" >/dev/null; then
  echo "OLD_ZERO_ASSERTION_STILL_PRESENT" >&2
  exit 3
fi

exec /usr/bin/bash "$PATCHED_RUNNER"
