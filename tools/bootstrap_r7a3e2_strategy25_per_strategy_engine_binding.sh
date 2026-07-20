#!/usr/bin/env bash
set -u

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
RC=0
TMP=""

cleanup() {
  [[ -n "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT

show_file() {
  local src="$1" dst="$2"
  mkdir -p "$(dirname "$dst")"
  git -C "$ROOT" -c safe.directory="$ROOT" show "$SHA:$src" > "$dst"
}

[[ -n "$SHA" ]] || { echo 'BLOCKERS=["MISSING_SHA"]'; exit 2; }
git -C "$ROOT" -c safe.directory="$ROOT" cat-file -e "$SHA^{commit}" || exit 2

TMP="$(mktemp -d /tmp/r7a3e2.XXXXXXXX)"
for path in \
  tools/r7a3e2_binding_lib.py \
  tools/r7a3e2_strategy25_binding_snapshot.py \
  tests/test_r7a3e2_binding_lib.py \
  backend/contracts/ZOS_R7A3E2_STRATEGY25_PER_STRATEGY_ENGINE_BINDING_v1.json
 do
  show_file "$path" "$TMP/$path" || RC=2
done

if [[ "$RC" -eq 0 ]]; then
  python3 -m py_compile \
    "$TMP/tools/r7a3e2_binding_lib.py" \
    "$TMP/tools/r7a3e2_strategy25_binding_snapshot.py" || RC=2
fi
if [[ "$RC" -eq 0 ]]; then
  PYTHONPATH="$TMP" python3 -m pytest -q "$TMP/tests/test_r7a3e2_binding_lib.py" || RC=2
fi
if [[ "$RC" -eq 0 ]]; then
  mkdir -p "$TMP/snapshot"
  git -C "$ROOT" -c safe.directory="$ROOT" archive "$SHA" | tar -x -C "$TMP/snapshot" || RC=2
  git -C "$ROOT" -c safe.directory="$ROOT" ls-tree -r "$SHA" > "$TMP/tree.txt" || RC=2
fi
if [[ "$RC" -eq 0 ]]; then
  echo R7A3E2_START
  echo MODE=READ_ONLY_PER_STRATEGY_ENGINE_AND_CONFIG_BINDING
  echo CANONICAL_REGISTRY_MUTATION_ALLOWED=false
  echo STRATEGY_LOGIC_MUTATION_ALLOWED=false
  echo ROUTER_MUTATION_ALLOWED=false
  echo SERVICE_MUTATION_ALLOWED=false
  echo SIMULATION_REPLAY_EXECUTION_ALLOWED=false
  echo SHADOW_START_ALLOWED=false
  echo PAPER_LIVE_ORDER_ALLOWED=false
  PYTHONPATH="$TMP/tools" python3 "$TMP/tools/r7a3e2_strategy25_binding_snapshot.py" \
    --root "$ROOT" \
    --snapshot "$TMP/snapshot" \
    --tree "$TMP/tree.txt" \
    --target-sha "$SHA" \
    --contract "$TMP/backend/contracts/ZOS_R7A3E2_STRATEGY25_PER_STRATEGY_ENGINE_BINDING_v1.json" || RC=$?
fi

echo R7A3E2_BOOTSTRAP_COMPLETE
echo RC="$RC"
exit "$RC"
