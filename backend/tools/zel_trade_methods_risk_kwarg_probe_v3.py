from __future__ import annotations

import argparse
import importlib
import inspect
import json
import math
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_TRADE_METHODS_RISK_KWARG_PROBE_V3"
MODES = (None, "conservative", "low", "balanced", "medium", "aggressive", "high", "high_risk")
RISK_KEYS = ("risk_mode", "risk_unit_r", "risk_multiplier", "loss_cap_r", "drawdown", "max_loss", "risk")
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


def safe(value: Any, depth: int = 0) -> Any:
    if depth > 5:
        return "<depth_limit>"
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Enum):
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


def risk_fields(value: Any) -> dict[str, Any]:
    flat = flatten(safe(value))
    return {key: item for key, item in flat.items() if any(token in key for token in RISK_KEYS)}


def invoke(function: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        output = function(**kwargs)
        return {"ok": True, "output": safe(output), "risk_fields": risk_fields(output)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}"}


def scalar(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def changed_fields(cases: list[dict[str, Any]]) -> list[str]:
    successful = [case for case in cases if case.get("ok")]
    keys = sorted({key for case in successful for key in case.get("risk_fields", {})})
    changed: list[str] = []
    for key in keys:
        values = {json.dumps(case.get("risk_fields", {}).get(key), sort_keys=True, ensure_ascii=False) for case in successful}
        if len(values) > 1:
            changed.append(key)
    return changed


def internal_probe(policy: Any) -> dict[str, Any]:
    normalize = getattr(policy, "_normalize_risk_mode", None)
    unit = getattr(policy, "_risk_unit_from_mode", None)
    result: dict[str, Any] = {
        "normalize_present": callable(normalize),
        "risk_unit_present": callable(unit),
        "normalize_signature": str(inspect.signature(normalize)) if callable(normalize) else None,
        "risk_unit_signature": str(inspect.signature(unit)) if callable(unit) else None,
        "cases": [],
    }
    if not callable(normalize) or not callable(unit):
        return result
    for mode in MODES:
        row: dict[str, Any] = {"input": mode}
        try:
            normalized = normalize(mode)
            row["normalized"] = safe(normalized)
            row["normalized_type"] = type(normalized).__name__
            try:
                risk_unit = unit(normalized)
                row["risk_unit_ok"] = True
                row["risk_unit"] = safe(risk_unit)
            except Exception as exc:
                row["risk_unit_ok"] = False
                row["risk_unit_error"] = f"{type(exc).__name__}:{exc}"
        except Exception as exc:
            row["normalize_error"] = f"{type(exc).__name__}:{exc}"
        result["cases"].append(row)
    numeric = [scalar(row.get("risk_unit")) for row in result["cases"] if row.get("risk_unit_ok")]
    numeric = [value for value in numeric if value is not None]
    result["distinct_risk_unit_count"] = len(set(numeric))
    result["internal_behavior_proved"] = len(set(numeric)) >= 2
    return result


def resolver_probe(resolver: Any) -> dict[str, Any]:
    functions: list[tuple[str, Any]] = []
    for name in ("h74tm8_resolve_trade_method", "h74tm8_resolve_combo"):
        function = getattr(resolver, name, None)
        if callable(function):
            functions.append((name, function))
    rows: list[dict[str, Any]] = []
    for name, function in functions:
        cases: list[dict[str, Any]] = []
        signature = inspect.signature(function)
        for mode in MODES:
            kwargs: dict[str, Any] = {"strategy": "trend_ma_macd", "skills": (), "cost_r": 0.1}
            if mode is not None:
                kwargs["risk_mode"] = mode
            case = {"mode": mode, "kwargs": kwargs, **invoke(function, **kwargs)}
            cases.append(case)
        changed = changed_fields(cases)
        rows.append({
            "name": name,
            "signature": str(signature),
            "accepts_var_kwargs": any(p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values()),
            "cases": cases,
            "changed_risk_fields": changed,
            "hidden_kwarg_behavior_proved": bool(changed),
        })
    return {
        "functions": rows,
        "hidden_kwarg_behavior_proved": any(row["hidden_kwarg_behavior_proved"] for row in rows),
    }


def run(root: Path) -> dict[str, Any]:
    sys.path.insert(0, str(root))
    policy = importlib.import_module("backend.trade_methods.policy")
    resolver = importlib.import_module("backend.trade_methods.resolver")
    internal = internal_probe(policy)
    resolved = resolver_probe(resolver)

    if resolved["hidden_kwarg_behavior_proved"]:
        state = "PASS_EXISTING_RISK_MODE_KWARG_ALIAS"
        next_step = "CREATE_READ_ONLY_RISK_MODE_ALIAS_CONTRACT_AND_REPLAY_FIXTURE"
        adapter_required = False
    elif internal.get("internal_behavior_proved"):
        state = "HOLD_RISK_MODE_EXPORT_ADAPTER_REQUIRED"
        next_step = "CREATE_ISOLATED_EXPORT_ADAPTER_USING_EXISTING_INTERNAL_RISK_POLICY"
        adapter_required = True
    else:
        state = "HOLD_RISK_MODE_POLICY_ADAPTER_REQUIRED"
        next_step = "EXTRACT_SSOT_RISK_POLICY_THEN_CREATE_ISOLATED_ADAPTER"
        adapter_required = True

    return {
        "schema_version": "zel.trade_methods.risk_kwarg_probe.v3",
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "internal_policy": internal,
        "resolver": resolved,
        "risk_mode_adapter_required": adapter_required,
        "next": next_step,
        **SAFE,
    }


def self_test() -> None:
    cases = [
        {"ok": True, "risk_fields": {"risk_unit_r": 0.5}},
        {"ok": True, "risk_fields": {"risk_unit_r": 1.0}},
    ]
    assert changed_fields(cases) == ["risk_unit_r"]
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
    print(json.dumps({"state": result["state"], "adapter_required": result["risk_mode_adapter_required"], "next": result["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
