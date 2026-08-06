#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    path = Path(__file__).resolve().parents[1] / "backend/research/zel_feature_strategy_ssot_v1.py"
    spec = importlib.util.spec_from_file_location("zel_feature_strategy_ssot_v1", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load SSOT")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def trend(module, count: int, start: float, step: float, timeframe_ms: int, volume: float = 100.0):
    bars = []
    price = start
    for index in range(count):
        close = price + step
        bars.append(module.Bar(
            ts=1_800_000_000_000 + index * timeframe_ms,
            open=price,
            high=max(price, close) + 0.1,
            low=min(price, close) - 0.1,
            close=close,
            volume=volume,
        ))
        price = close
    return bars


def main() -> None:
    module = load_module()
    config = module.StrategyConfig()
    regime = trend(module, 30, 100.0, 0.30, 900_000)
    setup = trend(module, 30, 108.0, 0.03, 300_000)
    last = setup[-1]
    setup[-1] = module.Bar(
        ts=last.ts,
        open=last.open,
        high=last.open + 2.2,
        low=last.open - 0.1,
        close=last.open + 2.0,
        volume=220.0,
    )

    features_a = module.compute_features(regime, setup, config)
    features_b = module.compute_features(tuple(regime), tuple(setup), config)
    assert features_a == features_b
    assert features_a.atr > 0
    assert 0 < features_a.directional_efficiency <= 1
    assert features_a.regime_return > 0
    assert features_a.breakout_distance_atr > 0
    assert features_a.expansion_atr >= config.expansion_atr_min
    assert features_a.relative_volume >= config.relative_volume_min

    intent_a = module.decide_momentum_long("BTCUSDT", regime, setup, config, 0.1316910918)
    intent_b = module.decide_momentum_long("BTCUSDT", tuple(regime), tuple(setup), config, 0.1316910918)
    assert intent_a.side == "long", intent_a
    assert intent_a == intent_b
    assert intent_a.sha256() == intent_b.sha256()
    assert intent_a.invalidation_price < intent_a.entry_reference < intent_a.target_price
    assert intent_a.planned_risk == intent_a.entry_reference - intent_a.invalidation_price
    assert intent_a.quality_score == intent_a.expected_move_to_cost * features_a.relative_volume

    low_volume = list(setup)
    bar = low_volume[-1]
    low_volume[-1] = module.Bar(bar.ts, bar.open, bar.high, bar.low, bar.close, 50.0)
    assert module.decide_momentum_long("BTCUSDT", regime, low_volume, config, 0.1316910918).reason == "RELATIVE_VOLUME_TOO_LOW"

    flat = trend(module, 30, 100.0, 0.0, 900_000)
    assert module.decide_momentum_long("BTCUSDT", flat, setup, config, 0.1316910918).reason == "REGIME_NOT_DIRECTIONAL_UP"

    future_mutation = list(setup)
    future_mutation.append(module.Bar(
        ts=setup[-1].ts + 300_000,
        open=500.0,
        high=600.0,
        low=400.0,
        close=550.0,
        volume=1_000_000.0,
    ))
    # The signal snapshot deliberately excludes the future bar. Recomputing the
    # same closed-bar slice must remain bit-for-bit identical.
    assert module.compute_features(regime, future_mutation[:-1], config) == features_a
    assert module.decide_momentum_long("BTCUSDT", regime, future_mutation[:-1], config, 0.1316910918).sha256() == intent_a.sha256()

    stale = list(setup)
    stale[-1] = module.Bar(stale[-2].ts, stale[-1].open, stale[-1].high, stale[-1].low, stale[-1].close, stale[-1].volume)
    try:
        module.compute_features(regime, stale, config)
    except ValueError as exc:
        assert "timestamps" in str(exc)
    else:
        raise AssertionError("non-increasing timestamps must fail closed")

    print("PASS_ZEL_FEATURE_STRATEGY_SSOT_V1")


if __name__ == "__main__":
    main()
