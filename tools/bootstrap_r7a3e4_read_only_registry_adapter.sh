#!/usr/bin/env bash
set -uo pipefail

ROOT="${1:-/home/z/z}"
SHA="${2:-}"
RC=2
TMP=""
DEST="$ROOT/backend/strategy25/read_only_registry_adapter_v1.py"
BACKUP=""
INSTALLED=false

cleanup() {
  [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
}
trap cleanup EXIT

printf '%s\n' \
  'R7A3E4_START' \
  'MODE=ATOMIC_READ_ONLY_REGISTRY_ADAPTER_INSTALL_AND_VERIFY' \
  'ADAPTER_MUTATION_ALLOWED=true' \
  'REGISTRY_MUTATION_ALLOWED=false' \
  'STRATEGY_SOURCE_MUTATION_ALLOWED=false' \
  'ROUTER_MUTATION_ALLOWED=false' \
  'SERVICE_MUTATION_ALLOWED=false' \
  'SIMULATION_REPLAY_EXECUTION_ALLOWED=false' \
  'SHADOW_START_ALLOWED=false' \
  'PAPER_LIVE_ORDER_ALLOWED=false'

if [[ -z "$SHA" ]] || ! git -C "$ROOT" cat-file -e "$SHA^{commit}" 2>/dev/null; then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["TARGET_SHA_INVALID"]'
  echo 'R7A3E4_BOOTSTRAP_COMPLETE'
  echo 'RC=2'
  exit 2
fi

TMP="$(mktemp -d /tmp/r7a3e4.XXXXXX)" || exit 2
for path in \
  backend/strategy25/read_only_registry_adapter_v1.py \
  backend/contracts/ZOS_R7A3E4_READ_ONLY_REGISTRY_ADAPTER_v1.json \
  tools/r7a3e4_read_only_registry_adapter_verify.py \
  tests/test_r7a3e4_read_only_registry_adapter.py
do
  mkdir -p "$TMP/$(dirname "$path")"
  if ! git -C "$ROOT" show "$SHA:$path" > "$TMP/$path"; then
    echo 'STATE=HOLD'
    echo 'BLOCKER_COUNT=1'
    printf 'BLOCKERS=["MATERIALIZE_FAILED:%s"]\n' "$path"
    echo 'R7A3E4_BOOTSTRAP_COMPLETE'
    echo 'RC=2'
    exit 2
  fi
done

if ! python3 -m py_compile \
  "$TMP/backend/strategy25/read_only_registry_adapter_v1.py" \
  "$TMP/tools/r7a3e4_read_only_registry_adapter_verify.py"; then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["PY_COMPILE_FAILED"]'
  echo 'R7A3E4_BOOTSTRAP_COMPLETE'
  echo 'RC=2'
  exit 2
fi

if ! PYTHONPATH="$TMP" python3 -m pytest -q "$TMP/tests/test_r7a3e4_read_only_registry_adapter.py"; then
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["FOCUSED_TEST_FAILED"]'
  echo 'R7A3E4_BOOTSTRAP_COMPLETE'
  echo 'RC=2'
  exit 2
fi

mkdir -p "$(dirname "$DEST")"
if [[ -f "$DEST" ]]; then
  BACKUP="$TMP/adapter.previous.py"
  cp -p "$DEST" "$BACKUP" || exit 2
fi
INSTALL_TMP="$(dirname "$DEST")/.read_only_registry_adapter_v1.py.r7a3e4.$$"
if ! install -m 0644 "$TMP/backend/strategy25/read_only_registry_adapter_v1.py" "$INSTALL_TMP" || ! mv -f "$INSTALL_TMP" "$DEST"; then
  rm -f "$INSTALL_TMP"
  echo 'STATE=HOLD'
  echo 'BLOCKER_COUNT=1'
  echo 'BLOCKERS=["ADAPTER_INSTALL_FAILED"]'
  echo 'R7A3E4_BOOTSTRAP_COMPLETE'
  echo 'RC=2'
  exit 2
fi
INSTALLED=true

python3 "$TMP/tools/r7a3e4_read_only_registry_adapter_verify.py" \
  --root "$ROOT" \
  --target-sha "$SHA" \
  --contract "$TMP/backend/contracts/ZOS_R7A3E4_READ_ONLY_REGISTRY_ADAPTER_v1.json"
RC=$?

if [[ "$RC" -ne 0 && "$INSTALLED" == true ]]; then
  if [[ -n "$BACKUP" && -f "$BACKUP" ]]; then
    cp -p "$BACKUP" "$DEST"
  else
    rm -f "$DEST"
  fi
  echo 'ROLLBACK_PERFORMED=true'
else
  echo 'ROLLBACK_PERFORMED=false'
fi

echo 'R7A3E4_BOOTSTRAP_COMPLETE'
echo "RC=$RC"
exit "$RC"
