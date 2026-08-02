from __future__ import annotations

import argparse
import ast
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_COMPOSITE_ADAPTER_CONTRACT_VALIDATOR_V1"
WRITE_CALL_SUFFIXES = {
    "write_text",
    "write_bytes",
    "unlink",
    "rename",
    "mkdir",
    "rmdir",
    "create_order",
    "cancel_order",
    "place_order",
    "submit_order",
    "set_leverage",
    "set_margin",
    "transfer",
}
NETWORK_CALLS = {
    "urllib.request.urlopen",
    "requests.get",
    "requests.post",
    "requests.put",
    "requests.delete",
    "httpx.get",
    "httpx.post",
    "aiohttp.ClientSession",
    "socket.create_connection",
    "fetch_json",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def arg_names(arguments: ast.arguments) -> list[str]:
    result = [arg.arg for arg in arguments.posonlyargs]
    result.extend(arg.arg for arg in arguments.args)
    if arguments.vararg:
        result.append("*" + arguments.vararg.arg)
    result.extend(arg.arg for arg in arguments.kwonlyargs)
    if arguments.kwarg:
        result.append("**" + arguments.kwarg.arg)
    return result


def resolve_path(runtime_root: Path, git_root: Path, value: str) -> tuple[Path, str]:
    if value.startswith("external:"):
        return Path(value[len("external:") :]), "EXTERNAL_ACTIVE_RUNTIME"
    runtime = runtime_root / value
    if runtime.is_file():
        return runtime, "VPS_RUNTIME_ROOT"
    git = git_root / value
    if git.is_file():
        return git, "GIT_ROOT"
    return runtime, "MISSING"


def scalar(node: ast.AST | None) -> Any:
    if node is None:
        return None
    try:
        value = ast.literal_eval(node)
    except Exception:
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


def locate_symbol(tree: ast.Module, symbol: str, kind: str) -> ast.AST | None:
    for node in tree.body:
        if kind == "function" and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol:
            return node
        if kind == "class" and isinstance(node, ast.ClassDef) and node.name == symbol:
            return node
    return None


def function_calls(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    result = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = call_name(child.func)
            if name:
                result.append(name)
    return sorted(set(result))


def function_risk(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, list[str]]:
    calls = function_calls(node)
    write_calls = sorted(
        name for name in calls if name.rsplit(".", 1)[-1].casefold() in WRITE_CALL_SUFFIXES
    )
    if "os.replace" in calls:
        write_calls.append("os.replace")
    network_calls = sorted(
        name
        for name in calls
        if name in NETWORK_CALLS
        or name.startswith("urllib.request.")
        or name.startswith("requests.")
        or name.startswith("httpx.")
        or name.startswith("aiohttp.")
        or name.startswith("socket.")
    )
    subprocess_calls = sorted(
        name for name in calls if name.startswith("subprocess.") or name in {"os.system", "os.popen"}
    )
    return {
        "write_calls": sorted(set(write_calls)),
        "network_calls": network_calls,
        "subprocess_calls": subprocess_calls,
    }


def class_fields(node: ast.ClassDef) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for child in node.body:
        if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            fields[child.target.id] = scalar(child.value)
        elif isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name):
                    fields[target.id] = scalar(child.value)
    return fields


def validate_adapter(runtime_root: Path, git_root: Path, row: dict[str, Any]) -> dict[str, Any]:
    module_id = str(row.get("module_id") or "")
    source = str(row.get("source_path") or "")
    symbol = str(row.get("symbol") or "")
    kind = str(row.get("symbol_kind") or "")
    path, source_scope = resolve_path(runtime_root, git_root, source)
    errors: list[str] = []
    symbol_args: list[str] | None = None
    observed_fields: dict[str, Any] = {}
    risk = {"write_calls": [], "network_calls": [], "subprocess_calls": []}
    source_sha = None
    if not path.is_file():
        errors.append("SOURCE_MISSING")
    else:
        raw = path.read_bytes()
        source_sha = hashlib.sha256(raw).hexdigest()
        try:
            tree = ast.parse(raw.decode("utf-8", errors="replace"), filename=source)
        except SyntaxError as exc:
            errors.append(f"SOURCE_PARSE_ERROR:{exc.lineno}")
        else:
            target = locate_symbol(tree, symbol, kind)
            if target is None:
                errors.append("SYMBOL_MISSING")
            elif isinstance(target, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbol_args = arg_names(target.args)
                if symbol_args != list(row.get("required_args") or []):
                    errors.append("SIGNATURE_MISMATCH")
                risk = function_risk(target)
                node_mode = str(row.get("node_mode") or "")
                if node_mode != "RUNTIME_OBSERVER_ONLY" and any(risk.values()):
                    errors.append("OFFLINE_ADAPTER_SIDE_EFFECT_SURFACE")
            elif isinstance(target, ast.ClassDef):
                observed_fields = class_fields(target)
                required = row.get("class_fields_required") if isinstance(row.get("class_fields_required"), dict) else {}
                for key, expected in required.items():
                    if observed_fields.get(key) != expected:
                        errors.append(f"CLASS_FIELD_MISMATCH:{key}")
    state = "PASS_ADAPTER_CONTRACT" if not errors else "HOLD_ADAPTER_CONTRACT"
    return {
        "module_id": module_id,
        "state": state,
        "node_mode": row.get("node_mode"),
        "economic_role": row.get("economic_role"),
        "source_path": source,
        "source_scope": source_scope,
        "source_sha256": source_sha,
        "symbol": symbol,
        "symbol_kind": kind,
        "required_args": row.get("required_args"),
        "observed_args": symbol_args,
        "required_class_fields": row.get("class_fields_required"),
        "observed_class_fields": observed_fields,
        "risk_surface": risk,
        "direct_alpha_claim_allowed": bool(row.get("direct_alpha_claim_allowed")),
        "w2_eligible": bool(row.get("w2_eligible")),
        "w3_eligible": bool(row.get("w3_eligible")),
        "errors": sorted(set(errors)),
    }


def build(runtime_root: Path, git_root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if contract.get("schema_version") != "zel.composite.adapter_contract.v1":
        errors.append("CONTRACT_SCHEMA_INVALID")
    adapters_raw = contract.get("adapters") if isinstance(contract.get("adapters"), list) else []
    adapters = [validate_adapter(runtime_root, git_root, row) for row in adapters_raw if isinstance(row, dict)]
    ids = [row["module_id"] for row in adapters]
    if len(adapters) != 12:
        errors.append("ADAPTER_COUNT_NOT_12")
    if len(set(ids)) != len(ids):
        errors.append("DUPLICATE_MODULE_ID")
    if any(row["state"] != "PASS_ADAPTER_CONTRACT" for row in adapters):
        errors.append("ADAPTER_VALIDATION_FAILED")
    w2_ids = sorted(row["module_id"] for row in adapters if row["w2_eligible"])
    w3_ids = sorted(row["module_id"] for row in adapters if row["w3_eligible"])
    structural_only = sorted(row["module_id"] for row in adapters if not row["w2_eligible"] and row["node_mode"] != "POST_SCORE_RISK_GOVERNOR")
    post_score = sorted(row["module_id"] for row in adapters if row["node_mode"] == "POST_SCORE_RISK_GOVERNOR")
    state = "PASS_COMPOSITE_ADAPTER_CONTRACTS" if not errors else "HOLD_COMPOSITE_ADAPTER_CONTRACTS"
    result: dict[str, Any] = {
        "schema_version": "zel.composite.adapter_contract_validation.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "adapter_count": len(adapters),
        "adapter_pass_count": sum(1 for row in adapters if row["state"].startswith("PASS")),
        "w2_eligible_module_ids": w2_ids,
        "w3_eligible_module_ids": w3_ids,
        "structural_only_module_ids": structural_only,
        "post_score_module_ids": post_score,
        "adapters": adapters,
        "errors": sorted(set(errors)),
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
    result["receipt_sha256"] = stable_sha(result)
    return result


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runtime = root / "runtime"
        git = root / "git"
        runtime.mkdir()
        git.mkdir()
        adapters = []
        for index in range(12):
            module_id = f"M{index:02d}"
            relative = f"backend/{module_id.lower()}.py"
            target_root = git if index == 11 else runtime
            path = target_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("def evaluate(context):\n    return {'state': 'PASS'}\n", encoding="utf-8")
            adapters.append({
                "module_id": module_id,
                "node_mode": "EXECUTABLE_REPLAY",
                "economic_role": "TEST",
                "source_path": relative,
                "symbol": "evaluate",
                "symbol_kind": "function",
                "required_args": ["context"],
                "direct_alpha_claim_allowed": True,
                "w2_eligible": True,
                "w3_eligible": True,
            })
        row = build(runtime, git, {"schema_version": "zel.composite.adapter_contract.v1", "adapters": adapters})
        assert row["state"] == "PASS_COMPOSITE_ADAPTER_CONTRACTS", row
        assert row["adapter_pass_count"] == 12, row
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--git-root", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.runtime_root or not args.git_root or not args.contract:
        parser.error("runtime-root, git-root and contract are required")
    row = build(
        args.runtime_root.resolve(),
        args.git_root.resolve(),
        json.loads(args.contract.read_text(encoding="utf-8")),
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.stdout or not args.out:
        print(json.dumps(row, sort_keys=True))
    return 0 if row["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
