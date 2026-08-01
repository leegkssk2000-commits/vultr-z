from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import inspect
import json
import math
import os
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_TRADE_METHODS_RISK_SIZING_PROBE_V1"
MODULES = (
    "backend.trade_methods.types",
    "backend.trade_methods.policy",
    "backend.trade_methods.profiles",
    "backend.trade_methods.resolver",
    "backend.trade_methods",
)
RISK_TOKENS = (
    "risk", "drawdown", "loss_cap", "stop", "exposure", "leverage", "cost_band",
    "high_risk", "risk_mode", "risk_profile", "max_loss", "dd_",
)
SIZING_TOKENS = (
    "size", "sizing", "position_size", "scale_in", "pyramid", "dca", "average_down",
    "water_add", "allocation", "weight", "notional", "quantity", "qty", "risk_unit",
)
FIXTURE_BY_NAME = {
    "strategy_id": "trend_ma_macd",
    "strategy": "trend_ma_macd",
    "skills": [],
    "skill_ids": [],
    "skill": "partial30",
    "method": "trend",
    "method_id": "trend",
    "trade_method": "trend",
    "profile": "balanced",
    "side": "long",
    "cost_r": 0.1,
    "fee_r": 0.02,
    "slippage_r": 0.01,
    "funding_r": 0.0,
    "drawdown_r": -0.2,
    "dd_r": -0.2,
    "risk_r": 1.0,
    "risk_unit_r": 1.0,
    "position_size_pct": 10.0,
    "leverage": 10.0,
    "confidence": 0.7,
    "signal_strength": 0.7,
    "mfe_r": 1.0,
    "mae_r": -0.5,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def safe_value(value: Any, depth: int = 0) -> Any:
    if depth > 5:
        return "<depth_limit>"
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Enum):
        return {"enum": type(value).__name__, "name": value.name, "value": safe_value(value.value, depth + 1)}
    if is_dataclass(value):
        return safe_value(asdict(value), depth + 1)
    if isinstance(value, Mapping):
        return {str(key): safe_value(item, depth + 1) for key, item in list(value.items())[:100]}
    if isinstance(value, (list, tuple, set)):
        return [safe_value(item, depth + 1) for item in list(value)[:100]]
    if hasattr(value, "__dict__"):
        return {"type": type(value).__name__, "attrs": safe_value(vars(value), depth + 1)}
    return {"type": type(value).__name__, "repr": repr(value)[:500]}


