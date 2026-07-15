#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TARGET_BRANCH="${Q4R3_TARGET_BRANCH:-q4r3-team-advisor-r02-zico-secure-mirror-v1}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/.venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/venv/bin/python"
[[ -x "$PY" ]] || PY=python3

SOURCE=/opt/zico-ceo-canonical-adapter/adapter.py
MIRROR="$WT/canonical/zico/adapter.py"
MANIFEST="$WT/canonical/zico/manifest.json"
EVIDENCE="$WT/evidence/q4r3_team_advisor_r02_zico_secure_mirror_latest.json"

for required in "$SOURCE" "$MIRROR" "$MANIFEST" "$EVIDENCE"; do
  [[ -f "$required" ]] || { echo "PUBLISH_INPUT_MISSING=$required"; exit 1; }
done

cmp "$SOURCE" "$MIRROR"

"$PY" - "$EVIDENCE" "$MANIFEST" <<'PY'
import json,sys
result=json.load(open(sys.argv[1],encoding="utf-8"))
manifest=json.load(open(sys.argv[2],encoding="utf-8"))
assert result.get("state")=="PASS", result
assert result.get("mirror_written") is True, result
assert result.get("audit",{}).get("direct_order_calls")==[], result
assert result.get("audit",{}).get("sensitive_literals")==[], result
assert manifest.get("canonical_name")=="Zico", manifest
assert manifest.get("source_sha256")==manifest.get("mirror_sha256"), manifest
assert manifest.get("byte_parity") is True, manifest
PY

git -C "$WT" add \
  canonical/zico/adapter.py \
  canonical/zico/manifest.json \
  evidence/q4r3_team_advisor_r02_zico_secure_mirror_latest.json

if git -C "$WT" diff --cached --quiet; then
  echo R02_ZICO_MIRROR_EVIDENCE_UNCHANGED
  exit 0
fi

SKIP=black,ruff,mypy git -C "$WT" \
  -c user.name="ZEL Runtime Evidence" \
  -c user.email="zel-runtime-evidence@localhost" \
  commit -m "Mirror active Zico canonical runtime with byte parity"

git -C "$WT" push origin "HEAD:refs/heads/$TARGET_BRANCH"

echo R02_ZICO_SECURE_MIRROR_PUBLISHED
echo "MIRROR=canonical/zico/adapter.py"
echo "MANIFEST=canonical/zico/manifest.json"
echo "EVIDENCE=evidence/q4r3_team_advisor_r02_zico_secure_mirror_latest.json"
