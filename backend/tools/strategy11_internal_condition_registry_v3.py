from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import inspect
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

VERSION = "STRATEGY11_INTERNAL_CONDITION_REGISTRY_V3"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}
EXCLUDED_TOKENS = (
    "size", "qty", "leverage", "pyramid", "add_count", "add_size", "reduce_size",
    "position", "risk_pct", "confidence", "min_bars", "warmup",
    "stop_", "trail_", "target_", "partial_", "runner_", "_rr", "base_rr", "beam_rr",
)


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_SPEC_FAILED:{name}:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def config_class(module: Any) -> type[Any] | None:
    strategy = getattr(module, "strategy", None)
    if callable(strategy):
        parameter = inspect.signature(strategy).parameters.get("config")
        annotation = getattr(parameter, "annotation", inspect._empty) if parameter else inspect._empty
        if isinstance(annotation, type) and dataclasses.is_dataclass(annotation):
            return annotation
    rows = [value for name, value in vars(module).items() if name.endswith("Config") and isinstance(value, type) and dataclasses.is_dataclass(value)]
    return rows[0] if len(rows) == 1 else None


def field_axis(name: str) -> str | None:
    lower = name.lower()
    if any(token in lower for token in EXCLUDED_TOKENS):
        return None
    if any(token in lower for token in ("session", "hour", "minute", "weekday")):
        return "SESSION_ENTRY"
    if any(token in lower for token in ("atr", "vol", "band", "boll", "keltner", "squeeze")):
        return "VOLATILITY_ENTRY"
    if any(token in lower for token in ("rsi", "mfi", "macd", "momentum", "obv", "stoch")):
        return "MOMENTUM_ENTRY"
    if any(token in lower for token in ("ema", "sma", "trend", "slope", "supertrend")):
        return "TREND_ENTRY"
    if any(token in lower for token in ("reclaim", "break", "dist", "chase", "body", "close_location", "pivot", "support", "resistance", "wick", "range")):
        return "STRUCTURE_ENTRY"
    if any(token in lower for token in ("len", "period", "lookback", "window", "bars")):
        return "LOOKBACK_ENTRY"
    if any(token in lower for token in ("min", "max", "threshold", "mult")):
        return "GENERIC_ENTRY"
    return None


def relaxed_value(name: str, value: int | float | bool, fraction: float) -> int | float | bool | None:
    lower = name.lower()
    if isinstance(value, bool):
        return not value if any(token in lower for token in ("require", "confirm", "use_")) else None
    if isinstance(value, int):
        if value <= 1:
            return None
        step = max(1, int(round(abs(value) * fraction)))
        candidate = value + step if any(token in lower for token in ("max", "ob", "overbought", "chase")) else value - step
        return max(2, candidate)
    if not math.isfinite(float(value)) or abs(float(value)) < 1e-12:
        return None
    factor = 1.0 + fraction if any(token in lower for token in ("max", "os", "oversold", "chase")) else 1.0 - fraction
    candidate = float(value) * factor
    if value > 0:
        candidate = max(candidate, 1e-6)
    return round(candidate, 10)


def tightened_value(name: str, value: int | float | bool, fraction: float) -> int | float | bool | None:
    relaxed = relaxed_value(name, value, fraction)
    if relaxed is None or isinstance(value, bool):
        return None
    delta = float(relaxed) - float(value)
    candidate = float(value) - delta
    if isinstance(value, int):
        return max(2, int(round(candidate)))
    if value > 0:
        candidate = max(candidate, 1e-6)
    return round(candidate, 10)


def build_registry(compute_root: Path, policy: Mapping[str, Any]) -> dict[str, Any]:
    registry_path = compute_root / "backend/strategy25/canonical_strategy_registry_v1.json"
    registry = read_json(registry_path)
    rows = [dict(row) for row in registry.get("entries", []) if isinstance(row, Mapping)]
    expected_count = int(policy["strategy_count_expected"])
    if len(rows) != expected_count or registry.get("fail_closed") is not True:
        raise RuntimeError(f"CANONICAL_REGISTRY_INVALID:{len(rows)}")
    fraction = float(policy["internal_mutation"]["fraction"])
    output_rows: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda value: str(value.get("strategy_id"))):
        strategy_id = str(row["strategy_id"])
        engine = dict(row.get("canonical_engine") or {})
        path = compute_root / str(engine.get("implementation_path") or "")
        expected_sha = str(engine.get("source_sha256") or "")
        if not path.is_file() or sha256(path) != expected_sha:
            raise RuntimeError(f"SOURCE_SHA_MISMATCH:{strategy_id}")
        module = load_module(f"s11_v3_registry_{strategy_id}", path)
        cls = config_class(module)
        fields: list[dict[str, Any]] = []
        if cls is not None:
            instance = cls()
            for field in dataclasses.fields(instance):
                value = getattr(instance, field.name)
                if not isinstance(value, (bool, int, float)) or isinstance(value, complex):
                    continue
                axis = field_axis(field.name)
                if axis is None:
                    continue
                relaxed = relaxed_value(field.name, value, fraction)
                tightened = tightened_value(field.name, value, fraction)
                if relaxed is None or relaxed == value:
                    continue
                fields.append({"field": field.name, "axis": axis, "type": type(value).__name__, "base_value": value, "relaxed_value": relaxed, "tightened_value": tightened, "one_axis_only": True})
        injectable = cls is not None and "config" in inspect.signature(getattr(module, "strategy")).parameters
        output_rows.append({"strategy_id": strategy_id, "family": str(policy["family_map"].get(strategy_id, "unknown")), "implementation_path": str(engine.get("implementation_path")), "strategy_source_sha256": expected_sha, "config_class": cls.__name__ if cls else None, "config_injectable": injectable, "safe_internal_fields": fields, "safe_internal_field_count": len(fields), "canonical_mutated": False})
    payload = {"schema_version": "3.0", "version": VERSION, "state": "PASS_INTERNAL_REGISTRY" if all(row["config_injectable"] for row in output_rows) else "HOLD_PARTIAL_CONFIG_INJECTABILITY", "strategy_count": len(output_rows), "injectable_strategy_count": sum(bool(row["config_injectable"]) for row in output_rows), "rows": output_rows, "canonical_registry_sha256": sha256(registry_path), **SAFETY}
    payload["registry_sha256"] = stable_sha(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compute-root", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    payload = build_registry(Path(args.compute_root).resolve(), read_json(Path(args.policy).resolve()))
    write_json(Path(args.out).resolve(), payload)
    print(json.dumps({"state": payload["state"], "strategies": payload["strategy_count"], "injectable": payload["injectable_strategy_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
