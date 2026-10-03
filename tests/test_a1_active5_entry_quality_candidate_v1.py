from backend.research.rebuild import a1_active5_entry_quality_candidate_v1 as candidate


def test_dimensionless_candidate_gates_are_fail_closed_and_scoped():
    assert candidate.gate_reasons("trend_rider", body_atr=0.41, chase_atr=None) == ("SIGNAL_BODY_ATR_ABOVE_MAX",)
    assert candidate.gate_reasons("trend_rider", body_atr=0.39, chase_atr=None) == ()
    assert candidate.gate_reasons("break_and_continue", body_atr=1.09, chase_atr=None) == ("SIGNAL_BODY_ATR_BELOW_MIN",)
    assert candidate.gate_reasons("break_and_continue", body_atr=1.11, chase_atr=None) == ()
    assert candidate.gate_reasons("trend_ma_macd", body_atr=None, chase_atr=0.71) == ("CHASE_ATR_ABOVE_MAX",)
    assert candidate.gate_reasons("trend_ma_macd", body_atr=None, chase_atr=0.69) == ()
    assert candidate.gate_reasons("supertrend_pullback", body_atr=99.0, chase_atr=99.0) == ()
    assert candidate.gate_reasons("keltner_trend", body_atr=0.0, chase_atr=0.0) == ()


def test_candidate_has_no_live_or_promotion_authority():
    assert candidate.AUTH["selection_authority"] is False
    assert candidate.AUTH["promotion_authority"] is False
    assert candidate.AUTH["execution_authority"] == "NONE"
    assert candidate.AUTH["order_authority"] == "BLOCKED"
    assert candidate.AUTH["live_trade_authority"] == "BLOCKED"
    assert candidate.AUTH["protected_mutations"] == 0
