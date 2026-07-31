from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "zel.pipeline_cleanup_audit.v1"
PYTHON_ROOTS = ("backend", "tools", "tests")
WORKFLOW_ROOT = ".github/workflows"
EXECUTION_TOKENS = (
    "place_order(", "execute_order(", "bingx_order", "real_order_enabled = true",
    '"real_order_enabled": true', "'real_order_enabled': true",
)
LEGACY_TERMS = ("legacy", "deprecated", "obsolete", "backup", "archive", "old_", "_old", "v0")
WRITE_HINTS = ("write_text(", "json.dump(", "open(", "atomic_json(", "os.replace(")
ABSOLUTE_JSON_RE = re.compile(r'''["'](/[^"']+(?:latest|status|snapshot|ledger)[^"']*\.json(?:l)?)["']''', re.I)
IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_\.]*)", re.M)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def text_files(root: Path, suffixes: set[str], roots: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for relative in roots:
        base = root / relative
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in suffixes:
                if any(part in {".git", "__pycache__", ".venv", "venv", "node_modules"} for part in path.parts):
                    continue
                files.append(path)
    return sorted(files)


def relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def syntax_findings(root: Path, python_files: list[Path]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in python_files:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            findings.append({"kind": "SYNTAX_ERROR", "severity": "CRITICAL", "path": relative(root, path), "detail": str(exc)[:500]})
    return findings


def workflow_findings(root: Path) -> list[dict[str, Any]]:
    base = root / WORKFLOW_ROOT
    if not base.exists():
        return []
    names: dict[str, list[str]] = defaultdict(list)
    scheduled: dict[str, list[str]] = defaultdict(list)
    findings: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"(?m)^name:\s*(.+?)\s*$", text)
        name = match.group(1).strip().strip("\"'") if match else path.stem
        names[name].append(relative(root, path))
        if re.search(r"(?m)^\s+schedule:\s*$", text):
            scheduled[re.sub(r"\s+", " ", name.upper()).strip()].append(relative(root, path))
    for name, paths in sorted(names.items()):
        if len(paths) > 1:
            findings.append({"kind": "DUPLICATE_WORKFLOW_NAME", "severity": "HIGH", "owner": name, "paths": paths})
    for owner, paths in sorted(scheduled.items()):
        if len(paths) > 1:
            findings.append({"kind": "DUPLICATE_SCHEDULE_OWNER_CANDIDATE", "severity": "HIGH", "owner": owner, "paths": paths})
    return findings


def execution_surface_findings(root: Path, files: list[Path]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in files:
        rel = relative(root, path)
        if rel.startswith("tests/") or "/fixtures/" in rel or rel.endswith("_fixture.py"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        matched = sorted({token for token in EXECUTION_TOKENS if token in text})
        if matched:
            findings.append({
                "kind": "EXECUTION_SURFACE_CANDIDATE", "severity": "REVIEW", "path": rel,
                "tokens": matched, "automatic_delete_allowed": False,
            })
    return findings


def writer_findings(root: Path, files: list[Path]) -> list[dict[str, Any]]:
    owners: dict[str, set[str]] = defaultdict(set)
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        if not any(hint in text for hint in WRITE_HINTS):
            continue
        rel = relative(root, path)
        for target in ABSOLUTE_JSON_RE.findall(text):
            owners[target].add(rel)
    return [
        {"kind": "MULTI_WRITER_PATH_CANDIDATE", "severity": "HIGH", "target": target,
         "paths": sorted(paths), "single_owner_required": True}
        for target, paths in sorted(owners.items()) if len(paths) > 1
    ]


def legacy_findings(root: Path, files: list[Path]) -> list[dict[str, Any]]:
    referenced: Counter[str] = Counter()
    texts: dict[str, str] = {}
    names: dict[str, str] = {}
    for path in files:
        rel = relative(root, path)
        texts[rel] = path.read_text(encoding="utf-8", errors="replace")
        names[rel] = path.name
    for owner, text in texts.items():
        for candidate, name in names.items():
            if candidate != owner and name in text:
                referenced[candidate] += 1
    findings: list[dict[str, Any]] = []
    for path in files:
        rel = relative(root, path)
        if not any(term in rel.lower() for term in LEGACY_TERMS):
            continue
        findings.append({
            "kind": "LEGACY_OR_PROVENANCE_CANDIDATE",
            "severity": "INFO" if referenced[rel] else "REVIEW",
            "path": rel, "reference_count": referenced[rel], "automatic_delete_allowed": False,
        })
    return findings


def import_findings(root: Path, python_files: list[Path]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in python_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for module in IMPORT_RE.findall(text):
            top = module.split(".", 1)[0]
            if top in {"backend", "tools", "tests", "canonical"} and not (root / top).exists():
                findings.append({"kind": "BROKEN_FIRST_PARTY_IMPORT_ROOT", "severity": "CRITICAL", "path": relative(root, path), "module": module})
    return findings


def audit(root: Path) -> dict[str, Any]:
    root = root.resolve()
    python_files = text_files(root, {".py"}, PYTHON_ROOTS)
    scan_files = text_files(root, {".py", ".json", ".yml", ".yaml", ".sh"}, PYTHON_ROOTS + (WORKFLOW_ROOT,))
    findings = (
        syntax_findings(root, python_files) + workflow_findings(root)
        + execution_surface_findings(root, scan_files) + writer_findings(root, scan_files)
        + legacy_findings(root, scan_files) + import_findings(root, python_files)
    )
    counts = Counter(item["kind"] for item in findings)
    critical = sum(1 for item in findings if item["severity"] == "CRITICAL")
    high = sum(1 for item in findings if item["severity"] == "HIGH")
    report = {
        "schema_version": SCHEMA_VERSION,
        "state": "HOLD_CLEANUP_REQUIRED" if critical or high else "PASS_NO_CRITICAL_CLEANUP_FINDING",
        "scan_root": str(root), "python_file_count": len(python_files), "scan_file_count": len(scan_files),
        "finding_count": len(findings), "critical_count": critical, "high_count": high,
        "finding_counts": dict(sorted(counts.items())), "findings": findings,
        "cleanup_policy": {
            "read_only": True, "automatic_delete_allowed": False, "single_cause_before_change": True,
            "backup_and_rollback_required": True, "protected_runtime_mutation_allowed": False,
        },
        "execution_authority": "NONE", "order_authority": "BLOCKED",
    }
    report["report_sha256"] = canonical_sha({k: v for k, v in report.items() if k != "report_sha256"})
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(report["state"])
    print(f"FINDINGS={report['finding_count']}")
    print(f"EVIDENCE={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
