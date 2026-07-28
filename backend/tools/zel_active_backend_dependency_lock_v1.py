#!/usr/bin/env python3
"""Build a read-only dependency reachability lock for the recovered active backend."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

SAFETY = {
    "canonical_mutated": False,
    "registry_mutated": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
}

DISTRIBUTIONS = {
    "fastapi": "fastapi",
    "flask": "Flask",
    "googleapiclient": "google-api-python-client",
    "google": "google-auth",
    "pandas": "pandas",
    "pydantic": "pydantic",
    "sqlalchemy": "SQLAlchemy",
    "starlette": "starlette",
    "uvicorn": "uvicorn",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def module_name(path: str) -> str:
    value = path[:-3] if path.endswith(".py") else path
    if value.endswith("/__init__"):
        value = value[: -len("/__init__")]
    return value.replace("/", ".")


def resolve_relative(current: str, level: int, target: str | None) -> str:
    parts = current.split(".")
    if not current.endswith(".__init__"):
        parts = parts[:-1]
    if level:
        parts = parts[: max(0, len(parts) - (level - 1))]
    if target:
        parts.extend(target.split("."))
    return ".".join(parts)


def inside_try(node: ast.AST, parent: dict[ast.AST, ast.AST]) -> bool:
    current = node
    while current in parent:
        current = parent[current]
        if isinstance(current, ast.Try):
            return True
    return False


def scan_file(path: Path, module: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    rows: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        guarded = inside_try(node, parent)
        if isinstance(node, ast.Import):
            for alias in node.names:
                rows.append({"module": alias.name, "line": node.lineno, "guarded": guarded})
        elif isinstance(node, ast.ImportFrom):
            base = resolve_relative(module, node.level, node.module)
            if base:
                rows.append({"module": base, "line": node.lineno, "guarded": guarded})
                for alias in node.names:
                    if alias.name != "*":
                        rows.append({"module": f"{base}.{alias.name}", "line": node.lineno, "guarded": guarded})
    return {"module": module, "path": path.as_posix(), "imports": rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--runtime-packages", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    runtime = json.loads(args.runtime_packages.read_text(encoding="utf-8"))
    files = [row["path"] for row in manifest["files"] if row["path"].endswith(".py")]
    module_to_path = {module_name(rel): rel for rel in files}
    scans: dict[str, dict[str, Any]] = {}
    parse_errors: list[dict[str, str]] = []
    for mod, rel in sorted(module_to_path.items()):
        try:
            scans[mod] = scan_file(root / rel, mod)
        except Exception as exc:
            parse_errors.append({"path": rel, "error": type(exc).__name__})

    graph: dict[str, set[str]] = defaultdict(set)
    package_refs: list[dict[str, Any]] = []
    for mod, scan in scans.items():
        for row in scan["imports"]:
            target = row["module"]
            candidates = [target]
            parts = target.split(".")
            candidates.extend(".".join(parts[:i]) for i in range(len(parts) - 1, 0, -1))
            internal = next((candidate for candidate in candidates if candidate in module_to_path), None)
            if internal:
                graph[mod].add(internal)
            root_name = parts[0].lower()
            if root_name in DISTRIBUTIONS:
                package_refs.append({
                    "distribution": DISTRIBUTIONS[root_name],
                    "import_root": root_name,
                    "source_module": mod,
                    "source_path": scan["path"],
                    "line": row["line"],
                    "guarded": row["guarded"],
                })

    entry = "backend.main"
    reachable: set[str] = set()
    queue: deque[str] = deque([entry])
    while queue:
        current = queue.popleft()
        if current in reachable or current not in module_to_path:
            continue
        reachable.add(current)
        queue.extend(sorted(graph.get(current, ())))

    versions = {
        row["name"]: {"version": row.get("version"), "state": row.get("state")}
        for row in runtime.get("packages", [])
    }
    packages: list[dict[str, Any]] = []
    for distribution in sorted(set(DISTRIBUTIONS.values())):
        refs = [row for row in package_refs if row["distribution"] == distribution]
        reachable_refs = [row for row in refs if row["source_module"] in reachable]
        reachable_unguarded = [row for row in reachable_refs if not row["guarded"]]
        runtime_row = versions.get(distribution, {"version": None, "state": "NOT_CHECKED"})
        if distribution == "uvicorn":
            classification = "REQUIRED_RUNTIME_LAUNCHER"
        elif reachable_unguarded:
            classification = "REQUIRED_REACHABLE_IMPORT"
        elif reachable_refs:
            classification = "OPTIONAL_GUARDED_REACHABLE_IMPORT"
        elif refs:
            classification = "OPTIONAL_UNREACHABLE_RECOVERED_IMPORT"
        else:
            classification = "RUNTIME_PRESENT_NOT_IMPORTED"
        installed = runtime_row.get("state") == "INSTALLED"
        blocker = classification.startswith("REQUIRED_") and not installed
        packages.append({
            "distribution": distribution,
            "installed": installed,
            "version": runtime_row.get("version"),
            "classification": classification,
            "blocker": blocker,
            "reference_count": len(refs),
            "reachable_reference_count": len(reachable_refs),
            "reachable_unguarded_reference_count": len(reachable_unguarded),
            "references": refs,
        })

    blockers = [f"MISSING_REQUIRED_DEPENDENCY:{row['distribution']}" for row in packages if row["blocker"]]
    result = {
        "schema_version": "zel.active_backend_dependency_lock.v1",
        "state": "HOLD_REQUIRED_DEPENDENCY_MISSING" if blockers else "PASS_ACTIVE_BACKEND_DEPENDENCY_LOCK",
        "entry_module": entry,
        "manifest_sha256": sha256_text(canonical_json(manifest)),
        "runtime_interpreter": runtime.get("python"),
        "runtime_python_version": runtime.get("python_version"),
        "runtime_packages_sha256": sha256_text(canonical_json(runtime)),
        "python_file_count": len(files),
        "reachable_internal_module_count": len(reachable),
        "reachable_internal_modules": sorted(reachable),
        "parse_error_count": len(parse_errors),
        "parse_errors": parse_errors,
        "packages": packages,
        "blocker_codes": blockers,
        "deployment_changed": False,
        "service_changed": False,
        "database_changed": False,
        **SAFETY,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(result["state"])
    return 1 if blockers or parse_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
