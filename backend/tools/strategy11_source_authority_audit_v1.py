from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "strategy11_source_authority_audit_v1"
TEXT_SUFFIXES = {".py", ".yml", ".yaml", ".json", ".md", ".txt", ".toml"}

TARGETS = (
    "backend/research/strategy11_ml_light_observer_optimized_v1.py",
    "backend/research/strategy11_post_shadow_observer_gate_v1_1.py",
    "backend/research/strategy11_pre_shadow_path_optimize_planner_v1_1.py",
    "backend/research/strategy11_pre_shadow_path_optimize_planner_v1_2.py",
    "backend/tools/r7a4d_strategy11_generation7_quota_state_machine_v1_1.py",
    "backend/tools/r7a4d_strategy11_ml_failure_observers_optimized_fixture_v1.py",
    "backend/tools/r7a4d_strategy11_path_candidate_replay_v1_1.py",
    "backend/tools/r7a4d_strategy11_path_state_source_restore_v1_1.py",
    "backend/tools/r7a4d_strategy11_synthesis_portfolio_integration_fixture_v1_1.py",
    "backend/tools/r7a4d_strategy11_trade_path_causal_loop_fixture_v1_1.py",
)


@dataclass(frozen=True)
class SourceFile:
    path: Path
    rel: str
    text: str
    sha256: str
    tree: ast.Module | None


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_text_files() -> list[SourceFile]:
    rows: list[SourceFile] = []
    excluded = {".git", "artifacts", "node_modules", ".venv", "venv", "dist", "build"}
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in excluded for part in path.relative_to(ROOT).parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        tree = None
        if path.suffix == ".py":
            try:
                tree = ast.parse(text, filename=rel)
            except SyntaxError:
                tree = None
        rows.append(SourceFile(path, rel, text, sha256_text(text), tree))
    return rows


def canonical_candidate(target: str) -> str | None:
    path = Path(target)
    name = path.name
    if "_optimized_" in name:
        candidate = name.replace("_optimized_", "_")
        return path.with_name(candidate).as_posix()
    match = re.match(r"^(.*_v\d+)_\d+(\.py)$", name)
    if match:
        return path.with_name(match.group(1) + match.group(2)).as_posix()
    return None


def family_key(target: str) -> str:
    name = Path(target).stem
    name = name.replace("_optimized_", "_")
    name = re.sub(r"(_v\d+)_\d+$", r"\1", name)
    return name


