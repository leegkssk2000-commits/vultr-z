from __future__ import annotations

import json

from backend.tools.strategy11_bounded_internal_mutation_v3 import build_candidates, semantic_role


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
            field("beam_body_ratio_min", "STRUCTURE_ENTRY", 0.4, 0.34, 0.46),
            field("atr_len", "VOLATILITY_ENTRY", 14, 12, 16),
            field("rsi_os", "MOMENTUM_ENTRY", 30.0, 34.5, 25.5),
            field("min_atr_pct", "VOLATILITY_ENTRY", 0.12, 0.102, 0.138),
            field("reclaim_atr_min", "STRUCTURE_ENTRY", 0.10, 0.085, 0.115),
        ],
    }
    assert semantic_role("beam_body_ratio_min") == "BEAM_CONFIRMATION"
    assert semantic_role("atr_len") == "INDICATOR_PERIOD"
    assert semantic_role("rsi_os") == "ENTRY_TRIGGER"
    assert semantic_role("min_atr_pct") == "REGIME_GATE"
    candidates = build_candidates(row, "A_ENTRY_LIVENESS_REPAIR", set(), 2)
    assert [item["field"] for item in candidates] == ["reclaim_atr_min", "rsi_os"] or [item["field"] for item in candidates] == ["rsi_os", "reclaim_atr_min"]
    assert all(item["semantic_role"] == "ENTRY_TRIGGER" for item in candidates) is False, "distinct semantic role gate must retain a second role when available"
    # The first candidate must be a real entry trigger; beam and indicator-period fields must not lead Lane A.
    assert candidates[0]["semantic_role"] == "ENTRY_TRIGGER"
    assert candidates[0]["field"] not in {"beam_body_ratio_min", "atr_len"}
    second_cycle = build_candidates(row, "A_ENTRY_LIVENESS_REPAIR", {item["candidate_id"] for item in candidates}, 2)
    assert second_cycle
    assert not {item["candidate_id"] for item in candidates} & {item["candidate_id"] for item in second_cycle}
    print(json.dumps({"state": "PASS_V3_CANDIDATE_PRIORITY_FIXTURE", "first": [item["field"] for item in candidates], "second": [item["field"] for item in second_cycle]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
