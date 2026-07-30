from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from backend.tools.strategy11_cron_overlap_audit_v1 import find_overlapping_schedules

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

    @property
    def is_fixture(self) -> bool:
        return "fixture" in self.path.name or self.rel.startswith("backend/tools/")


def canonical_sha(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def module_name(path: Path) -> str:
    return path.relative_to(ROOT).with_suffix("").as_posix().replace("/", ".")


def load_python() -> tuple[list[PyFile], list[dict[str, str]]]:
    files: list[PyFile] = []
    errors: list[dict[str, str]] = []
    for base in PY_ROOTS:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            text = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(text, filename=rel)
            except SyntaxError as exc:
                errors.append({"path": rel, "error": f"{exc.msg}:{exc.lineno}:{exc.offset}"})
                continue
            files.append(PyFile(path, rel, module_name(path), text, tree))
    return files, errors


def imports_for(file: PyFile) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(file.tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def package_modules() -> set[str]:
    packages: set[str] = set()
    backend = ROOT / "backend"
    if not backend.exists():
        return packages
    for path in backend.rglob("*"):
        if path.is_dir():
            packages.add(path.relative_to(ROOT).as_posix().replace("/", "."))
    return packages


def import_graph(files: list[PyFile]) -> tuple[dict[str, set[str]], list[dict[str, str]]]:
    modules = {file.module for file in files}
    packages = package_modules()
    graph: dict[str, set[str]] = {file.module: set() for file in files}
    unresolved: list[dict[str, str]] = []
    for file in files:
        for imported in sorted(imports_for(file)):
            if not imported.startswith("backend."):
                continue
            if imported in modules:
                graph[file.module].add(imported)
                continue
            if imported in packages:
                continue
            prefix = next((name for name in modules if imported.startswith(name + ".")), None)
            if prefix:
                graph[file.module].add(prefix)
            else:
                unresolved.append({"path": file.rel, "import": imported})
    return graph, unresolved


def strongly_connected(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    active: set[str] = set()
    indexes: dict[str, int] = {}
    low: dict[str, int] = {}
    groups: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = low[node] = index
        index += 1
        stack.append(node)
        active.add(node)
        for nxt in graph.get(node, set()):
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
            groups.append(sorted(group))

    for node in graph:
        if node not in indexes:
            visit(node)
    return sorted(groups)


def normalized_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    clone = ast.parse(ast.unparse(node)).body[0]
    assert isinstance(clone, (ast.FunctionDef, ast.AsyncFunctionDef))
    clone.name = "_"
    return ast.dump(clone, include_attributes=False)


def function_inventory(files: Iterable[PyFile]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    hotspots: list[dict[str, Any]] = []
    duplicates: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
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
            row = {"path": file.rel, "function": node.name, "line": node.lineno, "loc": loc, "branch_points": branches}
            if loc >= 80 or branches >= 18:
                hotspots.append(row)
            if loc >= 4:
                duplicates[canonical_sha(normalized_function(node))].append(row)
    duplicate_groups = [
        {"fingerprint": fingerprint, "copy_count": len(rows), "copies": rows}
        for fingerprint, rows in duplicates.items()
        if len({row["path"] for row in rows}) > 1
    ]
    return (
        sorted(hotspots, key=lambda row: (-row["loc"], -row["branch_points"], row["path"])),
        sorted(duplicate_groups, key=lambda row: (-row["copy_count"], row["fingerprint"])),
    )


def literal_dict(node: ast.AST) -> dict[str, Any] | None:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return None
    return value if isinstance(value, dict) else None


def safety_audit(files: Iterable[PyFile]) -> dict[str, Any]:
    definitions: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    for file in files:
        if "strategy11" not in file.rel:
            continue
        for node in file.tree.body:
            targets: list[str] = []
            value_node: ast.AST | None = None
            if isinstance(node, ast.Assign):
                targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
                value_node = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
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
                mismatches.append({**row, "mismatch_keys": mismatch})
    fingerprints = Counter(canonical_sha(row["value"]) for row in definitions)
    return {
        "definition_count": len(definitions),
        "distinct_literal_count": len(fingerprints),
        "duplicate_literal_groups": sorted(fingerprints.values(), reverse=True),
        "partial_or_mismatched": mismatches,
    }


def workflow_audit() -> tuple[dict[str, set[str]], list[dict[str, Any]], list[dict[str, Any]]]:
    refs: dict[str, set[str]] = defaultdict(set)
    workflows: list[dict[str, Any]] = []
    schedules: defaultdict[str, list[str]] = defaultdict(list)
    path_re = re.compile(r"(?:python\s+|-m\s+)(backend/[A-Za-z0-9_./-]+\.py)")
    cron_re = re.compile(r"cron:\s*['\"]([^'\"]+)['\"]")
    if not WORKFLOW_ROOT.exists():
        return refs, workflows, []
    for path in sorted(WORKFLOW_ROOT.glob("*.y*ml")):
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        python_refs = sorted(set(path_re.findall(text)))
        for target in python_refs:
            refs[target].add(rel)
        crons = cron_re.findall(text)
        for cron in crons:
            schedules[cron].append(rel)
        workflows.append(
            {
                "path": rel,
                "line_count": len(text.splitlines()),
                "has_permissions": bool(re.search(r"(?m)^permissions:", text)),
                "has_concurrency": bool(re.search(r"(?m)^concurrency:", text)),
                "write_permissions": sorted(set(re.findall(r"(?m)^\s+([a-z-]+):\s*write\s*$", text))),
                "cron": crons,
                "python_refs": python_refs,
            }
        )
    collisions = find_overlapping_schedules(workflows)
    return refs, workflows, collisions


def possible_dead_modules(files: Iterable[PyFile], graph: dict[str, set[str]], workflow_refs: dict[str, set[str]]) -> list[dict[str, str]]:
    inbound: Counter[str] = Counter()
    for targets in graph.values():
        inbound.update(targets)
    result: list[dict[str, str]] = []
    for file in files:
        if "strategy11" not in file.rel:
            continue
        has_main = any(isinstance(node, ast.If) and "__main__" in ast.unparse(node.test) for node in file.tree.body)
        if inbound[file.module] == 0 and file.rel not in workflow_refs and not has_main:
            result.append({"path": file.rel, "module": file.module, "reason": "NO_IMPORT_WORKFLOW_OR_MAIN"})
    return sorted(result, key=lambda row: row["path"])


def naming_anomalies(files: Iterable[PyFile]) -> list[dict[str, str]]:
    names = {file.path.name for file in files}
    result: list[dict[str, str]] = []
    residual = re.compile(r"(?:^|_)(?:copy|backup|old|legacy|tmp)(?:_|\.)", re.IGNORECASE)
    for file in files:
        name = file.path.name
        if re.search(r"_v\d+_\d+\.py$", name):
            result.append({"path": file.rel, "reason": "DOUBLE_VERSION_SUFFIX"})
        if "_optimized_" in name:
            base = name.replace("_optimized_", "_")
            if base in names:
                result.append({"path": file.rel, "reason": "PARALLEL_OPTIMIZED_IMPLEMENTATION"})
        if residual.search(name):
            result.append({"path": file.rel, "reason": "POSSIBLE_RESIDUAL_NAME"})
    return result


def pipeline_audit(files: Iterable[PyFile], graph: dict[str, set[str]]) -> dict[str, Any]:
    modules = {file.module for file in files}
    missing = [module for module in PIPELINE if module not in modules]
    edges = []
    for upstream, downstream in zip(PIPELINE, PIPELINE[1:]):
        direct = upstream in graph.get(downstream, set()) or downstream in graph.get(upstream, set())
        edges.append({"upstream": upstream, "downstream": downstream, "direct_import_edge": direct})
    return {
        "stage_count": len(PIPELINE),
        "missing_stages": missing,
        "direct_edges": edges,
        "disconnected_direct_edges": [row for row in edges if not row["direct_import_edge"]],
        "note": "Direct imports are diagnostic only; sealed artifact handoff may be intentional.",
    }


def module_stats(files: Iterable[PyFile], graph: dict[str, set[str]]) -> list[dict[str, Any]]:
    inbound: Counter[str] = Counter()
    for targets in graph.values():
        inbound.update(targets)
    return sorted(
        [
            {
                "path": file.rel,
                "module": file.module,
                "loc": len(file.text.splitlines()),
                "internal_import_out": len(graph.get(file.module, set())),
                "internal_import_in": inbound[file.module],
            }
            for file in files
        ],
        key=lambda row: (-row["loc"], row["path"]),
    )


def write_report(report: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = report["summary"]
    lines = ["# Strategy11 Internal Organic Audit V1", ""]
    lines.extend(f"- {key}: `{value}`" for key, value in summary.items())
    lines.extend(["", "## Priority findings"])
    lines.extend(f"- **{row['severity']} {row['code']}** — {row['detail']}" for row in report["priority_findings"])
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    files, syntax_errors = load_python()
    graph, unresolved = import_graph(files)
    cycles = strongly_connected(graph)
    production = [file for file in files if not file.is_fixture]
    fixtures = [file for file in files if file.is_fixture]
    production_hotspots, production_duplicates = function_inventory(production)
    fixture_hotspots, fixture_duplicates = function_inventory(fixtures)
    safety = safety_audit(files)
    workflow_refs, workflows, schedule_collisions = workflow_audit()
    dead = possible_dead_modules(files, graph, workflow_refs)
    naming = naming_anomalies(files)
    pipeline = pipeline_audit(files, graph)

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
        priority.append({"severity": "C", "code": "PIPELINE_STAGE_MISSING", "detail": f"{len(pipeline['missing_stages'])} stages"})
    if naming:
        priority.append({"severity": "m", "code": "NAMING_OR_PARALLEL_IMPL_RESIDUE", "detail": f"{len(naming)} files"})
    if dead:
        priority.append({"severity": "m", "code": "POSSIBLE_DEAD_MODULE", "detail": f"{len(dead)} files"})
    if production_hotspots:
        priority.append({"severity": "m", "code": "PRODUCTION_COMPLEXITY_HOTSPOT", "detail": f"{len(production_hotspots)} functions"})
    if production_duplicates:
        priority.append({"severity": "m", "code": "PRODUCTION_DUPLICATE_HELPER", "detail": f"{len(production_duplicates)} groups"})
    if schedule_collisions:
        priority.append({"severity": "m", "code": "WORKFLOW_SCHEDULE_COLLISION", "detail": f"{len(schedule_collisions)} cron groups"})
    if not priority:
        priority.append({"severity": "PASS", "code": "NO_STATIC_BLOCKER", "detail": "No structural blocker detected"})

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
            "naming_anomaly_count": len(naming),
            "dead_candidate_count": len(dead),
            "production_hotspot_count": len(production_hotspots),
            "fixture_hotspot_count": len(fixture_hotspots),
            "production_duplicate_group_count": len(production_duplicates),
            "fixture_duplicate_group_count": len(fixture_duplicates),
            "schedule_collision_count": len(schedule_collisions),
            "pipeline_missing_stage_count": len(pipeline["missing_stages"]),
        },
        "priority_findings": priority,
        "syntax_errors": syntax_errors,
        "unresolved_internal_imports": unresolved,
        "import_cycles": cycles,
        "safety": safety,
        "naming_anomalies": naming,
        "possible_dead_modules": dead,
        "production_complexity_hotspots": production_hotspots,
        "fixture_complexity_hotspots": fixture_hotspots,
        "production_duplicate_function_groups": production_duplicates,
        "fixture_duplicate_function_groups": fixture_duplicates,
        "workflow_schedule_collisions": schedule_collisions,
        "workflows": workflows,
        "pipeline": pipeline,
        "module_stats": module_stats(files, graph),
    }
    report["report_sha"] = canonical_sha(report)
    write_report(report)
    print(json.dumps(report["summary"], sort_keys=True))
    print(json.dumps({
        "priority_findings": priority,
        "unresolved_internal_imports": unresolved,
        "safety_mismatches": safety["partial_or_mismatched"],
        "naming_anomalies": naming,
        "production_hotspots": production_hotspots[:20],
        "production_duplicate_groups": production_duplicates[:10],
        "pipeline": pipeline,
    }, indent=2, sort_keys=True))
    print(f"REPORT_SHA={report['report_sha']}")
    return 1 if critical else 0


if __name__ == "__main__":
    raise SystemExit(main())
