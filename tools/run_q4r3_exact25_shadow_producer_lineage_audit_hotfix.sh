#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WT=${Q4R3_PRODUCER_AUDIT_WORKTREE:-/tmp/q4r3-exact25-shadow-producer-lineage-audit}
AUDITOR="$WT/tools/q4r3_exact25_shadow_producer_lineage_audit.py"
RUNNER="$WT/tools/run_q4r3_exact25_shadow_producer_lineage_audit_job.sh"
PYTHON_BIN="$ROOT/.venv/bin/python"

for required in "$AUDITOR" "$RUNNER" "$PYTHON_BIN"; do
  [ -e "$required" ] || { echo "REQUIRED_INPUT_MISSING:$required" >&2; exit 2; }
done

"$PYTHON_BIN" - "$AUDITOR" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old_tokens = '    "trace", "probe", "report", "test", "candidate", "roadmap", "forensic",\n'
new_tokens = '    "trace", "probe", "report", "unit_test", "candidate", "roadmap", "forensic",\n'
old_close = '    has_close_evidence = close_markers > 0 or bool(first({"x": None}, ())) or close_value_hits > 0\n'
new_close = '    has_close_evidence = close_markers > 0 or close_value_hits > 0\n'

if text.count(old_tokens) != 1:
    raise SystemExit(f"AUDIT_TOKEN_PATCH_TARGET_COUNT:{text.count(old_tokens)}")
if text.count(old_close) != 1:
    raise SystemExit(f"CLOSE_EVIDENCE_PATCH_TARGET_COUNT:{text.count(old_close)}")
text = text.replace(old_tokens, new_tokens, 1).replace(old_close, new_close, 1)
path.write_text(text, encoding="utf-8")

patched = path.read_text(encoding="utf-8")
if '"report", "test", "candidate"' in patched:
    raise SystemExit("LATEST_FALSE_POSITIVE_PATCH_NOT_APPLIED")
if 'bool(first({"x": None}, ()))' in patched:
    raise SystemExit("CLOSE_EVIDENCE_CLEANUP_NOT_APPLIED")
print("HOTFIX_APPLIED latest_not_misclassified_as_test=true close_evidence_clean=true")
PY

bash -n "$AUDITOR" 2>/dev/null || true
"$PYTHON_BIN" -m py_compile "$AUDITOR"
PYTHONPATH="$WT:$ROOT" "$PYTHON_BIN" -m pytest -q "$WT/tests/test_q4r3_exact25_shadow_producer_lineage_audit.py"

exec /usr/bin/bash "$RUNNER"
