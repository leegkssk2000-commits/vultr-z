from __future__ import annotations

import json

from backend.tools.strategy11_gemini_v3_2 import (
    REVIEW_ONLY,
    SAFETY,
    build_plan,
    build_profiles,
    stable_sha,
    validate_response,
)

STRATEGIES = [
    "alpha_combo", "anchor_vwap_trend", "bb_revert", "break_and_continue",
    "ema_ribbon_scalp", "fvg_revert", "grid_rebalance", "keltner_trend",
    "liquidity_sweep", "mfi_rsi_div", "obv_trend", "pivot_reversal",
    "range_fade", "rbreaker_like", "rsi_swing_fail", "scalp_snap",
    "session_bias", "squeeze_break", "sr_levels", "supertrend_pullback",
    "trend_ma_macd", "trend_rider", "turtle_trend", "vol_spike_fade",
    "vwap_revert",
]


def registry() -> dict:
    rows = []
    for sid in STRATEGIES:
        rows.append({
            "strategy_id": sid,
            "family": "trend_following" if "trend" in sid or sid == "trend_ma_macd" else "mean_reversion",
            "config_injectable": True,
            "safe_internal_fields": [
                {"field": "max_chase_dist_atr", "axis": "VOLATILITY_ENTRY", "base_value": 1.0, "relaxed_value": 1.15, "tightened_value": 0.85},
                {"field": "rsi_len", "axis": "MOMENTUM_ENTRY", "base_value": 14, "relaxed_value": 12, "tightened_value": 16},
                {"field": "reclaim_atr_min", "axis": "STRUCTURE_ENTRY", "base_value": 0.1, "relaxed_value": 0.085, "tightened_value": 0.115},
                {"field": "stop_atr_mult", "axis": "EXIT", "base_value": 1.5, "relaxed_value": 1.7, "tightened_value": 1.3},
            ],
        })
    return {"strategy_count": 25, "registry_sha256": "r" * 64, "rows": rows}


def result(strategy_id: str, trades: int) -> dict:
    return {
        "strategy_id": strategy_id,
        "control": {
            "strategy_id": strategy_id,
            "variant_id": "NO_CHANGE_CONTROL",
            "trade_count": trades,
            "win_rate_pct": 50.0,
            "net_return_pct_sum": 1.0,
            "net_profit_factor": 1.2,
            "payoff_ratio": 1.1,
            "max_drawdown_pct": 1.0,
            "positive_window_count": 4,
            "opportunity_diagnostics": {"hold_reasons": {f"{strategy_id}_no_setup": 10}},
        },
        "variants": [],
    }


def main() -> None:
    reg = registry()
    ledger = {
        "rows": [
            {"strategy_id": sid, "tested_candidate_ids": ["INT3_MAX_CHASE_DIST_ATR_RELAX"] if sid == "trend_ma_macd" else []}
            for sid in STRATEGIES if sid != "alpha_combo"
        ]
    }
    results = {sid: result(sid, 12 if sid == "trend_ma_macd" else 0) for sid in STRATEGIES if sid != "alpha_combo"}
    profiles, catalogs = build_profiles(reg, ledger, results, 10)
    assert len(profiles) == 24
    assert "GEMV32_MAX_CHASE_DIST_ATR_TIGHT" not in catalogs["trend_ma_macd"]
    assert catalogs["supertrend_pullback"] == {}
    assert catalogs["trend_rider"] == {}
    selected_strategy = next(sid for sid in catalogs if catalogs[sid] and sid not in REVIEW_ONLY)
    candidate_id = next(iter(catalogs[selected_strategy]))
    reviews = []
    for profile in profiles:
        sid = profile["strategy_id"]
        if sid == selected_strategy:
            reviews.append({
                "strategy_id": sid,
                "verdict": "SELECT_REPLAY",
                "selected_candidate_id": candidate_id,
                "causal_reason": "fixture",
                "internal_evidence_refs": ["no_setup"],
                "video_source_indexes": [1, 2],
                "expected_metric_effect": "more valid entries",
                "falsification_test": "A/B parity and economics",
                "overfit_risk": "LOW",
            })
        elif sid in REVIEW_ONLY:
            reviews.append({"strategy_id": sid, "verdict": "NEW_CHILD_REQUIRED", "selected_candidate_id": None})
        else:
            reviews.append({"strategy_id": sid, "verdict": "NO_ACTION", "selected_candidate_id": None})
    response = {
        "status": "PASS",
        "strategy_reviews": reviews,
        "alpha_fresh_only": {"strategy_id": "alpha_combo", "authority": "TIME54_TIME60_W1_FRESH_ONLY", "hypotheses": []},
    }
    normalized, selected = validate_response(response, profiles, catalogs, 16)
    assert len(normalized) == 24 and len(selected) == 1
    plan = build_plan(selected, profiles, stable_sha(response))
    assert plan["state"] == "PASS_GEMINI_V3_2_PLAN"
    assert plan["candidate_count"] == 1
    assert plan["active_strategy_ids"] == [selected_strategy]
    for key, value in SAFETY.items():
        assert plan[key] == value
    invalid = json.loads(json.dumps(response))
    target = next(row for row in invalid["strategy_reviews"] if row["strategy_id"] == "supertrend_pullback")
    target.update({"verdict": "SELECT_REPLAY", "selected_candidate_id": "BAD"})
    try:
        validate_response(invalid, profiles, catalogs, 16)
    except ValueError as exc:
        assert "REVIEW_ONLY_REPLAY_FORBIDDEN" in str(exc)
    else:
        raise AssertionError("review-only replay was not rejected")
    print("PASS_STRATEGY11_GEMINI_V3_2_FIXTURE")


if __name__ == "__main__":
    main()
