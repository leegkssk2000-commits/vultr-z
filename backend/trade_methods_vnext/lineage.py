from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from .types import MethodProfile, MethodRequest


def _normalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _normalize(asdict(value))
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, float):
        if value == 0:
            return 0.0
        return float(f"{value:.12g}")
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def profile_sha256(profile: MethodProfile) -> str:
    return sha256_hex(profile.to_dict())


def input_sha256(request: MethodRequest) -> str:
    return sha256_hex(request.to_dict())


def resolver_trace_id(*, request_hash: str, profile_hash: str, decision_code: str) -> str:
    raw = {"schema": "trade_method_vnext_trace_v1", "request_sha256": request_hash, "profile_sha256": profile_hash, "decision_code": decision_code}
    return f"tmvnext:{sha256_hex(raw)[:32]}"


def output_sha256(payload_without_hash: dict[str, Any]) -> str:
    return sha256_hex(payload_without_hash)
