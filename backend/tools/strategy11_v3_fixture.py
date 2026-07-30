from __future__ import annotations

import dataclasses
import json

import numpy as np
import pandas as pd

from backend.tools.strategy11_bounded_internal_mutation_v3 import build_candidates
from backend.tools.strategy11_regime_edge_router_v3 import ConfigStrategyWrapper, classify_regime
from backend.tools.strategy11_long_short_observer_v3 import replay


@dataclasses.dataclass
class DemoConfig:
    rsi_os: float = 30.0
    reclaim_atr_min: float = 0.1
    ema_len: int = 20
    long_base_size: float = 0.5


def demo_strategy(df: pd.DataFrame, *, state=None, risk_action="hold", config: DemoConfig | None = None):
    cfg = config or DemoConfig()
    close = float(df["close"].iloc[-1]); prior = float(df["close"].iloc[-2])
    if close > prior * (1.0 + cfg.reclaim_atr_min / 100.0):
        return {"side": "long", "action": "enter", "size": 0.1, "entry": close, "sl": close * 0.99, "tp": close * 1.02, "why": "demo_long"}
    if close < prior * (1.0 - cfg.reclaim_atr_min / 100.0):
        return {"side": "short", "action": "enter", "size": 0.1, "entry": close, "sl": close * 1.01, "tp": close * 0.98, "why": "demo_short"}
    return {"side": None, "action": "hold", "size": 0.0, "entry": close, "sl": close, "tp": close, "why": "demo_hold"}


def frame() -> pd.DataFrame:
    n = 300; close = 100 + np.sin(np.arange(n) / 5.0) * 3 + np.arange(n) * 0.01
    return pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC"), "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1000})


def main() -> int:
    row = {"config_injectable": True, "family": "mean_reversion", "safe_internal_fields": [{"field": "rsi_os", "axis": "MOMENTUM_ENTRY", "base_value": 30.0, "relaxed_value": 34.5, "tightened_value": 25.5}, {"field": "reclaim_atr_min", "axis": "STRUCTURE_ENTRY", "base_value": 0.1, "relaxed_value": 0.085, "tightened_value": 0.115}]}
    candidates = build_candidates(row, "A_ENTRY_LIVENESS_REPAIR", set(), 2)
    assert len(candidates) == 2 and len({row["axis"] for row in candidates}) == 2
    wrapped = ConfigStrategyWrapper(demo_strategy, DemoConfig, "reclaim_atr_min", 0.05, "RANGE")
    data = frame(); assert classify_regime(data.tail(100)) in {"RANGE", "TREND_UP", "TREND_DOWN", "HIGH_VOL", "LOW_VOL", "SESSION_ACTIVE"}
    result = replay(data, wrapped, warmup_bars=60, history_bars=60, cost_bps_per_side=4.0)
    assert result["state"] == "PASS_OBSERVER_ONLY"
    assert result["combined"]["trade_count"] > 0 and result["long"]["trade_count"] > 0 and result["short"]["trade_count"] > 0
    assert wrapped.diagnostics()["counts"]["calls"] > 0
    print(json.dumps({"state": "PASS_STRATEGY11_V3_FIXTURE", "candidates": len(candidates), "trades": result["combined"]["trade_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
