#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=/home/z/z
WORKTREE=${Q4R3_TRADE_METHOD_HARDENING_WORKTREE:-/tmp/q4r3-exact25-trade-method-research-hardening}
PYTHON_BIN=$ROOT/.venv/bin/python
CONFIG=$WORKTREE/config/q4r3_exact25_trade_method_research_hardening_ssot.json
BRANCH=q4r3-exact25-trade-method-research-hardening
RESULT_ROOT=$WORKTREE/runtime_results/q4r3/exact25_trade_method_source_capture_audit
SNAPSHOT_ROOT=$RESULT_ROOT/source_snapshot/backend/trade_methods
REPORT=$RESULT_ROOT/report_latest.json
LIVE_ROOT=$ROOT/runtime/exact25_edge_v1/trade_method_research_hardening
LIVE_REPORT=$LIVE_ROOT/source_capture_audit_latest.json
JOB_STATUS=$ROOT/runtime/q4r3_exact25_trade_method_source_capture_audit_job_latest.json
LOG=$ROOT/runtime/q4r3_exact25_trade_method_source_capture_audit_job.log
LEDGER=$ROOT/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl
PRODUCER_UNIT=q4r3-exact25-shadow-producer.service
WRITER_UNIT=q4r3-exact25-persistent-single-event-writer.service

exec > >(tee -a "$LOG") 2>&1

fail() {
  local stage=$1
  local reason=$2
  "$PYTHON_BIN" - "$JOB_STATUS" "$stage" "$reason" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
path = Path(sys.argv[1])
payload = {
    "job": "q4r3_exact25_trade_method_source_capture_audit",
    "state": "FAILED",
    "current_stage": sys.argv[2],
    "reason": sys.argv[3],
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "action": "hold",
    "order_authority": "blocked",
    "execution_authority": "none",
    "strategy_modified": False,
    "trade_method_modified": False,
    "producer_modified": False,
    "writer_modified": False,
    "formal_ledger_modified": False,
}
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY
  echo "FAILED stage=$stage reason=$reason" >&2
  exit 1
}
trap 'fail unexpected "line=$LINENO command=$BASH_COMMAND"' ERR

[ "$(id -u)" -eq 0 ] || fail preflight RUN_AS_ROOT
for required in "$WORKTREE" "$PYTHON_BIN" "$CONFIG" "$LEDGER"; do
  [ -e "$required" ] || fail preflight "REQUIRED_INPUT_MISSING:$required"
done

mkdir -p "$SNAPSHOT_ROOT" "$LIVE_ROOT"
rm -rf "$RESULT_ROOT/source_snapshot"
mkdir -p "$SNAPSHOT_ROOT"

PRODUCER_PID_BEFORE=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_BEFORE=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
LEDGER_HASH_BEFORE=$(sha256sum "$LEDGER" | awk '{print $1}')

"$PYTHON_BIN" - "$JOB_STATUS" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps({
    "job": "q4r3_exact25_trade_method_source_capture_audit",
    "state": "RUNNING",
    "current_stage": "capture_and_static_contract_audit",
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "action": "hold"
}, ensure_ascii=False, indent=2), encoding="utf-8")
PY

"$PYTHON_BIN" - "$ROOT" "$CONFIG" "$SNAPSHOT_ROOT" "$REPORT" <<'PY'
from __future__ import annotations

import ast
import hashlib
import json
import py_compile
import re
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

root = Path(sys.argv[1]).resolve()
config_path = Path(sys.argv[2]).resolve()
snapshot_root = Path(sys.argv[3]).resolve()
report_path = Path(sys.argv[4]).resolve()
config = json.loads(config_path.read_text(encoding="utf-8"))

