from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from typing import Any, Mapping


@dataclass(frozen=True)
class ChildFeatureSnapshot:
    parent: Any
    axis_name: str
    axis_value: float | int | str
    axis_reference: float | int | str
    axis_pass: bool
    feature_sha: str


def digest_feature(
    *, parent: Any, child_id: str, axis_name: str, axis_value: Any,
    axis_reference: Any, axis_pass: bool,
) -> str:
    body = {
        "child_id": child_id,
        "parent_feature_sha": str(parent.feature_sha),
        "signal_ts": int(parent.signal_ts),
        "axis_name": axis_name,
        "axis_value": axis_value,
        "axis_reference": axis_reference,
        "axis_pass": bool(axis_pass),
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def child_feature(
    *, parent: Any, child_id: str, axis_name: str, axis_value: Any,
    axis_reference: Any, axis_pass: bool,
) -> ChildFeatureSnapshot:
    return ChildFeatureSnapshot(
        parent=parent,
        axis_name=axis_name,
        axis_value=axis_value,
        axis_reference=axis_reference,
        axis_pass=bool(axis_pass),
        feature_sha=digest_feature(
            parent=parent, child_id=child_id, axis_name=axis_name,
            axis_value=axis_value, axis_reference=axis_reference, axis_pass=axis_pass,
        ),
    )


def positive_number(row: Mapping[str, Any], key: str) -> float:
    try:
        value = float(row[key])
    except Exception as exc:
        raise ValueError(f"BAR_{key.upper()}_INVALID") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"BAR_{key.upper()}_NONPOSITIVE_OR_NAN")
    return value


def wrap_intent(
    parent: Any,
    feature: ChildFeatureSnapshot,
    *,
    child_id: str,
    policy_schema: str,
    entry_suffix: str,
    pass_reason: str,
    block_reason: str,
) -> Any:
    return replace(
        parent,
        schema_version=policy_schema,
        strategy_id=child_id,
        feature_sha=feature.feature_sha,
        entry_rule=parent.entry_rule + ";" + entry_suffix,
        no_trade=bool(parent.no_trade or not feature.axis_pass),
        reason_codes=parent.reason_codes + ((pass_reason if feature.axis_pass else block_reason),),
    )


def frozen_parent_geometry(intent: Any) -> dict[str, Any]:
    value = asdict(intent)
    for key in ("schema_version", "strategy_id", "feature_sha", "entry_rule", "no_trade", "reason_codes"):
        value.pop(key, None)
    return value
