#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:?target SHA required}"
cd "$ROOT" || exit 1

printf '%s\n' \
  'R7A3E3B_START' \
  'MODE=ATOMIC_GIT_OBJECT_PERSISTENCE_CLOSURE' \
  'WORKTREE_INDEX_MUTATION_ALLOWED=false' \
  'PERSIST_SCOPE=25_STRATEGY_SOURCES_PLUS_REGISTRY_AND_CONFIG' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SIMULATION_REPLAY_EXECUTION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

TMP="$(mktemp -d /tmp/r7a3e3b.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/tools" "$TMP/tests" "$TMP/backend/contracts"

git show "$SHA:tools/r7a3e3b_strategy25_git_persistence_closure.py" > "$TMP/tools/r7a3e3b_strategy25_git_persistence_closure.py"
git show "$SHA:tests/test_r7a3e3b_strategy25_git_persistence_closure.py" > "$TMP/tests/test_r7a3e3b_strategy25_git_persistence_closure.py"
git show "$SHA:backend/contracts/ZOS_R7A3E3B_STRATEGY25_GIT_PERSISTENCE_CLOSURE_v1.json" > "$TMP/backend/contracts/ZOS_R7A3E3B_STRATEGY25_GIT_PERSISTENCE_CLOSURE_v1.json"

python3 -m py_compile "$TMP/tools/r7a3e3b_strategy25_git_persistence_closure.py"
PYTHONPATH="$TMP/tools" python3 -m pytest -q "$TMP/tests/test_r7a3e3b_strategy25_git_persistence_closure.py"

set +e
python3 "$TMP/tools/r7a3e3b_strategy25_git_persistence_closure.py" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --contract "$TMP/backend/contracts/ZOS_R7A3E3B_STRATEGY25_GIT_PERSISTENCE_CLOSURE_v1.json" \
  --apply
RC=$?
set -e

printf 'R7A3E3B_BOOTSTRAP_COMPLETE\nRC=%s\n' "$RC"
exit "$RC"
