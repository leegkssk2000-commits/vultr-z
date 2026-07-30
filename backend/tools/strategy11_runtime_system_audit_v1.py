from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "strategy11_runtime_system_audit_v1"
SKIP_PARTS = {".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv"}
TEXT_SUFFIXES = {".py", ".json", ".yml", ".yaml", ".md", ".txt", ".toml", ".ini", ".cfg", ".service", ".timer", ".sh", ".js", ".ts", ".tsx"}
METRIC_KEYS = {
    "win_rate_pct", "profit_factor", "payoff", "net_after_cost_r", "net_r", "pnl_r",
    "total_net_r", "max_drawdown_r", "max_drawdown_pct", "trades", "trade_count",
    "closed", "closed_count", "retention_pct", "worst_loss_r", "avg_loss_r",
}


@dataclass(frozen=True)
class TextFile:
    path: Path
    rel: str
    text: str


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def eligible(path: Path) -> bool:
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return False
    return not any(part in SKIP_PARTS for part in rel.parts)


def load_text_files() -> tuple[list[TextFile], list[dict[str, str]]]:
    rows: list[TextFile] = []
    decode_errors: list[dict[str, str]] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or not eligible(path) or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel = path.relative_to(ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            decode_errors.append({"path": rel, "error": str(exc)})
            continue
        rows.append(TextFile(path=path, rel=rel, text=text))
    return rows, decode_errors


def python_integrity(files: Iterable[TextFile]) -> tuple[list[dict[str, Any]], dict[str, ast.Module]]:
    errors: list[dict[str, Any]] = []
    trees: dict[str, ast.Module] = {}
    for row in files:
        if row.path.suffix != ".py":
            continue
        try:
            trees[row.rel] = ast.parse(row.text, filename=row.rel)
        except SyntaxError as exc:
            errors.append({"path": row.rel, "line": exc.lineno, "offset": exc.offset, "error": exc.msg})
    return errors, trees


def json_integrity(files: Iterable[TextFile]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    errors: list[dict[str, str]] = []
    documents: dict[str, Any] = {}
    for row in files:
        if row.path.suffix != ".json":
            continue
        try:
            documents[row.rel] = json.loads(row.text)
        except json.JSONDecodeError as exc:
            errors.append({"path": row.rel, "error": f"{exc.msg}:{exc.lineno}:{exc.colno}"})
    return errors, documents


def import_targets(tree: ast.Module) -> set[str]:
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            targets.add(node.module)
    return targets


def module_for(rel: str) -> str:
    return Path(rel).with_suffix("").as_posix().replace("/", ".")


def import_integrity(trees: Mapping[str, ast.Module]) -> tuple[list[dict[str, str]], list[list[str]], dict[str, set[str]]]:
    modules = {module_for(rel): rel for rel in trees}
    package_paths: set[str] = set()
    backend = ROOT / "backend"
    if backend.exists():
        for path in backend.rglob("*"):
            if path.is_dir() and eligible(path):
                package_paths.add(path.relative_to(ROOT).as_posix().replace("/", "."))
    graph: dict[str, set[str]] = {module: set() for module in modules}
    unresolved: list[dict[str, str]] = []
    for module, rel in modules.items():
        for target in sorted(import_targets(trees[rel])):
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


def runtime_named_files(files: Iterable[TextFile]) -> list[TextFile]:
    return [row for row in files if any("runtime" in part.lower() for part in Path(row.rel).parts)]


def token_references(target: TextFile, files: Iterable[TextFile]) -> list[dict[str, Any]]:
    tokens = [target.rel, target.path.name, target.path.stem, module_for(target.rel)]
    hits: list[dict[str, Any]] = []
    for row in files:
        if row.rel == target.rel:
            continue
        matched = sorted({token for token in tokens if token and token in row.text})
        if matched:
            hits.append({"path": row.rel, "tokens": matched})
    return hits


def python_wrapper_target(row: TextFile, tree: ast.Module | None) -> str | None:
    if tree is None or len(row.text.splitlines()) > 60:
        return None
    imports: list[str] = []
    substantive = 0
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, (ast.Expr, ast.Assign, ast.AnnAssign, ast.If)):
            continue
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            substantive += 1
    if substantive == 0 and imports:
        runtime_imports = [name for name in imports if "runtime" in name.lower()]
        return sorted(runtime_imports)[0] if runtime_imports else sorted(imports)[0]
    return None


def writer_references(target: TextFile, files: Iterable[TextFile]) -> list[dict[str, Any]]:
    tokens = [target.rel, target.path.name, target.path.stem]
    write_marker = re.compile(r"write_text|write_bytes|open\s*\([^\n]*(?:['\"]w|['\"]a)|replace\s*\(|rename\s*\(|unlink\s*\(")
    rows: list[dict[str, Any]] = []
    for row in files:
        if not any(token in row.text for token in tokens):
            continue
        lines = []
        for index, line in enumerate(row.text.splitlines(), start=1):
            if any(token in line for token in tokens) and write_marker.search(line):
                lines.append(index)
        if lines:
            rows.append({"path": row.rel, "lines": lines})
    return rows


def runtime_audit(files: list[TextFile], trees: Mapping[str, ast.Module]) -> dict[str, Any]:
    runtime = runtime_named_files(files)
    by_sha: defaultdict[str, list[str]] = defaultdict(list)
    by_json_sha: defaultdict[str, list[str]] = defaultdict(list)
    for row in runtime:
        by_sha[file_sha(row.path)].append(row.rel)
        if row.path.suffix == ".json":
            try:
                by_json_sha[canonical_sha(json.loads(row.text))].append(row.rel)
            except json.JSONDecodeError:
                pass

    exact_groups = [sorted(paths) for paths in by_sha.values() if len(paths) > 1]
    canonical_json_groups = [sorted(paths) for paths in by_json_sha.values() if len(paths) > 1]
    exact_members = {path for group in exact_groups for path in group}
    rows: list[dict[str, Any]] = []
    for row in runtime:
        refs = token_references(row, files)
        writers = writer_references(row, files)
        workflow_refs = [ref for ref in refs if ref["path"].startswith(".github/workflows/")]
        wrapper = python_wrapper_target(row, trees.get(row.rel)) if row.path.suffix == ".py" else None
        if row.rel in exact_members:
            disposition = "EXACT_DUPLICATE_GROUP"
        elif wrapper:
            disposition = "COMPATIBILITY_WRAPPER"
        elif workflow_refs or writers or refs:
            disposition = "ACTIVE_REFERENCED"
        else:
            disposition = "UNREFERENCED_REVIEW"
        rows.append({
            "path": row.rel,
            "suffix": row.path.suffix,
            "bytes": row.path.stat().st_size,
            "sha256": file_sha(row.path),
            "line_count": len(row.text.splitlines()),
            "reference_count": len(refs),
            "workflow_reference_count": len(workflow_refs),
            "writer_count": len(writers),
            "wrapper_target": wrapper,
            "disposition": disposition,
            "references": refs[:30],
            "writers": writers[:20],
        })
    return {
        "runtime_file_count": len(rows),
        "exact_duplicate_group_count": len(exact_groups),
        "canonical_json_duplicate_group_count": len(canonical_json_groups),
        "unreferenced_review_count": sum(row["disposition"] == "UNREFERENCED_REVIEW" for row in rows),
        "compatibility_wrapper_count": sum(row["disposition"] == "COMPATIBILITY_WRAPPER" for row in rows),
        "writer_bound_file_count": sum(row["writer_count"] > 0 for row in rows),
        "exact_duplicate_groups": exact_groups,
        "canonical_json_duplicate_groups": canonical_json_groups,
        "files": sorted(rows, key=lambda item: (item["disposition"], item["path"])),
    }


def walk_objects(value: Any, path: str = "$") -> Iterable[tuple[str, Mapping[str, Any]]]:
    if isinstance(value, Mapping):
        yield path, value
        for key, child in value.items():
            yield from walk_objects(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_objects(child, f"{path}[{index}]")


def bool_signal(document: Any, key: str) -> bool | None:
    values: list[bool] = []
    for _, obj in walk_objects(document):
        value = obj.get(key)
        if isinstance(value, bool):
            values.append(value)
    if not values:
        return None
    return any(values)


def strategy_evidence(documents: Mapping[str, Any]) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    for rel, document in documents.items():
        if "strategy11" not in rel.lower() and "shadow" not in rel.lower() and "pnl" not in rel.lower():
            continue
        fixture_path = "fixture" in rel.lower()
        fixture_flag = bool_signal(document, "fixture_only")
        production_flag = bool_signal(document, "production_authority")
        runtime_flag = bool_signal(document, "runtime_bound")
        for object_path, obj in walk_objects(document):
            metrics = {key: obj[key] for key in sorted(METRIC_KEYS.intersection(obj)) if isinstance(obj[key], (int, float)) and not isinstance(obj[key], bool)}
            if len(metrics) < 2:
                continue
            source_fields = {key: obj.get(key) for key in ("run_id", "data_sha", "window_sha", "source_manifest_sha", "artifact_sha", "state") if obj.get(key) is not None}
            evidence_class = "FIXTURE_OR_SYNTHETIC" if fixture_path or fixture_flag is True else "UNVERIFIED_STATIC_EVIDENCE"
            if fixture_flag is False and source_fields and production_flag is not True:
                evidence_class = "SOURCE_BOUND_RESEARCH_CANDIDATE"
            evidence.append({
                "path": rel,
                "object_path": object_path,
                "evidence_class": evidence_class,
                "fixture_only": fixture_flag,
                "production_authority": production_flag,
                "runtime_bound": runtime_flag,
                "metrics": metrics,
                "source_fields": source_fields,
            })
    counts = Counter(row["evidence_class"] for row in evidence)
    actual = [row for row in evidence if row["evidence_class"] == "SOURCE_BOUND_RESEARCH_CANDIDATE"]
    fixture = [row for row in evidence if row["evidence_class"] == "FIXTURE_OR_SYNTHETIC"]
    return {
        "evidence_count": len(evidence),
        "class_counts": dict(sorted(counts.items())),
        "source_bound_candidate_count": len(actual),
        "fixture_or_synthetic_count": len(fixture),
        "source_bound_candidates": actual[:100],
        "fixture_examples": fixture[:30],
    }


def workflow_integrity(files: Iterable[TextFile]) -> dict[str, Any]:
    workflows = [row for row in files if row.rel.startswith(".github/workflows/") and row.path.suffix in {".yml", ".yaml"}]
    names: defaultdict[str, list[str]] = defaultdict(list)
    missing_permissions: list[str] = []
    missing_concurrency: list[str] = []
    write_permissions: list[dict[str, Any]] = []
    for row in workflows:
        match = re.search(r"(?m)^name:\s*(.+?)\s*$", row.text)
        if match:
            names[match.group(1).strip()].append(row.rel)
        if not re.search(r"(?m)^permissions:\s*$", row.text):
            missing_permissions.append(row.rel)
        if not re.search(r"(?m)^concurrency:\s*$", row.text):
            missing_concurrency.append(row.rel)
        writes = sorted(set(re.findall(r"(?m)^\s+([a-z-]+):\s*write\s*$", row.text)))
        if writes:
            write_permissions.append({"path": row.rel, "permissions": writes})
    return {
        "workflow_count": len(workflows),
        "duplicate_name_groups": [sorted(paths) for paths in names.values() if len(paths) > 1],
        "missing_permissions": sorted(missing_permissions),
        "missing_concurrency": sorted(missing_concurrency),
        "write_permissions": write_permissions,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    files, decode_errors = load_text_files()
    syntax_errors, trees = python_integrity(files)
    json_errors, documents = json_integrity(files)
    unresolved_imports, import_cycles, _ = import_integrity(trees)
    runtime = runtime_audit(files, trees)
    performance = strategy_evidence(documents)
    workflows = workflow_integrity(files)

    critical_count = len(syntax_errors) + len(json_errors) + len(unresolved_imports) + len(import_cycles)
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
    report = {
        "schema_version": "strategy11.runtime_system_audit.v1",
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
    report["report_sha"] = canonical_sha(report)
    (OUT / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "summary.json").write_text(json.dumps({**summary, "report_sha": report["report_sha"]}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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


if __name__ == "__main__":
    raise SystemExit(main())
