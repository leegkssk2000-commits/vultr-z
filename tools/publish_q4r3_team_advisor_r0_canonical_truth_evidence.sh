#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${Q4R3_ROOT:-/home/z/z}"
WT="${Q4R3_WORKTREE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TARGET_BRANCH="${Q4R3_TARGET_BRANCH:-q4r3-team-advisor-r0-canonical-truth-audit-v1}"
PY="${Q4R3_PYTHON_BIN:-$ROOT/.venv/bin/python}"
[[ -x "$PY" ]] || PY="$ROOT/venv/bin/python"
[[ -x "$PY" ]] || { echo PYTHON_NOT_FOUND; exit 1; }

RUNTIME="$ROOT/runtime/exact25_edge_v1/team_advisor_r0_canonical_truth"
STATUS="$RUNTIME/status_latest.json"
UNITS="$RUNTIME/units_latest.json"
CANDIDATES="$RUNTIME/candidates_latest.json"
EVIDENCE_DIR="$WT/evidence"
OUT_STATUS="$EVIDENCE_DIR/q4r3_team_advisor_r0_canonical_truth_latest.json"
OUT_UNITS="$EVIDENCE_DIR/q4r3_team_advisor_r0_units_latest.json"
OUT_CANDIDATES="$EVIDENCE_DIR/q4r3_team_advisor_r0_candidates_latest.json"
OUT_SUMMARY="$EVIDENCE_DIR/q4r3_team_advisor_r0_summary_latest.md"

for required in "$STATUS" "$UNITS" "$CANDIDATES"; do
  [[ -f "$required" ]] || { echo "R0_EVIDENCE_MISSING=$required"; exit 1; }
done
mkdir -p "$EVIDENCE_DIR"

"$PY" - "$STATUS" "$UNITS" "$CANDIDATES" "$OUT_STATUS" "$OUT_UNITS" "$OUT_CANDIDATES" "$OUT_SUMMARY" <<'PY'
import json,re,sys
from pathlib import Path

status_path,units_path,candidates_path,out_status,out_units,out_candidates,out_summary=map(Path,sys.argv[1:])
status=json.loads(status_path.read_text(encoding="utf-8"))
units=json.loads(units_path.read_text(encoding="utf-8"))
candidates=json.loads(candidates_path.read_text(encoding="utf-8"))

assert status.get("state") in {"PASS","HOLD"}
assert "Zico" in status.get("scope",[]) and "Lico" in status.get("scope",[])
assert "ZICO" not in status.get("scope",[]) and "LiCo" not in status.get("scope",[])

secret_pattern=re.compile(r"(?:sk-[A-Za-z0-9_-]{12,}|(?i:api[_-]?key|secret|token|password|passphrase)\s*[=:]\s*(?!<redacted>)[^\s,;}]+)")
for payload in (status,units,candidates):
    rendered=json.dumps(payload,ensure_ascii=False)
    match=secret_pattern.search(rendered)
    if match:
        raise AssertionError(f"UNREDACTED_SECRET_PATTERN:{match.group(0)[:30]}")

for path,payload in ((out_status,status),(out_units,units),(out_candidates,candidates)):
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")

lines=[
    "# Q4R3 R0 Canonical Truth — Latest",
    "",
    f"- State: `{status['state']}`",
    f"- Verdict: `{status['verdict']}`",
    f"- Canonical owners: `{status['exit_gate']['canonical_owner_count']}/{status['exit_gate']['required_canonical_owner_count']}`",
    f"- Duplicate owners: `{status['exit_gate']['duplicate_owner_count']}`",
    f"- Active Exec mapping: `{status['exit_gate']['active_exec_mapping_pct']}%`",
    f"- Unclassified runtime candidates: `{status['exit_gate']['unclassified_runtime_candidate_count']}`",
    f"- Unresolved symlinks: `{status['exit_gate']['unresolved_symlink_count']}`",
    f"- Unresolved wrappers: `{status['exit_gate']['unresolved_wrapper_count']}`",
    "",
    "## Owner matrix",
    "",
    "| Component | State | Proven | Candidates | Unresolved |",
    "|---|---:|---:|---:|---|",
]
for component in status.get("scope",[]):
    row=status["owner_matrix"][component]
    unresolved=", ".join(row.get("unresolved") or []) or "-"
    lines.append(f"| {component} | {row['state']} | {row['proven_owner_count']} | {row['candidate_count']} | {unresolved} |")
lines.extend(["","## Policy surfaces",""])
for component in ("ZBot","Zico","Lico"):
    surface=status["policy_surface_coverage"][component]
    missing=", ".join(surface.get("missing") or []) or "-"
    lines.append(f"- **{component}**: `{surface['coverage_pct']}%`; missing: {missing}")
lines.extend(["","## Fix queue",""])
for item in status.get("fix_queue",[])[:200]:
    lines.append(f"- `{item['component']}` — `{item['code']}` — `{item['action']}`")
if not status.get("fix_queue"):
    lines.append("- none")
lines.extend(["","Canonical display spelling: **Zico**, **Lico**.",""])
out_summary.write_text("\n".join(lines),encoding="utf-8")
PY

git -C "$WT" add \
  "${OUT_STATUS#$WT/}" \
  "${OUT_UNITS#$WT/}" \
  "${OUT_CANDIDATES#$WT/}" \
  "${OUT_SUMMARY#$WT/}"

if git -C "$WT" diff --cached --quiet; then
  echo R0_EVIDENCE_UNCHANGED
  exit 0
fi

git -C "$WT" -c user.name="ZEL R0 Evidence" -c user.email="zel-r0-evidence@localhost" \
  commit -m "Record R0 canonical truth runtime evidence"
git -C "$WT" push origin "HEAD:refs/heads/$TARGET_BRANCH"

echo "R0_EVIDENCE_PUBLISHED=$OUT_STATUS"
