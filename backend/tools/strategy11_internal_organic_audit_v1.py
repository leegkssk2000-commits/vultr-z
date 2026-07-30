from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "strategy11_internal_organic_audit_v1"
PY_ROOTS = (ROOT / "backend" / "contracts", ROOT / "backend" / "research", ROOT / "backend" / "tools")
WORKFLOW_ROOT = ROOT / ".github" / "workflows"

SAFETY_EXPECTED = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}

PIPELINE = (
    "backend.research.strategy11_synthesis_material_registry_v1",
    "backend.research.strategy11_bounded_synthesis_constructor_v1",
    "backend.research.strategy11_synthesis_factorial_replay_v1",
    "backend.research.strategy11_component_attribution_v1",
    "backend.research.strategy11_synthesis_sealer_v1",
    "backend.research.strategy11_synthesis_classifier_adapter_v1",
    "backend.research.strategy11_synthesis_portfolio_integration_v1",
    "backend.research.strategy11_shadow20_readonly_canary_v1",
    "backend.research.strategy11_shadow200_readonly_accumulator_v1",
    "backend.research.strategy11_shadow300_readonly_completion_v1",
    "backend.research.strategy11_post_shadow_observer_gate_v1",
)


@dataclass(frozen=True)
class PyFile:
    path: Path
    rel: str
    module: str
    text: str
    tree: ast.Module


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def module_name(path: Path) -> str:
    return path.relative_to(ROOT).with_suffix("").as_posix().replace("/", ".")


def load_python() -> tuple[list[PyFile], list[dict[str, str]]]:
    files: list[PyFile] = []
    syntax_errors: list[dict[str, str]] = []
    for base in PY_ROOTS:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            text = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(text, filename=rel)
            except SyntaxError as exc:
                syntax_errors.append({"path": rel, "error": f"{exc.msg}:{exc.lineno}:{exc.offset}"})
                continue
            files.append(PyFile(path, rel, module_name(path), text, tree))
    return files, syntax_errors