def exported_symbols(file: SourceFile | None) -> list[str]:
    if file is None or file.tree is None:
        return []
    result = []
    for node in file.tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
            result.append(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            else:
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    result.append(target.id)
    return sorted(set(result))


def import_targets(file: SourceFile | None) -> list[str]:
    if file is None or file.tree is None:
        return []
    result: set[str] = set()
    for node in ast.walk(file.tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
            result.update(f"{node.module}.{alias.name}" for alias in node.names if alias.name != "*")
    return sorted(result)


def normalized_ast_sha(file: SourceFile | None) -> str | None:
    if file is None or file.tree is None:
        return None
    return sha256_text(ast.dump(file.tree, include_attributes=False))


def token_references(files: Iterable[SourceFile], target: str) -> list[dict[str, Any]]:
    path_token = target
    module_token = target[:-3].replace("/", ".")
    stem_token = Path(target).stem
    audit_rel = Path(__file__).resolve().relative_to(ROOT).as_posix()
    token_specs = (
        ("path_hits", path_token, r"A-Za-z0-9_./-"),
        ("module_hits", module_token, r"A-Za-z0-9_."),
        ("stem_hits", stem_token, r"A-Za-z0-9_"),
    )
    result = []
    for file in files:
        if file.rel in {target, audit_rel}:
            continue
        accepted: list[tuple[int, int, str]] = []
        for kind, token, boundary in token_specs:
            pattern = re.compile(rf"(?<![{boundary}]){re.escape(token)}(?![{boundary}])")
            for match in pattern.finditer(file.text):
                span = match.span()
                if any(not (span[1] <= start or span[0] >= end) for start, end, _ in accepted):
                    continue
                accepted.append((span[0], span[1], kind))
        if not accepted:
            continue
        counts = {kind: sum(row[2] == kind for row in accepted) for kind, _, _ in token_specs}
        result.append(
            {
                "path": file.rel,
                "total_hits": len(accepted),
                **counts,
                "is_workflow": file.rel.startswith(".github/workflows/"),
                "is_python": file.rel.endswith(".py"),
            }
        )
    return sorted(result, key=lambda row: (-row["total_hits"], row["path"]))

def similarity(left: SourceFile | None, right: SourceFile | None) -> dict[str, Any]:
    if left is None or right is None:
        return {"available": False}
    left_lines = {line.strip() for line in left.text.splitlines() if line.strip()}
    right_lines = {line.strip() for line in right.text.splitlines() if line.strip()}
    union = left_lines | right_lines
    jaccard = len(left_lines & right_lines) / max(len(union), 1)
    return {
        "available": True,
        "byte_equal": left.sha256 == right.sha256,
        "normalized_ast_equal": normalized_ast_sha(left) == normalized_ast_sha(right),
        "line_jaccard": round(jaccard, 6),
        "target_line_count": len(left.text.splitlines()),
        "candidate_line_count": len(right.text.splitlines()),
        "target_exports": exported_symbols(left),
        "candidate_exports": exported_symbols(right),
        "target_imports": import_targets(left),
        "candidate_imports": import_targets(right),
    }


def classify(row: dict[str, Any]) -> tuple[str, list[str]]:
    refs = row["target_references"]
    workflow_refs = [ref for ref in refs if ref["is_workflow"]]
    python_refs = [ref for ref in refs if ref["is_python"]]
    candidate_exists = row["canonical_candidate_exists"]
    sim = row["similarity"]
    reasons: list[str] = []

    if not refs:
        reasons.append("TARGET_UNREFERENCED")
        if candidate_exists:
            return "DELETE_CANDIDATE_AFTER_FIXTURE_VERIFY", reasons
        return "RENAME_CANDIDATE", reasons

    if workflow_refs:
        reasons.append("WORKFLOW_DIRECT_REFERENCE")
    if python_refs:
        reasons.append("PYTHON_DIRECT_REFERENCE")
    if candidate_exists and sim.get("byte_equal"):
        reasons.append("CANONICAL_BYTE_DUPLICATE")
        return "MIGRATE_REFERENCES_THEN_DELETE", reasons
    if candidate_exists and sim.get("normalized_ast_equal"):
        reasons.append("CANONICAL_AST_DUPLICATE")
        return "MIGRATE_REFERENCES_THEN_DELETE", reasons
    if "optimized" in row["target"]:
        reasons.append("OPTIMIZED_VARIANT_MAY_BE_CURRENT_AUTHORITY")
        return "PROMOTE_OPTIMIZED_TO_CANONICAL_WITH_COMPAT_SHIM", reasons
    if candidate_exists:
        reasons.append("PARALLEL_NONIDENTICAL_CANONICAL_EXISTS")
        return "MANUAL_AUTHORITY_DECISION_REQUIRED", reasons
    return "RENAME_WITH_REFERENCE_MIGRATION", reasons


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    files = load_text_files()
    by_path = {file.rel: file for file in files}
    rows = []
    for target in TARGETS:
        source = by_path.get(target)
        candidate = canonical_candidate(target)
        candidate_source = by_path.get(candidate) if candidate else None
        row = {
            "target": target,
            "exists": source is not None,
            "target_sha256": source.sha256 if source else None,
            "family_key": family_key(target),
            "canonical_candidate": candidate,
            "canonical_candidate_exists": candidate_source is not None,
            "canonical_candidate_sha256": candidate_source.sha256 if candidate_source else None,
            "target_references": token_references(files, target),
            "canonical_references": token_references(files, candidate) if candidate else [],
            "similarity": similarity(source, candidate_source),
        }
        disposition, reasons = classify(row)
        row["disposition"] = disposition
        row["reasons"] = reasons
        rows.append(row)

    families: dict[str, list[str]] = {}
    for row in rows:
        families.setdefault(row["family_key"], []).append(row["target"])
    summary = {
        "target_count": len(rows),
        "existing_target_count": sum(row["exists"] for row in rows),
        "referenced_target_count": sum(bool(row["target_references"]) for row in rows),
        "workflow_referenced_target_count": sum(any(ref["is_workflow"] for ref in row["target_references"]) for row in rows),
        "canonical_candidate_exists_count": sum(row["canonical_candidate_exists"] for row in rows),
        "disposition_counts": {
            disposition: sum(row["disposition"] == disposition for row in rows)
            for disposition in sorted({row["disposition"] for row in rows})
        },
    }
    report = {
        "schema_version": "strategy11.source_authority_audit.v1",
        "state": "PASS_SOURCE_AUTHORITY_AUDIT",
        "summary": summary,
        "families": {key: sorted(value) for key, value in sorted(families.items())},
        "rows": rows,
        "safety": {
            "read_only": True,
            "runtime_bound": False,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
            "protected_mutations": 0,
        },
    }
    report["report_sha"] = canonical_json_sha(report)
    (OUT / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    for row in rows:
        print(
            "|".join(
                [
                    row["disposition"],
                    row["target"],
                    f"refs={len(row['target_references'])}",
                    f"canonical={row['canonical_candidate']}",
                    f"canonical_exists={row['canonical_candidate_exists']}",
                    f"jaccard={row['similarity'].get('line_jaccard')}",
                ]
            )
        )
    print(f"REPORT_SHA={report['report_sha']}")
    if summary["existing_target_count"] != summary["target_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
