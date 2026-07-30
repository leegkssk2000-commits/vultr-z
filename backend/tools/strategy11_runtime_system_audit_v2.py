from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from backend.tools import strategy11_runtime_system_audit_v1 as v1


# V1 omitted HTML/CSS reference surfaces and included generated artifacts and audit files.
v1.SKIP_PARTS.add("artifacts")
v1.TEXT_SUFFIXES.update({".html", ".css"})


NON_PRODUCTION_RUNTIME_PATHS = {
    "backend/tools/strategy11_runtime_system_audit_v1.py",
    "backend/tools/strategy11_runtime_system_audit_v2.py",
    "backend/tools/strategy11_runtime_import_smoke_v1.py",
}


def runtime_named_files(files: Iterable[v1.TextFile]) -> list[v1.TextFile]:
    allowed_suffixes = {".py", ".js", ".css", ".ts", ".tsx", ".json", ".service", ".timer", ".sh"}
    result: list[v1.TextFile] = []
    for row in files:
        name = row.path.name.lower()
        if "runtime" not in name or row.path.suffix.lower() not in allowed_suffixes:
            continue
        if row.rel.startswith(".github/workflows/"):
            continue
        if row.rel in NON_PRODUCTION_RUNTIME_PATHS:
            continue
        if row.rel.startswith("backend/tools/") and ("fixture" in name or "smoke" in name or "audit" in name):
            continue
        result.append(row)
    return result


def _resolved_import_targets(tree: ast.Module, current_module: str) -> set[str]:
    targets: set[str] = set()
    current_parts = current_module.split(".")
    package = current_parts[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            keep = len(package) - (node.level - 1)
            if keep < 0:
                targets.add("__INVALID_RELATIVE_IMPORT__")
                continue
            base_parts = package[:keep]
            if node.module:
                targets.add(".".join([*base_parts, node.module]))
            else:
                targets.update(".".join([*base_parts, alias.name]) for alias in node.names)
        elif node.module:
            targets.add(node.module)
    return targets


def import_integrity(trees: Mapping[str, ast.Module]) -> tuple[list[dict[str, str]], list[list[str]], dict[str, set[str]]]:
    modules = {v1.module_for(rel): rel for rel in trees}
    package_paths: set[str] = set()
    backend = v1.ROOT / "backend"
    if backend.exists():
        for path in backend.rglob("*"):
            if path.is_dir() and v1.eligible(path):
                package_paths.add(path.relative_to(v1.ROOT).as_posix().replace("/", "."))

    graph: dict[str, set[str]] = {module: set() for module in modules}
    unresolved: list[dict[str, str]] = []
    for module, rel in modules.items():
        for target in sorted(_resolved_import_targets(trees[rel], module)):
            if target == "__INVALID_RELATIVE_IMPORT__":
                unresolved.append({"path": rel, "import": target})
                continue
            if not target.startswith("backend."):
                continue
            if target in modules:
                graph[module].add(target)
            elif target in package_paths:
                continue
            else:
                prefix = next((candidate for candidate in modules if target.startswith(candidate + ".")), None)
                if prefix:
                    graph[module].add(prefix)
                else:
                    unresolved.append({"path": rel, "import": target})

    index = 0
    stack: list[str] = []
    active: set[str] = set()
    indexes: dict[str, int] = {}
    low: dict[str, int] = {}
    cycles: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = low[node] = index
        index += 1
        stack.append(node)
        active.add(node)
        for nxt in graph[node]:
            if nxt not in indexes:
                visit(nxt)
                low[node] = min(low[node], low[nxt])
            elif nxt in active:
                low[node] = min(low[node], indexes[nxt])
        if low[node] != indexes[node]:
            return
        group: list[str] = []
        while True:
            child = stack.pop()
            active.remove(child)
            group.append(child)
            if child == node:
                break
        if len(group) > 1:
            cycles.append(sorted(group))

    for node in graph:
        if node not in indexes:
            visit(node)
    return unresolved, sorted(cycles), graph


def main() -> int:
    v1.OUT.mkdir(parents=True, exist_ok=True)
    files, decode_errors = v1.load_text_files()
    syntax_errors, trees = v1.python_integrity(files)
    json_errors, documents = v1.json_integrity(files)
    unresolved_imports, import_cycles, _ = import_integrity(trees)
    runtime = v1.runtime_audit(files, trees)
    performance = v1.strategy_evidence(documents)
    workflows = v1.workflow_integrity(files)

    critical_count = len(decode_errors) + len(syntax_errors) + len(json_errors) + len(unresolved_imports) + len(import_cycles)
    state = "HOLD_RUNTIME_SYSTEM_AUDIT" if critical_count else "PASS_RUNTIME_SYSTEM_STATIC_AUDIT"
    summary = {
        "state": state,
        "text_file_count": len(files),
        "python_file_count": len(trees),
        "json_document_count": len(documents),
        "decode_error_count": len(decode_errors),
        "syntax_error_count": len(syntax_errors),
        "json_error_count": len(json_errors),
        "unresolved_internal_import_count": len(unresolved_imports),
        "import_cycle_count": len(import_cycles),
        "runtime_file_count": runtime["runtime_file_count"],
        "runtime_exact_duplicate_group_count": runtime["exact_duplicate_group_count"],
        "runtime_unreferenced_review_count": runtime["unreferenced_review_count"],
        "runtime_compatibility_wrapper_count": runtime["compatibility_wrapper_count"],
        "strategy_source_bound_candidate_count": performance["source_bound_candidate_count"],
        "strategy_fixture_or_synthetic_count": performance["fixture_or_synthetic_count"],
        "workflow_duplicate_name_group_count": len(workflows["duplicate_name_groups"]),
    }
    report: dict[str, Any] = {
        "schema_version": "strategy11.runtime_system_audit.v2",
        "state": state,
        "summary": summary,
        "decode_errors": decode_errors,
        "syntax_errors": syntax_errors,
        "json_errors": json_errors,
        "unresolved_internal_imports": unresolved_imports,
        "import_cycles": import_cycles,
        "runtime": runtime,
        "strategy_performance_evidence": performance,
        "workflow_integrity": workflows,
        "authority": {
            "research_only": True,
            "promotion_authority": False,
            "protected_mutations": 0,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
            "runtime_bound": False,
        },
    }
    report["report_sha"] = v1.canonical_sha(report)
    (v1.OUT / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (v1.OUT / "summary.json").write_text(json.dumps({**summary, "report_sha": report["report_sha"]}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    print(json.dumps({
        "runtime_exact_duplicate_groups": runtime["exact_duplicate_groups"],
        "runtime_unreferenced": [row for row in runtime["files"] if row["disposition"] == "UNREFERENCED_REVIEW"],
        "runtime_wrappers": [row for row in runtime["files"] if row["disposition"] == "COMPATIBILITY_WRAPPER"],
        "strategy_class_counts": performance["class_counts"],
        "source_bound_strategy_candidates": performance["source_bound_candidates"][:20],
        "workflow_duplicate_names": workflows["duplicate_name_groups"],
    }, indent=2, sort_keys=True))
    print(f"REPORT_SHA={report['report_sha']}")
    return 1 if critical_count else 0


v1.runtime_named_files = runtime_named_files


if __name__ == "__main__":
    raise SystemExit(main())
