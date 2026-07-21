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

TMP_ROOT="$(mktemp -d /tmp/r7a4d2_vwap_geometry.XXXXXX)"
trap 'rm -rf "$TMP_ROOT"' EXIT
mkdir -p "$TMP_ROOT/tools" "$TMP_ROOT/tests"

git show "${TARGET_SHA}:tools/r7a4d2_vwap_revert_geometry_closure.py" \
  > "$TMP_ROOT/tools/r7a4d2_vwap_revert_geometry_closure.py"
git show "${TARGET_SHA}:tests/test_r7a4d2_vwap_revert_geometry_closure.py" \
  > "$TMP_ROOT/tests/test_r7a4d2_vwap_revert_geometry_closure.py"

python3 -m pytest -q "$TMP_ROOT/tests/test_r7a4d2_vwap_revert_geometry_closure.py"
python3 -m py_compile "$TMP_ROOT/tools/r7a4d2_vwap_revert_geometry_closure.py"

python3 "$TMP_ROOT/tools/r7a4d2_vwap_revert_geometry_closure.py" \
  --root "$ROOT"

python3 "$TMP_ROOT/tools/r7a4d2_vwap_revert_geometry_closure.py" \
  --root "$ROOT" --apply

python3 -m py_compile "$ROOT/backend/strategies/vwap_revert.py"

python3 - "$ROOT" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
source = root / "backend/strategies/vwap_revert.py"
registry_path = root / "backend/strategy25/canonical_strategy_registry_v1.json"
source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
registry = json.loads(registry_path.read_text(encoding="utf-8"))
entries = [
    row for row in registry.get("entries", [])
    if isinstance(row, dict) and row.get("strategy_id") == "vwap_revert"
]
assert len(entries) == 1, len(entries)
engine = entries[0]["canonical_engine"]
assert engine["source_sha256"] == source_sha
assert engine["binding_source"] == "R7.A4D2_VWAP_GEOMETRY_CLOSURE"
assert engine["decision_reason"] == "VWAP_SCALE_IN_REVERSION_TARGET_GEOMETRY_CLOSED"
text = source.read_text(encoding="utf-8")
assert '0.0 < long_avg_entry < price < long_reversion_target' in text
assert 'short_reversion_target < price < short_avg_entry' in text
assert 'cfg.scale_in_to_vwap_progress <= progress < 1.0' in text
print("POST_APPLY_SOURCE_REGISTRY_PARITY=true")
print("POST_APPLY_SOURCE_SHA256=" + source_sha)
PY

echo "R7A4D2_VWAP_GEOMETRY_BOOTSTRAP_COMPLETE"
echo "RC=0"
