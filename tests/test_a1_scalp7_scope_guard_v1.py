from backend.research.rebuild.a1_scalp7_scope_guard_v1 import audit_scope


def binding(lane: str, tf: int, source: str) -> dict[str, object]:
    return {
        "lane": lane,
        "decision_timeframe_ms": tf,
        "trade_source_class": source,
        "historical_outcome_selected": False,
    }


def test_legacy_active5_and_micro5_fail_current_scalp7_scope() -> None:
    rows = [
        binding("keltner_holygrail", 1_800_000, "SCALP30_FROZEN"),
        binding("trend_rider", 3_600_000, "LEGACY_ACTIVE5_1H"),
        binding("break_and_continue", 3_600_000, "LEGACY_ACTIVE5_1H"),
        binding("supertrend_pullback", 3_600_000, "LEGACY_ACTIVE5_1H"),
        binding("squeeze_break", 1_800_000, "SCALP30_FROZEN"),
        binding("cross_sectional_mean_reversion", 1_800_000, "SCALP30_FROZEN"),
        binding("micro_edge", 300_000, "MICRO5_RAW"),
    ]
    result = audit_scope(rows)
    assert result["state"] == "HOLD"
    assert result["scope_valid_count"] == 3
    assert result["scope_invalid_count"] == 4


def test_exact_seven_15m30m_bindings_pass_scope_only() -> None:
    rows = [
        binding("keltner_holygrail", 1_800_000, "SCALP30_FROZEN"),
        binding("trend_rider", 900_000, "SCALP15_FROZEN"),
        binding("break_and_continue", 900_000, "SCALP15_FROZEN"),
        binding("supertrend_pullback", 900_000, "SCALP15_FROZEN"),
        binding("squeeze_break", 1_800_000, "SCALP30_FROZEN"),
        binding("cross_sectional_mean_reversion", 1_800_000, "SCALP30_FROZEN"),
        binding("micro_edge", 900_000, "SCALP15_FROZEN"),
    ]
    result = audit_scope(rows)
    assert result["state"] == "PASS"
    assert result["scope_valid_count"] == 7


def test_outcome_selected_binding_fails_even_on_valid_timeframe() -> None:
    row = binding("trend_rider", 900_000, "SCALP15_FROZEN")
    row["historical_outcome_selected"] = True
    result = audit_scope([row])
    assert "HISTORICAL_OUTCOME_SELECTION_FORBIDDEN" in result["rows"][0]["errors"]
