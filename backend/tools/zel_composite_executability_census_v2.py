from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import zel_composite_executability_census_v1 as v1

VERSION = "ZEL_COMPOSITE_EXECUTABILITY_CENSUS_V2"
FUNCTION_RISK_CALLS = {
    "open",
    "write_text",
    "write_bytes",
    "unlink",
    "rename",
    "replace",
    "system",
    "popen",
    "run",
    "call",
    "check_call",
    "check_output",
    "post",
    "put",
    "delete",
    "create_order",
    "cancel_order",
    "place_order",
    "submit_order",
    "set_leverage",
    "set_margin",
    "transfer",
}
NETWORK_CALL_TOKENS = {
    "urlopen",
    "request",
    "get",
    "fetch_json",
    "http",
    "https",
    "curl",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def scalar(value: ast.AST) -> Any:
    try:
        result = ast.literal_eval(value)
    except Exception:
        return None
    if isinstance(result, (str, int, float, bool)) or result is None:
        return result
    return None


def function_descriptor(node: ast.FunctionDef | ast.AsyncFunctionDef, qualified: str) -> dict[str, Any]:
    calls: set[str] = set()
    return_keys: set[str] = set()
    strings: set[str] = set()
    assigned_names: set[str] = set()
    branch_count = 0
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = call_name(child.func)
            if name:
                calls.add(name)
        elif isinstance(child, ast.Return) and isinstance(child.value, ast.Dict):
            for key in child.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    return_keys.add(key.value)
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            value = child.value.strip()
            if value and len(value) <= 100 and "\n" not in value:
                strings.add(value)
        elif isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name):
                    assigned_names.add(target.id)
        elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            assigned_names.add(child.target.id)
        elif isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.Match)):
            branch_count += 1
    simple_calls = {name.rsplit(".", 1)[-1].casefold() for name in calls}
    mutation_calls = sorted(name for name in calls if name.rsplit(".", 1)[-1].casefold() in FUNCTION_RISK_CALLS)
    network_calls = sorted(
        name
        for name in calls
        if any(token in name.casefold() for token in NETWORK_CALL_TOKENS)
    )
    return {
        "qualified_name": qualified,
        "kind": "async" if isinstance(node, ast.AsyncFunctionDef) else "sync",
        "line": node.lineno,
        "args": v1.arg_names(node.args),
        "decorators": sorted(filter(None, (call_name(item) for item in node.decorator_list))),
        "calls": sorted(calls)[:100],
        "mutation_calls": mutation_calls,
        "network_calls": network_calls,
        "return_dict_keys": sorted(return_keys),
        "assigned_names": sorted(assigned_names),
        "string_constants": sorted(strings)[:100],
        "branch_count": branch_count,
        "function_level_offline_safe": not mutation_calls and not network_calls,
    }


