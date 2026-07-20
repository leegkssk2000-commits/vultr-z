#!/usr/bin/env python3
from __future__ import annotations

import ast
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
ENTRYPOINT_NAMES = ("evaluate", "generate_signal", "signal", "run", "decide")


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
    entrypoint_kind: str = "module_function"


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


def resolve_entrypoint_descriptor(path: Path, preferred: str | None = None) -> tuple[str, str]:
    """Resolve the source-level entrypoint without importing production code.

    This is the A3 static contract boundary. Runtime construction/invocation is
    intentionally deferred to lifecycle/runtime integration gates.
    """
    resolved = path.resolve()
    try:
        tree = ast.parse(resolved.read_text(encoding="utf-8"), filename=str(resolved))
    except Exception as exc:
        raise ValueError(f"STRATEGY_AST_PARSE_FAILED:{resolved}:{type(exc).__name__}") from exc

    preferred_names = tuple(name for name in ([preferred] if preferred else []) if name) + ENTRYPOINT_NAMES
    module_functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
    }
    class_methods: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and not child.name.startswith("_"):
                class_methods.append(f"{node.name}.{child.name}")

    preferred_module = [name for name in preferred_names if name in module_functions]
    preferred_class = [qualified for qualified in class_methods if qualified.rsplit(".", 1)[-1] in preferred_names]
    exact = [(name, "module_function") for name in preferred_module]
    exact += [(name, "class_method") for name in preferred_class]
    exact = list(dict.fromkeys(exact))
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise LookupError(f"ENTRYPOINT_AMBIGUOUS:{resolved}:{[name for name, _ in exact]}")

    public_module = sorted(module_functions)
    public_class = sorted(class_methods)
    fallback = [(name, "module_function") for name in public_module]
    fallback += [(name, "class_method") for name in public_class]
    if len(fallback) == 1:
        return fallback[0]
    raise LookupError(f"ENTRYPOINT_NOT_UNIQUE:{resolved}:{[name for name, _ in fallback]}")


def resolve_runtime_callable(path: Path, entrypoint: str, entrypoint_kind: str) -> Callable[..., Any]:
    if entrypoint_kind != "module_function" or "." in entrypoint:
        raise RuntimeError(f"ENTRYPOINT_REQUIRES_RUNTIME_FACTORY_BINDING:{entrypoint}")
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
    value = getattr(module, entrypoint, None)
    if not callable(value):
        raise LookupError(f"RUNTIME_ENTRYPOINT_MISSING:{resolved}:{entrypoint}")
    return value


def build_binding(strategy_id: str, implementation_path: str, preferred_entrypoint: str | None = None) -> StrategyBinding:
    path = Path(implementation_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"IMPLEMENTATION_MISSING:{path}")
    entrypoint, entrypoint_kind = resolve_entrypoint_descriptor(path, preferred_entrypoint)
    return StrategyBinding(
        strategy_id=strategy_id,
        implementation_path=str(path),
        source_sha=sha256_file(path),
        entrypoint=entrypoint,
        entrypoint_kind=entrypoint_kind,
    )


def invoke(binding: StrategyBinding, *, event_id: str, feature_ts: str, context: dict[str, Any], replay_guard: ReplayGuard) -> StrategyReceipt:
    replay_guard.validate()
    path = Path(binding.implementation_path)
    current_sha = sha256_file(path)
    if current_sha != binding.source_sha:
        raise ValueError("SOURCE_SHA_DRIFT")
    entrypoint = resolve_runtime_callable(path, binding.entrypoint, binding.entrypoint_kind)
    signature = inspect.signature(entrypoint)
    raw = entrypoint() if len(signature.parameters) == 0 else entrypoint(context)

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


def diagnose_bindings_from_a3_status(status_path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(status_path).read_text(encoding="utf-8"))
    rows = data.get("strategies")
    if not isinstance(rows, list) or len(rows) != 25:
        return {"ok": False, "strategy_count": 0, "bindings": [], "failures": [{"error": "A3_STRATEGY_ROWS_INVALID"}]}
    bindings: list[StrategyBinding] = []
    failures: list[dict[str, Any]] = []
    for row in rows:
        strategy_id = str(row.get("strategy_id", "")).strip()
        refs = [str(x) for x in row.get("implementation_refs", []) if str(x).endswith(".py")]
        attempts: list[dict[str, str]] = []
        if not strategy_id or not refs:
            failures.append({"strategy_id": strategy_id, "refs": refs, "error": "STRATEGY_BINDING_INCOMPLETE"})
            continue
        for ref in refs:
            try:
                binding = build_binding(strategy_id, ref)
                bindings.append(binding)
                break
            except Exception as exc:
                attempts.append({"path": ref, "error": f"{type(exc).__name__}:{exc}"})
        else:
            failures.append({"strategy_id": strategy_id, "refs": refs, "attempts": attempts, "error": "NO_RESOLVABLE_ENTRYPOINT"})
    unique_ids = {binding.strategy_id for binding in bindings}
    return {
        "ok": not failures and len(unique_ids) == 25,
        "strategy_count": len(rows),
        "binding_count": len(bindings),
        "bindings": [asdict(binding) for binding in bindings],
        "failures": failures,
    }


def load_bindings_from_a3_status(status_path: str | Path) -> list[StrategyBinding]:
    diagnosis = diagnose_bindings_from_a3_status(status_path)
    if not diagnosis["ok"]:
        raise ValueError("STRATEGY_BINDING_DIAGNOSIS_FAILED:" + json.dumps(diagnosis["failures"], ensure_ascii=False))
    return [StrategyBinding(**row) for row in diagnosis["bindings"]]
