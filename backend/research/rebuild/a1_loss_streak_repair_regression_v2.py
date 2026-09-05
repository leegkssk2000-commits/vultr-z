from __future__ import annotations

from backend.research.rebuild import a1_loss_streak_repair_regression_v1 as v1

v1.SCHEMA = "zel.a1.loss_streak_repair_regression.v4"
v1.CASES = {
    "trend_rider": {
        "trigger_run_id": 32623644328,
        "parent_policy": "backend/research/rebuild/trend_rider_transition_freshness_child_policy_v1.py",
        "child_policy": "backend/research/rebuild/trend_rider_transition_freshness_atr_expansion_child_policy_v1.py",
        "expected_context_trade_count": 24,
        "expected_loss_cluster_net_bps": -680.7580413522833,
        "loss_keys": [
            ("ETH-USDT", 1787400000000, "long"),
            ("ETH-USDT", 1787418000000, "long"),
            ("ETH-USDT", 1787439600000, "long"),
            ("BTC-USDT", 1787439600000, "long"),
        ],
        "changed_axis": "ATR14_CURRENT_GT_PRIOR_CLOSED_BAR_ON_TRANSITION_FRESHNESS_INCUMBENT",
    },
    "keltner_trend": {
        "trigger_run_id": 32624307572,
        "parent_policy": "backend/research/rebuild/breakout_policy_batch_v1.py",
        "child_policy": "backend/research/rebuild/keltner_trend_ema_spread_expansion_child_policy_v1.py",
        "expected_context_trade_count": 24,
        "expected_loss_cluster_net_bps": -704.9952609009406,
        "loss_keys": [
            ("ETH-USDT", 1787302800000, "long"),
            ("BTC-USDT", 1787317200000, "long"),
            ("ETH-USDT", 1787342400000, "long"),
            ("BTC-USDT", 1787346000000, "long"),
        ],
        "changed_axis": "NORMALIZED_EMA_SPREAD_EXPANDING_VS_PRIOR_CLOSED_BAR",
    },
}

CASES = v1.CASES
SCHEMA = v1.SCHEMA
run = v1.run
self_test = v1.self_test
main = v1.main


if __name__ == "__main__":
    raise SystemExit(main())