def semantic_file(path: Path, display_path: str) -> dict[str, Any]:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    tree = ast.parse(text, filename=display_path)
    functions: list[dict[str, Any]] = []
    classes: list[dict[str, Any]] = []
    module_assignments: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(function_descriptor(node, node.name))
        elif isinstance(node, ast.ClassDef):
            fields: dict[str, Any] = {}
            methods: list[dict[str, Any]] = []
            decorators = sorted(filter(None, (call_name(item) for item in node.decorator_list)))
            bases = sorted(filter(None, (call_name(item) for item in node.bases)))
            for child in node.body:
                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                    fields[child.target.id] = scalar(child.value) if child.value is not None else None
                elif isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name):
                            fields[target.id] = scalar(child.value)
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append(function_descriptor(child, f"{node.name}.{child.name}"))
            classes.append(
                {
                    "name": node.name,
                    "line": node.lineno,
                    "decorators": decorators,
                    "bases": bases,
                    "fields": fields,
                    "methods": methods,
                }
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            module_assignments[node.target.id] = scalar(node.value) if node.value is not None else None
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    module_assignments[target.id] = scalar(node.value)
    return {
        "path": display_path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "functions": functions,
        "classes": classes,
        "module_assignments": module_assignments,
    }


def resolve_source(runtime_root: Path, git_root: Path, display_path: str) -> tuple[Path, str]:
    if display_path.startswith("external:"):
        return Path(display_path[len("external:") :]), "EXTERNAL_ACTIVE_RUNTIME"
    runtime = runtime_root / display_path
    if runtime.is_file():
        return runtime, "VPS_RUNTIME_ROOT"
    git = git_root / display_path
    if git.is_file():
        return git, "GIT_BUNDLE_ROOT"
    return runtime, "MISSING"


def build(runtime_root: Path, git_root: Path, pin: dict[str, Any]) -> dict[str, Any]:
    modules = pin.get("modules") if isinstance(pin.get("modules"), list) else []
    semantic_modules: list[dict[str, Any]] = []
    source_errors: list[str] = []
    for module in modules:
        if not isinstance(module, dict):
            continue
        file_rows: list[dict[str, Any]] = []
        bundle_rows: list[dict[str, str]] = []
        for display_path_raw in module.get("source_paths", []):
            display_path = str(display_path_raw)
            path, source_scope = resolve_source(runtime_root, git_root, display_path)
            if not path.is_file():
                source_errors.append(f"SOURCE_MISSING:{module.get('module_id')}:{display_path}")
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            bundle_rows.append({"path": display_path, "sha256": digest})
            if path.suffix.casefold() == ".py":
                try:
                    row = semantic_file(path, display_path)
                    row["source_scope"] = source_scope
                    row["parse_state"] = "PASS"
                    file_rows.append(row)
                except SyntaxError as exc:
                    source_errors.append(f"PARSE_ERROR:{module.get('module_id')}:{display_path}:{exc.lineno}")
                    file_rows.append(
                        {
                            "path": display_path,
                            "sha256": digest,
                            "source_scope": source_scope,
                            "parse_state": "HOLD_SYNTAX_ERROR",
                            "functions": [],
                            "classes": [],
                            "module_assignments": {},
                        }
                    )
            else:
                file_rows.append(
                    {
                        "path": display_path,
                        "sha256": digest,
                        "source_scope": source_scope,
                        "parse_state": "PASS_NON_PYTHON_SOURCE",
                        "functions": [],
                        "classes": [],
                        "module_assignments": {},
                    }
                )
        actual_bundle = v1.stable_sha(sorted(bundle_rows, key=lambda row: row["path"])) if bundle_rows else None
        expected_bundle = module.get("source_bundle_sha256")
        parity = actual_bundle == expected_bundle
        if not parity:
            source_errors.append(f"SOURCE_BUNDLE_SHA_MISMATCH:{module.get('module_id')}")
        all_functions = [function for file_row in file_rows for function in file_row["functions"]]
        all_methods = [method for file_row in file_rows for class_row in file_row["classes"] for method in class_row["methods"]]
        offline_safe = [row for row in all_functions + all_methods if row["function_level_offline_safe"]]
        semantic_modules.append(
            {
                "module_id": module.get("module_id"),
                "expected_source_bundle_sha256": expected_bundle,
                "actual_source_bundle_sha256": actual_bundle,
                "source_pin_match": parity,
                "source_file_count": len(file_rows),
                "function_count": len(all_functions),
                "method_count": len(all_methods),
                "offline_safe_callable_count": len(offline_safe),
                "files": file_rows,
            }
        )
    state = "PASS_COMPOSITE_EXECUTABILITY_SEMANTIC_CENSUS" if not source_errors and len(semantic_modules) == 12 else "HOLD_COMPOSITE_EXECUTABILITY_SEMANTIC_CENSUS"
    result: dict[str, Any] = {
        "schema_version": "zel.composite.executability_semantic_census.v2",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "module_count": len(semantic_modules),
        "source_pin_verified_count": sum(1 for row in semantic_modules if row["source_pin_match"]),
        "source_error_count": len(source_errors),
        "source_errors": sorted(set(source_errors)),
        "modules": semantic_modules,
        "economic_claim_allowed": False,
        "exact_replay_started": False,
        "w2_started": False,
        "w3_started": False,
        "portfolio_joint_risk_started": False,
        "active_data_b_1m_mutated": False,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    result["receipt_sha256"] = v1.stable_sha(result)
    return result


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runtime = root / "runtime"
        git = root / "git"
        runtime.mkdir()
        git.mkdir()
        modules = []
        for index in range(12):
            module_id = f"M{index:02d}"
            relative = f"backend/{module_id.lower()}.py"
            target_root = git if index == 11 else runtime
            path = target_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("def evaluate(context):\n    return {'state': 'PASS', 'value': context}\n", encoding="utf-8")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            modules.append(
                {
                    "module_id": module_id,
                    "source_paths": [relative],
                    "source_bundle_sha256": v1.stable_sha([{"path": relative, "sha256": digest}]),
                }
            )
        row = build(runtime, git, {"modules": modules})
        assert row["state"] == "PASS_COMPOSITE_EXECUTABILITY_SEMANTIC_CENSUS", row
        assert row["source_pin_verified_count"] == 12, row
        assert row["modules"][-1]["files"][0]["source_scope"] == "GIT_BUNDLE_ROOT", row
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--git-root", type=Path)
    parser.add_argument("--pin", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.runtime_root or not args.git_root or not args.pin:
        parser.error("runtime-root, git-root and pin are required")
    row = build(
        args.runtime_root.resolve(),
        args.git_root.resolve(),
        json.loads(args.pin.read_text(encoding="utf-8")),
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.stdout or not args.out:
        print(json.dumps(row, sort_keys=True))
    return 0 if row["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
