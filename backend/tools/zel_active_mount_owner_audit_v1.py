from __future__ import annotations

import argparse
import ast
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

VERSION = "ZEL_ACTIVE_MOUNT_OWNER_AUDIT_V1"


def _string_list(node: ast.AST) -> list[str]:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return []
    out: list[str] = []
    for item in node.elts:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            out.append(item.value)
    return out


def _canonical_module(modules: set[str]) -> str:
    backend = sorted(m for m in modules if m.startswith("backend."))
    if backend:
        return backend[0]
    return sorted(modules)[0] if modules else "UNKNOWN"


def _guard_text(source_lines: list[str], node: ast.AST) -> str:
    parent = getattr(node, "_parent", None)
    guards: list[str] = []
    while parent is not None:
        if isinstance(parent, ast.If):
            segment = ast.get_source_segment("\n".join(source_lines), parent.test)
            if segment:
                guards.append(segment.strip())
        parent = getattr(parent, "_parent", None)
    return " && ".join(reversed(guards))


def audit(path: Path) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            setattr(child, "_parent", parent)

    alias_modules: dict[str, set[str]] = defaultdict(set)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if alias.name == "router":
                    alias_modules[alias.asname or alias.name].add(node.module)

        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Name) and call.func.id == "_import_module_attr" and call.args:
                modules = _string_list(call.args[0])
                names: list[str] = []
                for target in node.targets:
                    if isinstance(target, ast.Tuple):
                        names.extend(elt.id for elt in target.elts if isinstance(elt, ast.Name))
                    elif isinstance(target, ast.Name):
                        names.append(target.id)
                if names:
                    alias_modules[names[0]].update(modules)

    mounts: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "include_router" or not node.args:
            continue
        owner = node.func.value.id if isinstance(node.func.value, ast.Name) else ast.unparse(node.func.value)
        arg = node.args[0]
        alias = arg.id if isinstance(arg, ast.Name) else ast.unparse(arg)
        modules = alias_modules.get(alias, set())
        mounts.append(
            {
                "owner": owner,
                "router_alias": alias,
                "candidate_modules": sorted(modules),
                "canonical_module": _canonical_module(modules),
                "line": int(getattr(node, "lineno", 0)),
                "guard": _guard_text(lines, node),
            }
        )

    by_alias: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_module: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in mounts:
        by_alias[row["router_alias"]].append(row)
        by_module[row["canonical_module"]].append(row)

    repeated_aliases = {
        alias: rows for alias, rows in sorted(by_alias.items()) if len(rows) > 1
    }
    repeated_modules = {
        module: rows
        for module, rows in sorted(by_module.items())
        if module != "UNKNOWN" and len(rows) > 1
    }

    recursive_functions: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls_self = any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == node.name
            for call in ast.walk(node)
        )
        if calls_self:
            recursive_functions.append({"function": node.name, "line": node.lineno})

    findings: list[dict[str, Any]] = []
    for alias, rows in repeated_aliases.items():
        findings.append(
            {
                "code": "ROUTER_ALIAS_INCLUDED_MULTIPLE_TIMES",
                "severity": "HIGH",
                "router_alias": alias,
                "mounts": rows,
            }
        )
    for module, rows in repeated_modules.items():
        findings.append(
            {
                "code": "ROUTER_MODULE_HAS_MULTIPLE_MOUNT_PATHS",
                "severity": "HIGH",
                "module": module,
                "mounts": rows,
            }
        )
    for row in recursive_functions:
        findings.append(
            {
                "code": "DIRECT_SELF_RECURSION",
                "severity": "CRITICAL",
                **row,
            }
        )

    state = "PASS_SINGLE_MOUNT_OWNER" if not findings else "HOLD_MOUNT_OWNER_REVIEW_REQUIRED"
    return {
        "schema_version": "1.0",
        "version": VERSION,
        "state": state,
        "entrypoint": str(path),
        "mount_count": len(mounts),
        "mounts": mounts,
        "repeated_alias_count": len(repeated_aliases),
        "repeated_module_count": len(repeated_modules),
        "recursive_function_count": len(recursive_functions),
        "findings": findings,
        "next": "MINIMAL_GUARDED_SINGLE_OWNER_PATCH" if findings else "FREEZE_ROUTE_OWNER_SSOT",
        "safety": {
            "read_only": True,
            "canonical_mutated": False,
            "registry_mutated": False,
            "runtime_mutated": False,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
            "protected_mutations": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry", default="backend/main.py")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = audit(Path(args.entry))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("state", "mount_count", "repeated_alias_count", "repeated_module_count", "recursive_function_count")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
