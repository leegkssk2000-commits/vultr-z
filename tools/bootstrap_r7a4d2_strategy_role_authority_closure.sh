#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/home/z/z}"
TARGET_SHA="${2:-}"

if [[ -z "$TARGET_SHA" ]]; then
  echo "TARGET_SHA_REQUIRED" >&2
  exit 2
fi

cd "$ROOT"
git cat-file -e "${TARGET_SHA}^{commit}"

TMP_ROOT="$(mktemp -d /tmp/r7a4d2_role_authority.XXXXXX)"
trap 'rm -rf "$TMP_ROOT"' EXIT
mkdir -p "$TMP_ROOT/tools" "$TMP_ROOT/tests"

for path in \
  tools/r7a4d2_strategy_role_authority_closure.py \
  tests/test_r7a4d2_strategy_role_authority_closure.py
 do
  git show "${TARGET_SHA}:$path" > "$TMP_ROOT/$path"
done

python3 -m py_compile "$TMP_ROOT/tools/r7a4d2_strategy_role_authority_closure.py"
PYTHONPATH="$TMP_ROOT" python3 -m pytest -q \
  "$TMP_ROOT/tests/test_r7a4d2_strategy_role_authority_closure.py"

python3 "$TMP_ROOT/tools/r7a4d2_strategy_role_authority_closure.py" \
  --root "$ROOT"

python3 "$TMP_ROOT/tools/r7a4d2_strategy_role_authority_closure.py" \
  --root "$ROOT" --apply

python3 - "$ROOT" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
registry_path = root / "backend/strategy25/canonical_strategy_registry_v1.json"
config_path = root / "backend/strategy25/canonical_strategy25_config_v1.json"
targets = {
    "break_and_continue",
    "rbreaker_like",
    "squeeze_break",
    "trend_ma_macd",
    "vwap_revert",
}

registry = json.loads(registry_path.read_text(encoding="utf-8"))
entries = {
    str(row.get("strategy_id") or ""): row
    for row in registry.get("entries", [])
    if isinstance(row, dict)
}
assert len(entries) == 25, len(entries)
assert set(targets).issubset(entries)
assert all(row.get("active_allowed") is False for row in entries.values())

for strategy_id in sorted(targets):
    row = entries[strategy_id]
    assert row.get("strategy_role") == "standalone"
    assert row.get("execution_scope") == "independent_entry_add_reduce_exit"
    assert row.get("role_authority_source") == "R7.A4D2_ENTRY_TO_ADD_CHAIN_DIAGNOSE"
    assert row.get("role_authority_reason") == (
        "SOURCE_ENTER_AND_ADD_BRANCHES_PRESENT_ROLE_AUTHORITY_EXPLICIT"
    )
    engine = row["canonical_engine"]
    source_path = root / engine["implementation_path"]
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert source_sha == engine["source_sha256"], strategy_id

config = json.loads(config_path.read_text(encoding="utf-8"))
assert int(config.get("strategy_count") or 0) == 25
assert set(config.get("strategies", {})) == set(entries)

print("POST_APPLY_ROLE_CLOSED_COUNT=5")
print("POST_APPLY_ACTIVE_ALLOWED_TRUE_COUNT=0")
print("POST_APPLY_SOURCE_REGISTRY_PARITY=true")
print("POST_APPLY_CONFIG_STRATEGY_SET_PARITY=true")
PY

echo "R7A4D2_STRATEGY_ROLE_AUTHORITY_BOOTSTRAP_COMPLETE"
echo "RC=0"
