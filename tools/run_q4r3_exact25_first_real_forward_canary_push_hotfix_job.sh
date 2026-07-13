#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_CANARY_WORKTREE:-/tmp/q4r3-exact25-first-real-forward-canary-push-hotfix}
PYTHON_BIN=$ROOT/.venv/bin/python
BASE_RUNNER=$WORKTREE/tools/run_q4r3_exact25_first_real_forward_canary_arm_job.sh
PATCHED_RUNNER=$WORKTREE/.q4r3_exact25_first_real_forward_canary_arm_job.push_hotfix.sh

if [ ! -x "$PYTHON_BIN" ]; then
  echo "PYTHON_BIN_MISSING:$PYTHON_BIN" >&2
  exit 2
fi
if [ ! -f "$BASE_RUNNER" ]; then
  echo "BASE_RUNNER_MISSING:$BASE_RUNNER" >&2
  exit 2
fi

"$PYTHON_BIN" - "$BASE_RUNNER" "$PATCHED_RUNNER" <<'PY'
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
text = source.read_text(encoding="utf-8")
old = 'git push origin "HEAD:$BRANCH"'
new = 'git push origin "HEAD:refs/heads/$BRANCH"'
count = text.count(old)
if count != 1:
    raise SystemExit(f"PUSH_REFSPEC_PATCH_TARGET_COUNT:{count}")
patched = text.replace(old, new, 1)
if old in patched or patched.count(new) != 1:
    raise SystemExit("PUSH_REFSPEC_PATCH_VERIFICATION_FAILED")
target.write_text(patched, encoding="utf-8")
PY

chmod 0755 "$PATCHED_RUNNER"
bash -n "$PATCHED_RUNNER"
grep -Fq 'git push origin "HEAD:refs/heads/$BRANCH"' "$PATCHED_RUNNER"
if grep -Fq 'git push origin "HEAD:$BRANCH"' "$PATCHED_RUNNER"; then
  echo "OLD_PUSH_REFSPEC_STILL_PRESENT" >&2
  exit 3
fi

exec /usr/bin/bash "$PATCHED_RUNNER"
