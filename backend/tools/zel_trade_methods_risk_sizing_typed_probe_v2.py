from __future__ import annotations

import argparse
import enum
import hashlib
import importlib
import inspect
import itertools
import json
import math
import sys
import typing
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_TRADE_METHODS_RISK_SIZING_TYPED_PROBE_V2"
MODULES = (
    "backend.trade_methods.types",
    "backend.trade_methods.policy",
    "backend.trade_methods.profiles",
    "backend.trade_methods.resolver",
    "backend.trade_methods",
)
RISK_TOKENS = ("risk", "drawdown", "loss_cap", "stop", "exposure", "leverage", "cost_band", "max_loss", "dd_")
SIZE_TOKENS = ("size", "sizing", "position", "scale_in", "pyramid", "dca", "average_down", "water_add", "allocation", "weight", "notional", "quantity", "qty", "risk_unit")
SAFE = {
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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe(value: Any, depth: int = 0) -> Any:
    if depth > 5:
        return "<depth_limit>"
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, enum.Enum):
        return {"enum": type(value).__name__, "name": value.name, "value": safe(value.value, depth + 1)}
    if is_dataclass(value):
        return safe(asdict(value), depth + 1)
    if isinstance(value, Mapping):
        return {str(k): safe(v, depth + 1) for k, v in list(value.items())[:100]}
    if isinstance(value, (list, tuple, set)):
        return [safe(v, depth + 1) for v in list(value)[:100]]
    if hasattr(value, "__dict__"):
        return {"type": type(value).__name__, "attrs": safe(vars(value), depth + 1)}
    return {"type": type(value).__name__, "repr": repr(value)[:300]}


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.update(flatten(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value[:20]):
            out.update(flatten(item, f"{prefix}[{index}]"))
    else:
        out[prefix.lower()] = value
    return out


def token_fields(flat: Mapping[str, Any], tokens: tuple[str, ...]) -> dict[str, Any]:
    return {key: value for key, value in flat.items() if any(token in key for token in tokens)}


def stable(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def enum_classes(modules: Mapping[str, Any]) -> list[type[enum.Enum]]:
    found: dict[str, type[enum.Enum]] = {}
    for module in modules.values():
        for name in dir(module):
            value = getattr(module, name)
            if inspect.isclass(value) and issubclass(value, enum.Enum):
                found[f"{value.__module__}.{value.__name__}"] = value
    return list(found.values())


def resolve_hint(function: Any, parameter: inspect.Parameter) -> Any:
    try:
        return typing.get_type_hints(function).get(parameter.name, parameter.annotation)
    except Exception:
        return parameter.annotation


def values_for(function: Any, parameter: inspect.Parameter, enums: list[type[enum.Enum]]) -> list[Any]:
    name = parameter.name.lower()
    hint = resolve_hint(function, parameter)
    origin = typing.get_origin(hint)
    args = typing.get_args(hint)
    candidates: list[Any] = []

    enum_hint = None
    if inspect.isclass(hint) and issubclass(hint, enum.Enum):
        enum_hint = hint
    elif origin is typing.Union:
        enum_hint = next((arg for arg in args if inspect.isclass(arg) and issubclass(arg, enum.Enum)), None)
    if enum_hint:
        candidates.extend(list(enum_hint))

    if not candidates and any(token in name for token in ("risk_mode", "mode")):
        for cls in enums:
            if "risk" in cls.__name__.lower() or "mode" in cls.__name__.lower():
                candidates.extend(list(cls))
        candidates.extend(["conservative", "balanced", "aggressive", "high_risk", "low_risk"])
    elif any(token in name for token in ("size_profile", "sizing", "position_size")):
        candidates.extend(["small", "conservative", "balanced", "large", "aggressive", 5.0, 10.0, 15.0])
    elif name in {"strategy_id", "strategy", "strategy_name"}:
        candidates.append("trend_ma_macd")
    elif "method" in name or "profile" == name:
        candidates.extend(["trend", "balanced"])
    elif "skill" in name:
        candidates.extend([(), ("partial30",), ("scale_in",)])
    elif name == "side":
        candidates.extend(["long", "short"])
    elif "cost" in name or "fee" in name or "slippage" in name or "funding" in name:
        candidates.extend([0.0, 0.1, 0.3])
    elif "drawdown" in name or name.startswith("dd"):
        candidates.extend([0.0, -0.5, -1.0])
    elif "risk" in name:
        candidates.extend([0.5, 1.0, 1.5])
    elif "leverage" in name:
        candidates.extend([10.0, 15.0, 20.0])
    elif hint is bool:
        candidates.extend([False, True])
    elif hint is int:
        candidates.append(1)
    elif hint is float:
        candidates.append(0.1)
    elif hint is str:
        candidates.append("fixture")

    if parameter.default is not inspect._empty:
        candidates.insert(0, parameter.default)
    unique: list[Any] = []
    seen: set[str] = set()
    for value in candidates:
        marker = repr(value)
        if marker not in seen:
            seen.add(marker)
            unique.append(value)
    return unique[:8]


def base_kwargs(function: Any, enums: list[type[enum.Enum]]) -> tuple[dict[str, Any], list[str]]:
    kwargs: dict[str, Any] = {}
    unresolved: list[str] = []
    for parameter in inspect.signature(function).parameters.values():
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        values = values_for(function, parameter, enums)
        if values:
            kwargs[parameter.name] = values[0]
        elif parameter.default is inspect._empty:
            unresolved.append(parameter.name)
    return kwargs, unresolved


def call(function: Any, kwargs: Mapping[str, Any]) -> dict[str, Any]:
    try:
        output = function(**dict(kwargs))
        normalized = safe(output)
        return {
            "ok": True,
            "return_type": type(output).__name__,
            "output": normalized,
            "flat": flatten(normalized),
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}"}


def probe_function(module_name: str, name: str, function: Any, enums: list[type[enum.Enum]]) -> dict[str, Any]:
    signature = inspect.signature(function)
    base, unresolved = base_kwargs(function, enums)
    row: dict[str, Any] = {
        "module": module_name,
        "name": name,
        "signature": str(signature),
        "unresolved_required_parameters": unresolved,
        "cases": [],
    }
    if unresolved:
        return row

    base_result = call(function, base)
    row["cases"].append({"label": "BASE", "kwargs": safe(base), **base_result})
    for parameter in signature.parameters.values():
        values = values_for(function, parameter, enums)
        if len(values) < 2:
            continue
        for index, value in enumerate(values[1:6], start=1):
            kwargs = dict(base)
            kwargs[parameter.name] = value
            result = call(function, kwargs)
            row["cases"].append({"label": f"{parameter.name}:{index}", "varied_parameter": parameter.name, "kwargs": safe(kwargs), **result})
    return row


def field_delta(cases: list[dict[str, Any]], tokens: tuple[str, ...]) -> list[dict[str, Any]]:
    successful = [case for case in cases if case.get("ok")]
    if len(successful) < 2:
        return []
    deltas: list[dict[str, Any]] = []
    base = successful[0]
    base_fields = token_fields(base.get("flat") or {}, tokens)
    for case in successful[1:]:
        fields = token_fields(case.get("flat") or {}, tokens)
        changed = sorted({key for key in set(base_fields) | set(fields) if base_fields.get(key) != fields.get(key)})
        if changed:
            deltas.append({
                "from": base["label"],
                "to": case["label"],
                "varied_parameter": case.get("varied_parameter"),
                "changed_fields": changed,
                "base_values": {key: base_fields.get(key) for key in changed},
                "candidate_values": {key: fields.get(key) for key in changed},
            })
    return deltas


def run(root: Path) -> dict[str, Any]:
    sys.path.insert(0, str(root))
    modules: dict[str, Any] = {}
    import_errors: dict[str, str] = {}
    for module_name in MODULES:
        try:
            modules[module_name] = importlib.import_module(module_name)
        except Exception as exc:
            import_errors[module_name] = f"{type(exc).__name__}:{exc}"
    enums = enum_classes(modules)
    probes: list[dict[str, Any]] = []
    for module_name, module in modules.items():
        for name in sorted(dir(module)):
            value = getattr(module, name)
            lower = name.lower()
            if not inspect.isfunction(value):
                continue
            if not any(token in lower for token in ("risk", "size", "sizing", "resolve", "combo", "method")):
                continue
            probes.append(probe_function(module_name, name, value, enums))

    risk_proofs: list[dict[str, Any]] = []
    size_proofs: list[dict[str, Any]] = []
    for probe in probes:
        risk_delta = field_delta(probe["cases"], RISK_TOKENS)
        size_delta = field_delta(probe["cases"], SIZE_TOKENS)
        if risk_delta:
            risk_proofs.append({"module": probe["module"], "name": probe["name"], "signature": probe["signature"], "deltas": risk_delta})
        if size_delta:
            size_proofs.append({"module": probe["module"], "name": probe["name"], "signature": probe["signature"], "deltas": size_delta})

    roles = {
        "RISK_MODE": {
            "state": "EXACT_TYPED_BEHAVIOR_PROVED" if risk_proofs else "TYPED_BEHAVIOR_UNRESOLVED",
            "proof_count": len(risk_proofs),
            "proofs": risk_proofs[:20],
            "minimal_adapter_required": not bool(risk_proofs),
        },
        "SIZING_POLICY": {
            "state": "EXACT_TYPED_BEHAVIOR_PROVED" if size_proofs else "TYPED_BEHAVIOR_UNRESOLVED",
            "proof_count": len(size_proofs),
            "proofs": size_proofs[:20],
            "minimal_adapter_required": not bool(size_proofs),
        },
    }
    unresolved = [name for name, role in roles.items() if role["minimal_adapter_required"]]
    result = {
        "schema_version": "zel.trade_methods.risk_sizing_typed_probe.v2",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": "PASS_RISK_SIZING_TYPED_BEHAVIOR" if not unresolved else "HOLD_MINIMAL_COMPATIBILITY_ADAPTER_REQUIRED",
        "root": str(root),
        "module_import_count": len(modules),
        "module_import_errors": import_errors,
        "enum_inventory": [
            {"module": cls.__module__, "name": cls.__name__, "members": [member.name for member in cls]}
            for cls in enums
        ],
        "function_probe_count": len(probes),
        "successful_case_count": sum(sum(1 for case in probe["cases"] if case.get("ok")) for probe in probes),
        "roles": roles,
        "unresolved_roles": unresolved,
        "next": "CREATE_READ_ONLY_ALIAS_BINDING_CONTRACT" if not unresolved else "CREATE_ISOLATED_MINIMAL_COMPATIBILITY_ADAPTER",
        "probe_sha256": stable({"roles": roles, "imports": sorted(modules), "enum_count": len(enums)}),
        **SAFE,
    }
    return result


def self_test() -> None:
    assert token_fields({"x.risk_unit_r": 1.0, "x.foo": 2}, RISK_TOKENS) == {"x.risk_unit_r": 1.0}
    assert token_fields({"x.size_multiplier": 0.5}, SIZE_TOKENS)
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
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "risk": result["roles"]["RISK_MODE"]["state"],
        "sizing": result["roles"]["SIZING_POLICY"]["state"],
        "next": result["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
