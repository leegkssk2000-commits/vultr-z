#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_FUNNEL_SCOPE_WORKTREE:-/tmp/q4r3-exact25-funnel-counter-scope-repair-v2}
PYTHON_BIN=$ROOT/.venv/bin/python
INNER_RUNNER=$WORKTREE/tools/run_q4r3_exact25_funnel_counter_scope_repair_job.sh

if [ "$(id -u)" -ne 0 ]; then
  echo RUN_AS_ROOT >&2
  exit 1
fi

for required in "$PYTHON_BIN" "$WORKTREE" "$INNER_RUNNER"; do
  [ -e "$required" ] || {
    echo "REQUIRED_INPUT_MISSING:$required" >&2
    exit 2
  }
done

# Force Python/pytest to resolve the candidate worktree first. The prior job
# inherited /home/z/z as cwd, so the active old tools package shadowed the
# patched candidate module during tests.
cd "$WORKTREE"
find "$WORKTREE" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
find "$WORKTREE" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete 2>/dev/null || true
export PYTHONPATH="$WORKTREE"
export PYTHONDONTWRITEBYTECODE=1

"$PYTHON_BIN" - "$WORKTREE" <<'PY'
from pathlib import Path
import importlib
import sys

worktree = Path(sys.argv[1]).resolve()
module = importlib.import_module("tools.q4r3_exact25_six_layer_observer_core")
loaded = Path(module.__file__).resolve()
print(f"WORKTREE_IMPORT_CHECK={loaded}")
if worktree not in loaded.parents:
    raise SystemExit(f"WORKTREE_IMPORT_ISOLATION_FAILED:{loaded}")
PY

Q4R3_FUNNEL_SCOPE_WORKTREE="$WORKTREE" \
  bash "$INNER_RUNNER"