def imports_for(file: PyFile) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(file.tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def internal_target(name: str, modules: set[str]) -> str | None:
    if name in modules:
        return name
    parts = name.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in modules:
            return candidate
        parts.pop()
    return None


def import_graph(files: list[PyFile]) -> tuple[dict[str, set[str]], list[dict[str, str]]]:
    modules = {file.module for file in files}
    graph: dict[str, set[str]] = {file.module: set() for file in files}
    unresolved: list[dict[str, str]] = []
    for file in files:
        for imported in sorted(imports_for(file)):
            if not imported.startswith("backend."):
                continue
            target = internal_target(imported, modules)
            if target:
                graph[file.module].add(target)
            else:
                unresolved.append({"path": file.rel, "import": imported})
    return graph, unresolved


def strongly_connected(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        low[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for nxt in graph.get(node, set()):
            if nxt not in indices:
                visit(nxt)
                low[node] = min(low[node], low[nxt])
            elif nxt in on_stack:
                low[node] = min(low[node], indices[nxt])
        if low[node] == indices[node]:
            component: list[str] = []
            while True:
                child = stack.pop()
                on_stack.remove(child)
                component.append(child)
                if child == node:
                    break
            if len(component) > 1:
                components.append(sorted(component))

    for node in graph:
        if node not in indices:
            visit(node)
    return sorted(components)


def normalized_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    clone = ast.parse(ast.unparse(node)).body[0]
    assert isinstance(clone, (ast.FunctionDef, ast.AsyncFunctionDef))
    clone.name = "_"
    return ast.dump(clone, include_attributes=False)


def function_inventory(files: list[PyFile]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    functions: list[dict[str, Any]] = []
    duplicate_map: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for file in files:
        for node in file.tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            end = getattr(node, "end_lineno", node.lineno)
            loc = end - node.lineno + 1
            branches = sum(
                isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.Match, ast.BoolOp, ast.IfExp))
                for child in ast.walk(node)
            )
            row = {"path": file.rel, "function": node.name, "loc": loc, "branch_points": branches, "line": node.lineno}
            functions.append(row)
            if loc >= 4:
                duplicate_map[canonical_sha(normalized_function(node))].append(row)
    hotspots = sorted(
        [row for row in functions if row["loc"] >= 80 or row["branch_points"] >= 18],
        key=lambda row: (-row["loc"], -row["branch_points"], row["path"], row["function"]),
    )
    duplicates = sorted(
        [
            {"fingerprint": fingerprint, "copies": rows, "copy_count": len(rows)}
            for fingerprint, rows in duplicate_map.items()
            if len({row["path"] for row in rows}) > 1
        ],
        key=lambda row: (-row["copy_count"], row["fingerprint"]),
    )
    return hotspots, duplicates


def literal_dict(node: ast.AST) -> dict[str, Any] | None:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return None
    return value if isinstance(value, dict) else None


def safety_audit(files: list[PyFile]) -> dict[str, Any]:
    definitions: list[dict[str, Any]] = []
    partial: list[dict[str, Any]] = []
    for file in files:
        if "strategy11" not in file.rel:
            continue
        for node in file.tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets: list[str] = []
            value_node: ast.AST | None = None
            if isinstance(node, ast.Assign):
                targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
                value_node = node.value
            else:
                if isinstance(node.target, ast.Name):
                    targets = [node.target.id]
                value_node = node.value
            if not targets or value_node is None or not any("SAFETY" in name for name in targets):
                continue
            value = literal_dict(value_node)
            if value is None:
                continue
            row = {"path": file.rel, "names": targets, "value": value}
            definitions.append(row)
            mismatch = sorted(key for key, expected in SAFETY_EXPECTED.items() if value.get(key) != expected)
            if mismatch:
                partial.append({**row, "mismatch_keys": mismatch})
    fingerprints = Counter(canonical_sha(row["value"]) for row in definitions)
    return {
        "definition_count": len(definitions),
        "distinct_literal_count": len(fingerprints),
        "partial_or_mismatched": partial,
        "duplicate_literal_groups": sorted(fingerprints.values(), reverse=True),
    }


def workflow_refs() -> tuple[dict[str, set[str]], list[dict[str, Any]], list[dict[str, Any]]]:
    refs: dict[str, set[str]] = defaultdict(set)
    workflows: list[dict[str, Any]] = []
    schedule_map: defaultdict[str, list[str]] = defaultdict(list)
    if not WORKFLOW_ROOT.exists():
        return refs, workflows, []
    path_re = re.compile(r"(?:python\s+|-m\s+)(backend/[A-Za-z0-9_./-]+\.py)")
    cron_re = re.compile(r"cron:\s*['\"]([^'\"]+)['\"]")
    for path in sorted(WORKFLOW_ROOT.glob("*.y*ml")):
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for match in path_re.finditer(text):
            refs[match.group(1)].add(rel)
        crons = cron_re.findall(text)
        for cron in crons:
            schedule_map[cron].append(rel)
        workflows.append(
            {
                "path": rel,
                "has_concurrency": bool(re.search(r"(?m)^concurrency:", text)),
                "has_permissions": bool(re.search(r"(?m)^permissions:", text)),
                "write_permissions": sorted(set(re.findall(r"(?m)^\s+([a-z-]+):\s*write\s*$", text))),
                "cron": crons,
                "python_refs": sorted(set(path_re.findall(text))),
                "line_count": len(text.splitlines()),
            }
        )
    collisions = [
        {"cron": cron, "workflows": sorted(paths), "count": len(paths)}
        for cron, paths in schedule_map.items()
        if len(paths) > 1
    ]
    return refs, workflows, sorted(collisions, key=lambda row: (-row["count"], row["cron"]))


def dead_candidates(files: list[PyFile], graph: dict[str, set[str]], workflow_file_refs: dict[str, set[str]]) -> list[dict[str, Any]]:
    inbound: Counter[str] = Counter()
    for targets in graph.values():
        inbound.update(targets)
    result: list[dict[str, Any]] = []
    for file in files:
        if "strategy11" not in file.rel:
            continue
        is_tool = file.rel.startswith("backend/tools/")
        referenced_by_workflow = file.rel in workflow_file_refs
        has_main = any(isinstance(node, ast.If) and "__main__" in ast.unparse(node.test) for node in file.tree.body)
        if inbound[file.module] == 0 and not referenced_by_workflow and not (is_tool and has_main):
            result.append({"path": file.rel, "module": file.module, "reason": "NO_INTERNAL_IMPORT_OR_WORKFLOW_REFERENCE"})
    return sorted(result, key=lambda row: row["path"])


def naming_anomalies(files: list[PyFile]) -> list[dict[str, str]]:
    anomalies: list[dict[str, str]] = []
    for file in files:
        name = file.path.name
        if re.search(r"_v\d+_\d+\.py$", name):
            anomalies.append({"path": file.rel, "reason": "DOUBLE_VERSION_SUFFIX"})
        if "optimized" in name:
            anomalies.append({"path": file.rel, "reason": "PARALLEL_OPTIMIZED_IMPLEMENTATION"})
        if re.search(r"(?:copy|backup|old|legacy|tmp)", name, re.IGNORECASE):
            anomalies.append({"path": file.rel, "reason": "POSSIBLE_RESIDUAL_NAME"})
    return anomalies


def pipeline_audit(files: list[PyFile], graph: dict[str, set[str]]) -> dict[str, Any]:
    modules = {file.module for file in files}
    missing = [module for module in PIPELINE if module not in modules]
    edges: list[dict[str, Any]] = []
    for upstream, downstream in zip(PIPELINE, PIPELINE[1:]):
        direct = upstream in graph.get(downstream, set()) or downstream in graph.get(upstream, set())
        edges.append({"upstream": upstream, "downstream": downstream, "direct_import_edge": direct})
    return {
        "stage_count": len(PIPELINE),
        "missing_stages": missing,
        "direct_edges": edges,
        "disconnected_direct_edges": [row for row in edges if not row["direct_import_edge"]],
        "note": "A missing direct import can be intentional when sealed artifacts are passed by an orchestrator.",
    }


def module_stats(files: list[PyFile], graph: dict[str, set[str]]) -> list[dict[str, Any]]:
    inbound: Counter[str] = Counter()
    for targets in graph.values():
        inbound.update(targets)
    rows = []
    for file in files:
        rows.append(
            {
                "path": file.rel,
                "module": file.module,
                "loc": len(file.text.splitlines()),
                "functions": sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in file.tree.body),
                "classes": sum(isinstance(node, ast.ClassDef) for node in file.tree.body),
                "internal_import_out": len(graph.get(file.module, set())),
                "internal_import_in": inbound[file.module],
            }
        )
    return sorted(rows, key=lambda row: (-row["loc"], row["path"]))


def markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Strategy11 Internal Organic Audit V1",
        "",
        f"- state: `{summary['state']}`",
        f"- python files: {summary['python_file_count']}",
        f"- workflows: {summary['workflow_count']}",
        f"- syntax errors: {summary['syntax_error_count']}",
        f"- unresolved internal imports: {summary['unresolved_internal_import_count']}",
        f"- import cycles: {summary['import_cycle_count']}",
        f"- safety mismatches: {summary['safety_mismatch_count']}",
        f"- naming anomalies: {summary['naming_anomaly_count']}",
        f"- dead candidates: {summary['dead_candidate_count']}",
        f"- large/complex functions: {summary['hotspot_count']}",
        f"- duplicate helper groups: {summary['duplicate_function_group_count']}",
        f"- schedule collisions: {summary['schedule_collision_count']}",
        "",
        "## Priority findings",
    ]
    for row in report["priority_findings"]:
        lines.append(f"- **{row['severity']} {row['code']}** — {row['detail']}")
    lines.extend(
        [
            "",
            "## Pipeline",
            f"- missing stages: {report['pipeline']['missing_stages']}",
            f"- disconnected direct edges: {len(report['pipeline']['disconnected_direct_edges'])}",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    files, syntax_errors = load_python()
    graph, unresolved = import_graph(files)
    cycles = strongly_connected(graph)
    hotspots, duplicate_functions = function_inventory(files)
    safety = safety_audit(files)
    workflow_file_refs, workflows, schedule_collisions = workflow_refs()
    dead = dead_candidates(files, graph, workflow_file_refs)
    names = naming_anomalies(files)
    pipeline = pipeline_audit(files, graph)
    stats = module_stats(files, graph)

    priority: list[dict[str, str]] = []
    if syntax_errors:
        priority.append({"severity": "C", "code": "PYTHON_SYNTAX_ERROR", "detail": f"{len(syntax_errors)} files"})
    if unresolved:
        priority.append({"severity": "C", "code": "UNRESOLVED_INTERNAL_IMPORT", "detail": f"{len(unresolved)} imports"})
    if cycles:
        priority.append({"severity": "M", "code": "IMPORT_CYCLE", "detail": f"{len(cycles)} cycles"})
    if safety["partial_or_mismatched"]:
        priority.append({"severity": "C", "code": "SAFETY_CONTRACT_DRIFT", "detail": f"{len(safety['partial_or_mismatched'])} literal blocks"})
    if pipeline["missing_stages"]:
        priority.append({"severity": "C", "code": "PIPELINE_STAGE_MISSING", "detail": ", ".join(pipeline["missing_stages"])})
    if names:
        priority.append({"severity": "m", "code": "NAMING_OR_PARALLEL_IMPL_RESIDUE", "detail": f"{len(names)} files"})
    if dead:
        priority.append({"severity": "m", "code": "POSSIBLE_DEAD_MODULE", "detail": f"{len(dead)} files; manual confirmation required"})
    if hotspots:
        priority.append({"severity": "m", "code": "COMPLEXITY_HOTSPOT", "detail": f"{len(hotspots)} functions"})
    if duplicate_functions:
        priority.append({"severity": "m", "code": "DUPLICATE_HELPER_LOGIC", "detail": f"{len(duplicate_functions)} groups"})
    if schedule_collisions:
        priority.append({"severity": "m", "code": "WORKFLOW_SCHEDULE_COLLISION", "detail": f"{len(schedule_collisions)} cron groups"})
    if not priority:
        priority.append({"severity": "PASS", "code": "NO_STATIC_BLOCKER", "detail": "No static structural blocker detected"})

    critical = any(row["severity"] == "C" for row in priority)
    state = "HOLD_INTERNAL_ORGANIC_AUDIT" if critical else "PASS_INTERNAL_ORGANIC_STATIC_AUDIT"
    report = {
        "schema_version": "strategy11.internal_organic_audit.v1",
        "state": state,
        "authority": SAFETY_EXPECTED,
        "summary": {
            "state": state,
            "python_file_count": len(files),
            "workflow_count": len(workflows),
            "syntax_error_count": len(syntax_errors),
            "unresolved_internal_import_count": len(unresolved),
            "import_cycle_count": len(cycles),
            "safety_mismatch_count": len(safety["partial_or_mismatched"]),
            "naming_anomaly_count": len(names),
            "dead_candidate_count": len(dead),
            "hotspot_count": len(hotspots),
            "duplicate_function_group_count": len(duplicate_functions),
            "schedule_collision_count": len(schedule_collisions),
            "pipeline_missing_stage_count": len(pipeline["missing_stages"]),
        },
        "priority_findings": priority,
        "syntax_errors": syntax_errors,
        "unresolved_internal_imports": unresolved,
        "import_cycles": cycles,
        "safety": safety,
        "naming_anomalies": names,
        "possible_dead_modules": dead,
        "complexity_hotspots": hotspots,
        "duplicate_function_groups": duplicate_functions,
        "workflow_schedule_collisions": schedule_collisions,
        "workflows": workflows,
        "pipeline": pipeline,
        "module_stats": stats,
    }
    report["report_sha"] = canonical_sha(report)
    (OUT / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "report.md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report["summary"], sort_keys=True))
    for row in priority:
        print(f"{row['severity']}|{row['code']}|{row['detail']}")
    print(f"REPORT_SHA={report['report_sha']}")
    return 0 if not syntax_errors and not unresolved and not pipeline["missing_stages"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
