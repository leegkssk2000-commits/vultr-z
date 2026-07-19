#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping

ADAPTER_VERSION = "r7a3c2_strategy25_canonical_shared_adapter_v1"
REQUIRED_RECEIPT_KEYS = (
    "strategy_id",
    "source_sha",
    "event_id",
    "feature_ts",
    "signal",
    "invalidation",
)
REQUIRED_REPLAY_GUARDS = ("point_in_time", "lookahead_zero", "cost_model_bound")


class StrategyAdapterError(ValueError):
    pass


@dataclass(frozen=True)
class StrategyBinding:
    strategy_id: str
    source_sha: str
    entrypoint_ref: str

    def validate(self) -> None:
        if not self.strategy_id.strip():
            raise StrategyAdapterError("strategy_id_missing")
        if len(self.source_sha.strip()) not in (40, 64):
            raise StrategyAdapterError(f"source_sha_invalid:{self.strategy_id}")
        if ":" not in self.entrypoint_ref:
            raise StrategyAdapterError(f"entrypoint_ref_invalid:{self.strategy_id}")


@dataclass(frozen=True)
class ReplayContext:
    event_ts: str
    point_in_time: bool
    lookahead_zero: bool
    cost_model_bound: bool
    cost_model_id: str

    def validate(self) -> None:
        if not self.event_ts:
            raise StrategyAdapterError("event_ts_missing")
        if not self.cost_model_id:
            raise StrategyAdapterError("cost_model_id_missing")
        for key in REQUIRED_REPLAY_GUARDS:
            if getattr(self, key) is not True:
                raise StrategyAdapterError(f"replay_guard_failed:{key}")


@dataclass(frozen=True)
class StrategyReceipt:
    strategy_id: str
    source_sha: str
    event_id: str
    feature_ts: str
    signal: str
    invalidation: Any
    entrypoint_ref: str
    replay: Mapping[str, Any]
    adapter_version: str
    receipt_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_result(result: Any) -> tuple[str, Any]:
    if isinstance(result, Mapping):
        signal = result.get("signal")
        invalidation = result.get("invalidation")
    else:
        signal = getattr(result, "signal", None)
        invalidation = getattr(result, "invalidation", None)
    if signal is None:
        raise StrategyAdapterError("strategy_result_signal_missing")
    if invalidation is None:
        raise StrategyAdapterError("strategy_result_invalidation_missing")
    return str(signal), invalidation


class CanonicalStrategy25Adapter:
    """Order-free shared caller for deterministic replay/shadow strategy evaluation."""

    order_authority = "none"
    ledger_write_authority = "none"
    runtime_activation_default = False

    def __init__(
        self,
        bindings: Mapping[str, StrategyBinding],
        entrypoints: Mapping[str, Callable[[Mapping[str, Any]], Any]],
        *,
        expected_count: int = 25,
    ) -> None:
        self.bindings = dict(bindings)
        self.entrypoints = dict(entrypoints)
        if len(self.bindings) != expected_count:
            raise StrategyAdapterError(
                f"binding_count_{len(self.bindings)}_ne_{expected_count}"
            )
        if set(self.bindings) != set(self.entrypoints):
            raise StrategyAdapterError("binding_entrypoint_id_mismatch")
        for strategy_id, binding in self.bindings.items():
            if strategy_id != binding.strategy_id:
                raise StrategyAdapterError(f"binding_key_mismatch:{strategy_id}")
            binding.validate()
            if not callable(self.entrypoints[strategy_id]):
                raise StrategyAdapterError(f"entrypoint_not_callable:{strategy_id}")

    def dispatch(
        self,
        strategy_id: str,
        *,
        event_id: str,
        feature_ts: str,
        payload: Mapping[str, Any],
        replay: ReplayContext,
    ) -> StrategyReceipt:
        if strategy_id not in self.bindings:
            raise StrategyAdapterError(f"unknown_strategy:{strategy_id}")
        if not event_id:
            raise StrategyAdapterError("event_id_missing")
        if not feature_ts:
            raise StrategyAdapterError("feature_ts_missing")
        replay.validate()
        binding = self.bindings[strategy_id]
        result = self.entrypoints[strategy_id](payload)
        signal, invalidation = _normalize_result(result)
        body = {
            "strategy_id": strategy_id,
            "source_sha": binding.source_sha,
            "event_id": event_id,
            "feature_ts": feature_ts,
            "signal": signal,
            "invalidation": invalidation,
            "entrypoint_ref": binding.entrypoint_ref,
            "replay": {
                "event_ts": replay.event_ts,
                "point_in_time": replay.point_in_time,
                "lookahead_zero": replay.lookahead_zero,
                "cost_model_bound": replay.cost_model_bound,
                "cost_model_id": replay.cost_model_id,
            },
            "adapter_version": ADAPTER_VERSION,
        }
        return StrategyReceipt(**body, receipt_hash=_canonical_hash(body))