SECRET_ASSIGNMENT = re.compile(
    r"(?im)^\s*[A-Z0-9_]*(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD|PRIVATE[_-]?KEY)[A-Z0-9_]*\s*=\s*['\"]([^'\"]{6,})['\"]"
)
NETWORK_IMPORTS = {"requests", "httpx", "aiohttp", "urllib", "websocket", "websockets"}
NONDETERMINISTIC_IMPORTS = {"random", "secrets"}
CLOCK_CALLS = {"time", "time_ns", "now", "utcnow", "today"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def names_from_target(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        out: list[str] = []
        for item in target.elts:
            out.extend(names_from_target(item))
        return out
    return []


def literal_strings(node: ast.AST) -> set[str]:
    values: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            values.add(child.value)
    return values


def attr_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = attr_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""

files: list[dict[str, Any]] = []
findings: list[dict[str, Any]] = []
all_text = ""
all_literals: set[str] = set()
all_functions: set[str] = set()
all_classes: set[str] = set()
all_assignments: set[str] = set()

for rel in config["source_paths"]:
    source = root / rel
    if not source.is_file():
        findings.append({"severity": "C", "code": "SOURCE_MISSING", "path": rel})
        continue

    text = source.read_text(encoding="utf-8", errors="strict")
    secret_hits = SECRET_ASSIGNMENT.findall(text)
    if secret_hits:
        findings.append({
            "severity": "C",
            "code": "POSSIBLE_EMBEDDED_SECRET",
            "path": rel,
            "count": len(secret_hits),
        })
        continue

    try:
        tree = ast.parse(text, filename=str(source))
        py_compile.compile(str(source), doraise=True)
        syntax_ok = True
        syntax_error = None
    except Exception as exc:
        tree = ast.Module(body=[], type_ignores=[])
        syntax_ok = False
        syntax_error = f"{type(exc).__name__}:{exc}"
        findings.append({"severity": "C", "code": "SYNTAX_OR_COMPILE_ERROR", "path": rel, "detail": syntax_error})

    destination = snapshot_root / source.name
    shutil.copy2(source, destination)

    imports: set[str] = set()
    functions: list[str] = []
    classes: list[str] = []
    assignments: list[str] = []
    decorators: list[str] = []
    top_level_calls: list[str] = []
    clock_calls: list[str] = []
    environment_reads: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
            decorators.extend(attr_name(item) for item in node.decorator_list)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
            decorators.extend(attr_name(item) for item in node.decorator_list)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                assignments.extend(names_from_target(target))
        elif isinstance(node, ast.AnnAssign):
            assignments.extend(names_from_target(node.target))
        elif isinstance(node, ast.Call):
            called = attr_name(node.func)
            if called.split(".")[-1] in CLOCK_CALLS:
                clock_calls.append(called)
            if called in {"os.getenv", "os.environ.get"} or called.endswith(".getenv"):
                environment_reads.append(called)

    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            top_level_calls.append(attr_name(node.value.func))

    literals = literal_strings(tree)
    all_text += "\n" + text.lower()
    all_literals.update(literals)
    all_functions.update(functions)
    all_classes.update(classes)
    all_assignments.update(assignments)

    files.append({
        "path": rel,
        "snapshot_path": str(destination.relative_to(report_path.parents[1])),
        "sha256": sha256(source),
        "bytes": source.stat().st_size,
        "lines": text.count("\n") + 1,
        "syntax_ok": syntax_ok,
        "syntax_error": syntax_error,
        "imports": sorted(imports),
        "functions": sorted(set(functions)),
        "classes": sorted(set(classes)),
        "assignments": sorted(set(assignments)),
        "decorators": sorted(set(filter(None, decorators))),
        "top_level_calls": sorted(set(filter(None, top_level_calls))),
        "clock_calls": sorted(set(clock_calls)),
        "environment_reads": sorted(set(environment_reads)),
        "network_imports": sorted(imports & NETWORK_IMPORTS),
        "nondeterministic_imports": sorted(imports & NONDETERMINISTIC_IMPORTS),
        "possible_secret_count": 0,
    })

families = config["known_method_families"]
subtypes = config["known_method_subtypes"]
family_presence = {name: name.lower() in all_text or name in all_literals for name in families}
subtype_presence = {name: name.lower() in all_text or name in all_literals for name in subtypes}

for name, present in family_presence.items():
    if not present:
        findings.append({"severity": "M", "code": "METHOD_FAMILY_NOT_DECLARED", "value": name})
for name, present in subtype_presence.items():
    if not present:
        findings.append({"severity": "M", "code": "METHOD_SUBTYPE_NOT_DECLARED", "value": name})

capability_coverage: dict[str, dict[str, Any]] = {}
for capability, tokens in config["required_evidence_capabilities"].items():
    hits = sorted(token for token in tokens if token.lower() in all_text)
    capability_coverage[capability] = {
        "tokens": tokens,
        "hits": hits,
        "covered": bool(hits),
        "coverage_pct": round(100.0 * len(hits) / max(len(tokens), 1), 2),
    }
    if not hits:
        findings.append({"severity": "M", "code": "CAPABILITY_NOT_OBSERVED", "capability": capability})

field_presence = {
    field: field.lower() in all_text or field in all_literals or field in all_assignments
    for field in config["required_contract_fields"]
}
for field, present in field_presence.items():
    if not present:
        findings.append({"severity": "M", "code": "CONTRACT_FIELD_NOT_OBSERVED", "field": field})

if any(item["network_imports"] for item in files):
    findings.append({"severity": "M", "code": "NETWORK_DEPENDENCY_IN_RESOLUTION_LAYER"})
if any(item["nondeterministic_imports"] for item in files):
    findings.append({"severity": "M", "code": "NONDETERMINISTIC_RANDOMNESS_IN_RESOLUTION_LAYER"})
if any(item["environment_reads"] for item in files):
    findings.append({"severity": "m", "code": "ENVIRONMENT_DEPENDENT_RESOLUTION_PRESENT"})
if any(item["top_level_calls"] for item in files):
    findings.append({"severity": "m", "code": "TOP_LEVEL_CALLS_REQUIRE_SIDE_EFFECT_REVIEW"})

severity_order = {"C": 3, "M": 2, "m": 1}
max_severity = max((severity_order.get(item.get("severity"), 0) for item in findings), default=0)
state = "CLEAR" if max_severity == 0 else "VIOLATION"
severity = {3: "C", 2: "M", 1: "m"}.get(max_severity)

report = {
    "schema": "q4r3_exact25_trade_method_source_capture_audit_v1",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "state": state,
    "severity": severity,
    "action": "hold",
    "observer_only": True,
    "source_count": len(files),
    "expected_source_count": len(config["source_paths"]),
    "files": files,
    "family_presence": family_presence,
    "subtype_presence": subtype_presence,
    "contract_field_presence": field_presence,
    "capability_coverage": capability_coverage,
    "function_count": len(all_functions),
    "class_count": len(all_classes),
    "assignment_count": len(all_assignments),
    "findings": findings,
    "finding_counts": dict(Counter(item.get("severity") for item in findings)),
    "phase_1_decision": "CAPTURED_FOR_RESEARCH_HARDENING" if len(files) == len(config["source_paths"]) and max_severity < 3 else "BLOCKED_SOURCE_INTEGRITY",
    "next_action": "REVIEW_EXACT_SOURCE_THEN_BUILD_ISOLATED_VNEXT_CANDIDATE",
    "strategy_modified": False,
    "trade_method_modified": False,
    "producer_modified": False,
    "writer_modified": False,
    "formal_ledger_modified": False,
    "paper_enabled": False,
    "live_enabled": False,
    "order_enabled": False,
    "order_authority": "blocked",
    "execution_authority": "none",
}

report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({
    "state": state,
    "severity": severity,
    "source_count": report["source_count"],
    "phase_1_decision": report["phase_1_decision"],
    "finding_counts": report["finding_counts"],
    "next_action": report["next_action"],
}, ensure_ascii=False, sort_keys=True))

if max_severity >= 3:
    raise SystemExit("CRITICAL_SOURCE_INTEGRITY_FINDING")
PY

cp -f "$REPORT" "$LIVE_REPORT.tmp"
mv -f "$LIVE_REPORT.tmp" "$LIVE_REPORT"

PRODUCER_PID_AFTER=$(systemctl show "$PRODUCER_UNIT" -p MainPID --value)
WRITER_PID_AFTER=$(systemctl show "$WRITER_UNIT" -p MainPID --value)
LEDGER_HASH_AFTER=$(sha256sum "$LEDGER" | awk '{print $1}')

[ "$PRODUCER_PID_BEFORE" = "$PRODUCER_PID_AFTER" ] || fail immutability PRODUCER_PID_CHANGED
[ "$WRITER_PID_BEFORE" = "$WRITER_PID_AFTER" ] || fail immutability WRITER_PID_CHANGED
[ "$LEDGER_HASH_BEFORE" = "$LEDGER_HASH_AFTER" ] || fail immutability FORMAL_LEDGER_HASH_CHANGED

cd "$WORKTREE"
git add runtime_results/q4r3/exact25_trade_method_source_capture_audit
if ! git diff --cached --quiet; then
  git -c user.name="Q4R3 Exact25 Audit" -c user.email="q4r3-audit@localhost" \
    commit -m "Capture and audit Exact25 trade-method core sources"
  git push origin HEAD:"$BRANCH"
fi
REPORT_COMMIT=$(git rev-parse HEAD)

"$PYTHON_BIN" - "$JOB_STATUS" "$REPORT" "$REPORT_COMMIT" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
job_path = Path(sys.argv[1])
report = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
payload = {
    "job": "q4r3_exact25_trade_method_source_capture_audit",
    "state": "PASS",
    "current_stage": "complete",
    "status": "PASS_Q4R3_EXACT25_TRADE_METHOD_SOURCE_CAPTURE_AUDIT",
    "verdict": report.get("phase_1_decision"),
    "observer_state": report.get("state"),
    "violation_severity": report.get("severity"),
    "source_count": report.get("source_count"),
    "finding_counts": report.get("finding_counts"),
    "report_commit": sys.argv[3],
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "producer_pid_unchanged": True,
    "writer_pid_unchanged": True,
    "formal_ledger_hash_unchanged": True,
    "strategy_modified": False,
    "trade_method_modified": False,
    "producer_modified": False,
    "writer_modified": False,
    "formal_ledger_modified": False,
    "paper_enabled": False,
    "live_enabled": False,
    "order_enabled": False,
    "order_authority": "blocked",
    "execution_authority": "none",
    "action": "hold",
}
job_path.parent.mkdir(parents=True, exist_ok=True)
job_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY

echo "Q4R3_EXACT25_TRADE_METHOD_SOURCE_CAPTURE_AUDIT_PASS commit=$REPORT_COMMIT"