def flatten_keys(value: Any, prefix: str = "") -> list[str]:
    keys: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            keys.append(path.lower())
            keys.extend(flatten_keys(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value[:20]):
            keys.extend(flatten_keys(item, f"{prefix}[{index}]"))
    return keys


def role_hits(values: list[str], tokens: tuple[str, ...]) -> list[str]:
    return sorted({value for value in values if any(token in value.lower() for token in tokens)})


def ast_inventory(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(text, filename=str(path))
    symbols: list[dict[str, Any]] = []
    strings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append({
                "kind": "function",
                "name": node.name,
                "args": [arg.arg for arg in node.args.args],
                "line": node.lineno,
            })
        elif isinstance(node, ast.ClassDef):
            symbols.append({"kind": "class", "name": node.name, "line": node.lineno})
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    symbols.append({"kind": "constant", "name": target.id, "line": node.lineno})
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if 0 < len(node.value) <= 200:
                strings.append(node.value)
    searchable = [f"symbol:{row['name'].lower()}" for row in symbols]
    searchable.extend(f"string:{value.lower()}" for value in strings)
    return {
        "path": str(path),
        "sha256": sha256_text(text),
        "symbols": symbols,
        "risk_hits": role_hits(searchable, RISK_TOKENS),
        "sizing_hits": role_hits(searchable, SIZING_TOKENS),
    }


def fixture_for_parameter(parameter: inspect.Parameter) -> tuple[bool, Any]:
    name = parameter.name.lower()
    if name in FIXTURE_BY_NAME:
        return True, FIXTURE_BY_NAME[name]
    annotation = parameter.annotation
    if annotation is bool:
        return True, False
    if annotation is int:
        return True, 1
    if annotation is float:
        return True, 0.1
    if annotation is str:
        return True, "fixture"
    if parameter.default is not inspect._empty:
        return False, None
    return False, None


def deterministic_call(function: Any) -> dict[str, Any]:
    signature = inspect.signature(function)
    kwargs: dict[str, Any] = {}
    unresolved: list[str] = []
    for parameter in signature.parameters.values():
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        has_fixture, value = fixture_for_parameter(parameter)
        if has_fixture:
            kwargs[parameter.name] = value
        elif parameter.default is inspect._empty:
            unresolved.append(parameter.name)
    result: dict[str, Any] = {
        "signature": str(signature),
        "fixture_kwargs": safe_value(kwargs),
        "unresolved_required_parameters": unresolved,
        "called": False,
    }
    if unresolved:
        return result
    try:
        output = function(**kwargs)
        safe = safe_value(output)
        keys = flatten_keys(safe)
        result.update({
            "called": True,
            "return_type": type(output).__name__,
            "output": safe,
            "output_keys": keys,
            "risk_output_hits": role_hits(keys, RISK_TOKENS),
            "sizing_output_hits": role_hits(keys, SIZING_TOKENS),
        })
    except Exception as exc:
        result.update({"called": True, "error": f"{type(exc).__name__}:{exc}"})
    return result


def runtime_inventory(root: Path) -> dict[str, Any]:
    sys.path.insert(0, str(root))
    modules: dict[str, Any] = {}
    candidates: dict[str, list[dict[str, Any]]] = {"risk": [], "sizing": []}
    for module_name in MODULES:
        row: dict[str, Any] = {"module": module_name}
        try:
            module = importlib.import_module(module_name)
            row["path"] = str(Path(module.__file__).resolve()) if getattr(module, "__file__", None) else None
            exports: list[dict[str, Any]] = []
            for name in sorted(dir(module)):
                if name.startswith("_"):
                    continue
                value = getattr(module, name)
                lower = name.lower()
                export: dict[str, Any] = {"name": name, "kind": type(value).__name__}
                if inspect.isfunction(value):
                    export.update(deterministic_call(value))
                elif inspect.isclass(value):
                    try:
                        export["signature"] = str(inspect.signature(value))
                    except Exception:
                        export["signature"] = None
                    if issubclass(value, Enum):
                        export["enum_members"] = [member.name for member in value]
                else:
                    export["value"] = safe_value(value)
                exports.append(export)

                search_values = [lower]
                search_values.extend(export.get("output_keys") or [])
                risk_hits = role_hits(search_values, RISK_TOKENS)
                sizing_hits = role_hits(search_values, SIZING_TOKENS)
                candidate = {
                    "module": module_name,
                    "name": name,
                    "kind": export["kind"],
                    "signature": export.get("signature"),
                    "called": export.get("called"),
                    "error": export.get("error"),
                    "risk_hits": risk_hits,
                    "sizing_hits": sizing_hits,
                }
                if risk_hits:
                    candidates["risk"].append(candidate)
                if sizing_hits:
                    candidates["sizing"].append(candidate)
            row["exports"] = exports
            row["import_ok"] = True
        except Exception as exc:
            row.update({"import_ok": False, "error": f"{type(exc).__name__}:{exc}"})
        modules[module_name] = row
    return {"modules": modules, "candidates": candidates}


def classify(ast_rows: list[dict[str, Any]], runtime: dict[str, Any]) -> dict[str, Any]:
    runtime_risk = runtime["candidates"]["risk"]
    runtime_sizing = runtime["candidates"]["sizing"]
    ast_risk = [item for row in ast_rows for item in row["risk_hits"]]
    ast_sizing = [item for row in ast_rows for item in row["sizing_hits"]]

    def verdict(runtime_rows: list[dict[str, Any]], ast_hits: list[str], role: str) -> dict[str, Any]:
        behavior = [row for row in runtime_rows if row.get("called") and not row.get("error")]
        exact = [row for row in behavior if (row.get("risk_hits") if role == "RISK_MODE" else row.get("sizing_hits"))]
        if exact:
            state = "EXACT_BEHAVIOR_CANDIDATE"
        elif runtime_rows:
            state = "SEMANTIC_NAME_CANDIDATE_ONLY"
        elif ast_hits:
            state = "AST_TOKEN_ONLY"
        else:
            state = "TRUE_ABSENCE_CONFIRMED"
        return {
            "role": role,
            "state": state,
            "runtime_candidate_count": len(runtime_rows),
            "behavior_candidate_count": len(exact),
            "ast_hit_count": len(ast_hits),
            "runtime_candidates": runtime_rows,
            "ast_hits": ast_hits[:100],
            "minimal_adapter_allowed": state == "TRUE_ABSENCE_CONFIRMED",
        }

    return {
        "RISK_MODE": verdict(runtime_risk, ast_risk, "RISK_MODE"),
        "SIZING_POLICY": verdict(runtime_sizing, ast_sizing, "SIZING_POLICY"),
    }


def run(root: Path) -> dict[str, Any]:
    package = root / "backend" / "trade_methods"
    ast_rows = [ast_inventory(path) for path in sorted(package.glob("*.py"))]
    runtime = runtime_inventory(root)
    roles = classify(ast_rows, runtime)
    unresolved = [name for name, row in roles.items() if row["state"] != "EXACT_BEHAVIOR_CANDIDATE"]
    return {
        "schema_version": "zel.trade_methods.risk_sizing_probe.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": "PASS_RISK_SIZING_EXACT_BEHAVIOR_FOUND" if not unresolved else "HOLD_RISK_SIZING_MINIMAL_ADAPTER_REQUIRED",
        "root": str(root),
        "python_file_count": len(ast_rows),
        "ast_inventory": ast_rows,
        "runtime_inventory": runtime,
        "roles": roles,
        "unresolved_roles": unresolved,
        "next": "BIND_EXACT_BEHAVIOR_ALIAS" if not unresolved else "CREATE_ISOLATED_MINIMAL_RISK_SIZING_ADAPTER_AND_BEHAVIOR_TEST",
        "canonical_strategy_files_mutated": False,
        "canonical_trade_methods_mutated": False,
        "canonical_registry_mutated": False,
        "adapter_created": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "shadow_start_allowed": False,
        "paper_enabled": False,
        "live_enabled": False,
        "action": "hold",
    }


def self_test() -> None:
    assert role_hits(["position_size_pct", "fee_r"], SIZING_TOKENS) == ["position_size_pct"]
    assert "risk" in role_hits(["risk"], RISK_TOKENS)
    assert safe_value({"x": 1.0}) == {"x": 1.0}
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.out:
        parser.error("--out required")
    result = run(Path(args.root).resolve())
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "unresolved_roles": result["unresolved_roles"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
