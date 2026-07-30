from __future__ import annotations

import json

from backend.tools.strategy11_bounded_internal_mutation_v3 import (
    build_candidates,
    mutation_domain,
    semantic_role,
    side_scope,
)


def field(name: str, axis: str, base: float | int, relaxed: float | int, tightened: float | int) -> dict[str, object]:
    return {
        "field": name,
        "axis": axis,
        "base_value": base,
        "relaxed_value": relaxed,
        "tightened_value": tightened,
        "one_axis_only": True,
    }


def main() -> int:
    row = {
        "strategy_id": "fixture_strategy",
        "family": "mean_reversion",
        "config_injectable": True,
        "safe_internal_fields": [
            field("fail_band_break_atr", "STRUCTURE_ENTRY", 0.24, 0.20, 0.28),
            field("add_pullback_atr", "STRUCTURE_ENTRY", 0.42, 0.48, 0.36),
            field("scale_in_progress_min", "MOMENTUM_ENTRY", 0.35, 0.30, 0.40),
            field("beam_body_ratio_min", "STRUCTURE_ENTRY", 0.4, 0.34, 0.46),
            field("atr_len", "VOLATILITY_ENTRY", 14, 12, 16),
            field("rsi_ob", "MOMENTUM_ENTRY", 70.0, 74.0, 66.0),
            field("rsi_os", "MOMENTUM_ENTRY", 30.0, 34.5, 25.5),
            field("min_atr_pct", "VOLATILITY_ENTRY", 0.12, 0.102, 0.138),
            field("reclaim_atr_min", "STRUCTURE_ENTRY", 0.10, 0.085, 0.115),
        ],
    }
    assert mutation_domain("fail_band_break_atr") == "FAILURE_EXIT"
    assert mutation_domain("add_pullback_atr") == "POSITION_MANAGEMENT"
    assert mutation_domain("scale_in_progress_min") == "POSITION_MANAGEMENT"
    assert side_scope("rsi_ob") == "SHORT_ONLY"
    assert side_scope("rsi_os") == "LONG_ONLY"
    assert semantic_role("beam_body_ratio_min") == "BEAM_CONFIRMATION"
    assert semantic_role("atr_len") == "INDICATOR_PERIOD"
    assert semantic_role("rsi_os") == "ENTRY_TRIGGER"
    assert semantic_role("min_atr_pct") == "REGIME_GATE"
    candidates = build_candidates(row, "A_ENTRY_LIVENESS_REPAIR", set(), 2)
    assert [item["field"] for item in candidates] == ["reclaim_atr_min", "min_atr_pct"]
    assert [item["semantic_role"] for item in candidates] == ["ENTRY_TRIGGER", "REGIME_GATE"]
    assert all(item["mutation_domain"] == "ENTRY_LOGIC" for item in candidates)
    assert all(item["side_scope"] != "SHORT_ONLY" for item in candidates)
    excluded = {"fail_band_break_atr", "add_pullback_atr", "scale_in_progress_min", "rsi_ob"}
    assert excluded.isdisjoint({item["field"] for item in candidates})
    tested = {item["candidate_id"] for item in candidates}
    second_cycle = build_candidates(row, "A_ENTRY_LIVENESS_REPAIR", tested, 2)
    assert second_cycle
    assert not tested & {item["candidate_id"] for item in second_cycle}
    print(json.dumps({"state": "PASS_V3_CANDIDATE_ROLE_SIDE_FIXTURE", "first": [item["field"] for item in candidates], "second": [item["field"] for item in second_cycle]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
