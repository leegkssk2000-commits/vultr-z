from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

VERSION = "STRATEGY11_BOUNDED_INTERNAL_MUTATION_V3"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def native_regimes(family: str) -> list[str]:
    return {
        "trend_following": ["TREND_UP", "TREND_DOWN"],
        "breakout_momentum": ["HIGH_VOL", "TREND_UP", "TREND_DOWN"],
        "mean_reversion": ["RANGE", "LOW_VOL"],
        "market_structure": ["RANGE", "TREND_UP", "TREND_DOWN"],
        "session_volatility": ["HIGH_VOL", "SESSION_ACTIVE"],
        "hybrid": ["TREND_UP", "RANGE", "HIGH_VOL"],
    }.get(family, ["RANGE", "TREND_UP"])


def build_candidates(row: Mapping[str, Any], lane: str, tested: set[str], max_count: int = 2) -> list[dict[str, Any]]:
    if not row.get("config_injectable"):
        return []
    fields = [dict(value) for value in row.get("safe_internal_fields", []) if isinstance(value, Mapping)]
    priority = {"STRUCTURE_ENTRY": 0, "MOMENTUM_ENTRY": 1, "VOLATILITY_ENTRY": 2, "TREND_ENTRY": 3, "LOOKBACK_ENTRY": 4, "SESSION_ENTRY": 5, "GENERIC_ENTRY": 6}
    fields.sort(key=lambda value: (priority.get(str(value["axis"]), 99), str(value["field"])))
    selected: list[dict[str, Any]] = []
    used_axes: set[str] = set()
    for field in fields:
        axis = str(field["axis"])
        if axis in used_axes:
            continue
        relaxed = lane in {"A_ENTRY_LIVENESS_REPAIR", "B_COVERAGE_EXPANSION", "C_DISCOVERY_OPTIMIZATION"}
        value = field["relaxed_value"] if relaxed else field.get("tightened_value")
        if value is None:
            continue
        scope = None if not selected else native_regimes(str(row.get("family")))[0]
        candidate_id = f"INT3_{field['field'].upper()}_{'RELAX' if relaxed else 'TIGHT'}" + (f"_{scope}" if scope else "")
        if candidate_id in tested:
            continue
        candidate = {"candidate_id": candidate_id, "kind": "REGIME_INTERNAL_MUTATION" if scope else "INTERNAL_MUTATION", "axis": f"{axis}:{field['field']}", "field": field["field"], "base_value": field["base_value"], "mutation_value": value, "regime_scope": scope, "family": row.get("family"), "one_axis_only": True, "same_axis_generation_limit": 2, "canonical_mutated": False}
        candidate["candidate_spec_sha256"] = stable_sha(candidate)
        selected.append(candidate)
        used_axes.add(axis)
        if len(selected) >= max_count:
            break
    return selected
