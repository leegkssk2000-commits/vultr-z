#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

REQUIRED_RECEIPT_KEYS = (
    "strategy_id",
    "source_sha",
    "event_id",
    "feature_ts",
    "signal",
    "invalidation",
)


@dataclass(frozen=True)
class ReplayGuard:
    point_in_time: bool
    lookahead_zero: bool
    cost_model_bound: bool
    completed_bar_only: bool

    def validate(self) -> None:
        if not all(asdict(self).values()):
            raise ValueError("REPLAY_GUARD_NOT_SATISFIED")


@dataclass(frozen=True)
class StrategyBinding:
    strategy_id: str
    implementation_path: str
    source_sha: str
    entrypoint: str


@dataclass(frozen=True)
class StrategyReceipt:
    strategy_id: str
    source_sha: str
    event_id: str
    feature_ts: str
    signal: str
    invalidation: Any
    replay_guard: ReplayGuard

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        missing = [key for key in REQUIRED_RECEIPT_KEYS if payload.get(key) in (None, "")]
        if missing:
            raise ValueError(f"RECEIPT_KEYS_MISSING:{','.join(missing)}")
        self.replay_guard.validate()
        return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_entrypoint(path: Path, preferred: str | None = None) -> tuple[str, Callable[..., Any]]:
    resolved = path.resolve()
    module_suffix = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12]
    module_name = f"zel_strategy_{resolved.stem}_{module_suffix}"
    spec = importlib.util.spec_from_file_location(module_name, resolved)
    if spec is None or spec.loader is None:
        raise ImportError(f"STRATEGY_IMPORT_FAILED:{resolved}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise

    names = [preferred] if preferred else []
    names += ["evaluate", "generate_signal", "signal", "run", "decide"]
    for name in names:
        if name and hasattr(module, name) and callable(getattr(module, name)):
            return name, getattr(module, name)

    candidates = [
        (name, value)
        for name, value in vars(module).items()
        if callable(value)
        and not name.startswith("_")
        and getattr(value, "__module__", None) == module.__name__
    ]
    if len(candidates) == 1:
        return candidates[0]
    raise LookupError(f"ENTRYPOINT_NOT_UNIQUE:{resolved}:{[name for name, _ in candidates]}")


def build_binding(strategy_id: str, implementation_path: str, preferred_entrypoint: str | None = None) -> StrategyBinding:
    path = Path(implementation_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"IMPLEMENTATION_MISSING:{path}")
    entrypoint, _ = resolve_entrypoint(path, preferred_entrypoint)
    return StrategyBinding(
        strategy_id=strategy_id,
        implementation_path=str(path),
        source_sha=sha256_file(path),
        entrypoint=entrypoint,
    )


def invoke(binding: StrategyBinding, *, event_id: str, feature_ts: str, context: dict[str, Any], replay_guard: ReplayGuard) -> StrategyReceipt:
    replay_guard.validate()
    path = Path(binding.implementation_path)
    current_sha = sha256_file(path)
    if current_sha != binding.source_sha:
        raise ValueError("SOURCE_SHA_DRIFT")
    _, entrypoint = resolve_entrypoint(path, binding.entrypoint)
    signature = inspect.signature(entrypoint)
    if len(signature.parameters) == 0:
        raw = entrypoint()
    else:
        raw = entrypoint(context)

    if isinstance(raw, dict):
        signal = raw.get("signal") or raw.get("action") or raw.get("decision") or "hold"
        invalidation = raw.get("invalidation") or raw.get("stop_loss") or raw.get("loss_cap")
    else:
        signal = str(raw)
        invalidation = context.get("invalidation")

    return StrategyReceipt(
        strategy_id=binding.strategy_id,
        source_sha=binding.source_sha,
        event_id=event_id,
        feature_ts=feature_ts,
        signal=str(signal),
        invalidation=invalidation,
        replay_guard=replay_guard,
    )


def load_bindings_from_a3_status(status_path: str | Path) -> list[StrategyBinding]:
    data = json.loads(Path(status_path).read_text(encoding="utf-8"))
    rows = data.get("strategies")
    if not isinstance(rows, list) or len(rows) != 25:
        raise ValueError("A3_STRATEGY_ROWS_INVALID")
    bindings: list[StrategyBinding] = []
    for row in rows:
        strategy_id = str(row.get("strategy_id", "")).strip()
        refs = [str(x) for x in row.get("implementation_refs", []) if str(x).endswith(".py")]
        if not strategy_id or not refs:
            raise ValueError(f"STRATEGY_BINDING_INCOMPLETE:{strategy_id}")
        errors: list[str] = []
        for ref in refs:
            try:
                bindings.append(build_binding(strategy_id, ref))
                break
            except Exception as exc:
                errors.append(f"{ref}:{type(exc).__name__}")
        else:
            raise ValueError(f"NO_RESOLVABLE_ENTRYPOINT:{strategy_id}:{errors}")
    if len({binding.strategy_id for binding in bindings}) != 25:
        raise ValueError("STRATEGY_BINDING_COUNT_NOT_25")
    return bindings
