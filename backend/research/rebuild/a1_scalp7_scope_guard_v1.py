from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Mapping

SCHEMA = "zel.a1.scalp7.scope_guard.v1"
ALLOWED_DECISION_TF_MS = {900_000: "15m", 1_800_000: "30m"}
SCALP7_LANES = (
    "keltner_holygrail",
    "trend_rider",
    "break_and_continue",
    "supertrend_pullback",
    "squeeze_break",
    "cross_sectional_mean_reversion",
    "micro_edge",
)
LEGACY_TRADE_SOURCE_CLASSES = {
    "LEGACY_ACTIVE5_1H",
    "LEGACY_G4_G5_CONVEYOR",
    "LEGACY_TRENDRIDER_BROAD",
}


def validate_scope_binding(row: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    lane = str(row.get("lane", ""))
    if lane not in SCALP7_LANES:
        errors.append("UNKNOWN_SCALP7_LANE")
    tf = row.get("decision_timeframe_ms")
    if tf not in ALLOWED_DECISION_TF_MS:
        errors.append("DECISION_TF_NOT_15M_OR_30M")
    source_class = str(row.get("trade_source_class", ""))
    if source_class in LEGACY_TRADE_SOURCE_CLASSES:
        errors.append("LEGACY_TRADE_SOURCE_FORBIDDEN")
    if source_class == "MICRO5_RAW":
        errors.append("MICRO5_NOT_CURRENT_15M30M_SCOREBOARD")
    if bool(row.get("historical_outcome_selected", False)):
        errors.append("HISTORICAL_OUTCOME_SELECTION_FORBIDDEN")
    return errors


def audit_scope(bindings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for binding in bindings:
        lane = str(binding.get("lane", ""))
        if lane in seen:
            raise ValueError(f"DUPLICATE_LANE:{lane}")
        seen.add(lane)
        errors = validate_scope_binding(binding)
        rows.append({"lane": lane, "scope_valid": not errors, "errors": errors})
    missing = sorted(set(SCALP7_LANES) - seen)
    extra = sorted(seen - set(SCALP7_LANES))
    valid = sum(bool(row["scope_valid"]) for row in rows)
    return {
        "schema": SCHEMA,
        "state": "PASS" if not missing and not extra and valid == 7 else "HOLD",
        "expected_lane_count": 7,
        "observed_lane_count": len(bindings),
        "scope_valid_count": valid,
        "scope_invalid_count": len(bindings) - valid,
        "missing_lanes": missing,
        "extra_lanes": extra,
        "rows": rows,
    }
