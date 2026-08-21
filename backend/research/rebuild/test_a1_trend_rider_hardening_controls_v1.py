from backend.research.rebuild.a1_trend_rider_h4_h5_hardening_v1 import (
    net_for,
    one_bar_delay_net_R,
)
from backend.research.rebuild.trend_policy_batch_v1 import TrendPolicyConfig


def test_one_bar_delay_keeps_stop_geometry() -> None:
    bars = []
    for i in range(20):
        bars.append({
            "ts_ms": i * 3_600_000,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1.0,
        })
    # The delayed fill occurs at index 11. Its bar breaches the frozen stop;
    # a stop-free time-return control would incorrectly survive to a later close.
    bars[11].update({"open": 100.0, "high": 110.0, "low": 90.0, "close": 109.0})
    trade = {
        "entry_ts": bars[10]["ts_ms"],
        "exit_ts": bars[12]["ts_ms"],
        "side": "long",
        "realized_cost_bps": 14.0,
    }
    index = {row["ts_ms"]: i for i, row in enumerate(bars)}
    cfg = TrendPolicyConfig(atr_len=3, timeout_bars=3)
    value = one_bar_delay_net_R(trade, bars, index, cfg)
    # With the synthetic flat pre-signal bars ATR=2 and the frozen stop is 97.
    expected = net_for("long", 100.0, 97.0, 14.0) / 100.0
    assert abs(value - expected) < 1e-12
