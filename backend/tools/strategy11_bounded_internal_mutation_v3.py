from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

VERSION = "STRATEGY11_BOUNDED_INTERNAL_MUTATION_V3_2"


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


def mutation_domain(field_name: str) -> str:
    name = field_name.lower()
    if (
        name.startswith(("add_", "scale_in_", "reduce_", "max_add", "max_pyramid"))
        or "_add_" in name
        or name.endswith("_add")
        or "pyramiding" in name
        or "adverse_atr_for_dip" in name
    ):
        return "POSITION_MANAGEMENT"
    if name.startswith("fail_") or "failed_" in name or "fake_break_reject" in name:
        return "FAILURE_EXIT"
    if any(token in name for token in ("stop_", "trail_", "target_", "partial_", "breakeven", "base_rr", "beam_rr", "runner_")):
        return "EXIT_RISK"
    if any(token in name for token in ("size_long", "size_short", "bonus_long", "bonus_short")):
        return "POSITION_SIZING"
    return "ENTRY_LOGIC"


def side_scope(field_name: str) -> str:
    name = field_name.lower()
    short_tokens = ("short", "bear", "rsi_ob", "upper_")
    long_tokens = ("long", "bull", "rsi_os", "lower_")
    short = any(token in name for token in short_tokens)
    long = any(token in name for token in long_tokens)
    if short and not long:
        return "SHORT_ONLY"
    if long and not short:
        return "LONG_ONLY"
    return "NEUTRAL"


def semantic_role(field_name: str) -> str:
    name = field_name.lower()
    domain = mutation_domain(name)
    if domain != "ENTRY_LOGIC":
        return domain
    if name.startswith("beam_") or any(token in name for token in ("body_ratio", "close_location")):
        return "BEAM_CONFIRMATION"
    if name.endswith("_len") or any(token in name for token in ("lookback", "window", "period", "bars")):
        return "INDICATOR_PERIOD"
    if any(token in name for token in ("min_atr_pct", "max_atr_pct", "session", "hour", "weekday")):
        return "REGIME_GATE"
    if any(token in name for token in (
        "reclaim", "break", "pullback", "sweep", "wick", "dist", "chase", "band_over",
        "rsi_os", "rsi_ob", "rsi_reclaim", "mfi_delta", "obv_impulse", "vol_mult",
        "squeeze", "pivot", "support", "resistance", "threshold", "kc_mult", "bb_mult",
        "gap_pct", "hist_impulse", "divergence", "deviation",
    )):
        return "ENTRY_TRIGGER"
    return "ENTRY_SUPPORT"


def role_priority(lane: str) -> dict[str, int]:
    if lane in {"A_ENTRY_LIVENESS_REPAIR", "B_COVERAGE_EXPANSION"}:
        order = ("ENTRY_TRIGGER", "REGIME_GATE", "ENTRY_SUPPORT", "INDICATOR_PERIOD", "BEAM_CONFIRMATION")
    elif lane == "C_DISCOVERY_OPTIMIZATION":
        order = ("ENTRY_TRIGGER", "ENTRY_SUPPORT", "REGIME_GATE", "INDICATOR_PERIOD", "BEAM_CONFIRMATION")
    else:
        order = ("ENTRY_SUPPORT", "ENTRY_TRIGGER", "REGIME_GATE", "BEAM_CONFIRMATION", "INDICATOR_PERIOD")
    return {role: index for index, role in enumerate(order)}


def build_candidates(row: Mapping[str, Any], lane: str, tested: set[str], max_count: int = 2) -> list[dict[str, Any]]:
    if not row.get("config_injectable"):
        return []
    fields = [dict(value) for value in row.get("safe_internal_fields", []) if isinstance(value, Mapping)]
    axis_priority = {
        "STRUCTURE_ENTRY": 0,
        "MOMENTUM_ENTRY": 1,
        "VOLATILITY_ENTRY": 2,
        "TREND_ENTRY": 3,
        "LOOKBACK_ENTRY": 4,
        "SESSION_ENTRY": 5,
        "GENERIC_ENTRY": 6,
    }
    side_rank = {"LONG_ONLY": 0, "NEUTRAL": 1, "SHORT_ONLY": 2}
    role_rank = role_priority(lane)
    allowed_roles = set(role_rank)
    eligible: list[dict[str, Any]] = []
    for field in fields:
        field_name = str(field["field"])
        field["mutation_domain"] = mutation_domain(field_name)
        field["semantic_role"] = semantic_role(field_name)
        field["side_scope"] = side_scope(field_name)
        if field["mutation_domain"] != "ENTRY_LOGIC" or field["semantic_role"] not in allowed_roles:
            continue
        eligible.append(field)
    eligible.sort(key=lambda value: (
        side_rank.get(str(value["side_scope"]), 99),
        role_rank.get(str(value["semantic_role"]), 99),
        axis_priority.get(str(value["axis"]), 99),
        str(value["field"]),
    ))
    selected: list[dict[str, Any]] = []
    used_axes: set[str] = set()
    used_roles: set[str] = set()
    relaxed = lane in {"A_ENTRY_LIVENESS_REPAIR", "B_COVERAGE_EXPANSION", "C_DISCOVERY_OPTIMIZATION"}
    for field in eligible:
        axis = str(field["axis"])
        role = str(field["semantic_role"])
        if axis in used_axes or (role in used_roles and len(eligible) > max_count):
            continue
        value = field["relaxed_value"] if relaxed else field.get("tightened_value")
        if value is None:
            continue
        scope = None if not selected else native_regimes(str(row.get("family")))[0]
        candidate_id = f"INT3_{field['field'].upper()}_{'RELAX' if relaxed else 'TIGHT'}" + (f"_{scope}" if scope else "")
        if candidate_id in tested:
            continue
        candidate = {
            "candidate_id": candidate_id,
            "kind": "REGIME_INTERNAL_MUTATION" if scope else "INTERNAL_MUTATION",
            "axis": f"{axis}:{field['field']}",
            "mutation_domain": field["mutation_domain"],
            "semantic_role": role,
            "side_scope": field["side_scope"],
            "field": field["field"],
            "base_value": field["base_value"],
            "mutation_value": value,
            "regime_scope": scope,
            "family": row.get("family"),
            "one_axis_only": True,
            "same_axis_generation_limit": 2,
            "canonical_mutated": False,
        }
        candidate["candidate_spec_sha256"] = stable_sha(candidate)
        selected.append(candidate)
        used_axes.add(axis)
        used_roles.add(role)
        if len(selected) >= max_count:
            break
    return selected
