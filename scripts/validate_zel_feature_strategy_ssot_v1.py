#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from statistics import fmean


def load_module():
    path = Path(__file__).resolve().parents[1] / "backend/research/zel_feature_strategy_ssot_v1.py"
    spec = importlib.util.spec_from_file_location("zel_feature_strategy_ssot_v1", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load SSOT")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def trend(module, count: int, start: float, step: float, timeframe_ms: int, end_ts: int, volume: float = 100.0):
    bars = []
    price = start
    first_ts = end_ts - (count - 1) * timeframe_ms
    for index in range(count):
        close = price + step
        bars.append(module.Bar(
            ts=first_ts + index * timeframe_ms,
            open=price,
            high=max(price, close) + 0.1,
            low=min(price, close) - 0.1,
            close=close,
            volume=volume,
        ))
        price = close
    return bars


def independent_true_ranges(bars):
    values = []
    for index, bar in enumerate(bars):
        previous_close = bars[index - 1].close if index else bar.close
        values.append(max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close)))
    return values


def assert_close(left: float, right: float) -> None:
    assert math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12), (left, right)


def main() -> None:
    module = load_module()
    config = module.StrategyConfig()
    end_ts = 1_800_000_000_000
    regime = trend(module, 30, 100.0, 0.30, module.FIFTEEN_MIN_MS, end_ts)
    setup = trend(module, 30, 108.0, 0.03, module.FIVE_MIN_MS, end_ts)
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
    assert features_a.feature_schema_sha256 == module.FEATURE_SCHEMA_SHA256

    regime_window = regime[-config.regime_lookback:]
    setup_required = max(config.breakout_lookback + 1, 15)
    setup_window = setup[-setup_required:]
    history = setup_window[-(config.breakout_lookback + 1):-1]
    expected_atr = fmean(independent_true_ranges(setup_window)[-14:])
    expected_efficiency = abs(regime_window[-1].close - regime_window[0].close) / sum(
        abs(regime_window[index].close - regime_window[index - 1].close)
        for index in range(1, len(regime_window))
    )
    expected_breakout_reference = max(bar.high for bar in history)
    expected_volume_reference = fmean(bar.volume for bar in history)

    assert_close(features_a.atr, expected_atr)
    assert_close(features_a.directional_efficiency, expected_efficiency)
    assert_close(features_a.regime_return, regime_window[-1].close / regime_window[0].close - 1.0)
    assert_close(features_a.breakout_reference, expected_breakout_reference)
    assert_close(features_a.breakout_distance_atr, (setup_window[-1].close - expected_breakout_reference) / expected_atr)
    assert_close(features_a.expansion_atr, (setup_window[-1].close - setup_window[-1].open) / expected_atr)
    assert_close(features_a.relative_volume, setup_window[-1].volume / expected_volume_reference)

    intent_a = module.decide_momentum_long("BTCUSDT", regime, setup, config, 0.1316910918)
    intent_b = module.decide_momentum_long("BTCUSDT", tuple(regime), tuple(setup), config, 0.1316910918)
    assert intent_a.side == "long", intent_a
    assert intent_a == intent_b
    assert intent_a.sha256() == intent_b.sha256()
    assert intent_a.strategy_id == module.STRATEGY_ID
    assert intent_a.strategy_source_sha256 == module.STRATEGY_SOURCE_SHA256
    assert intent_a.feature_schema_sha256 == module.FEATURE_SCHEMA_SHA256
    assert intent_a.invalidation_price < intent_a.entry_reference < intent_a.target_price
    assert_close(intent_a.planned_risk, intent_a.entry_reference - intent_a.invalidation_price)
    assert_close(intent_a.quality_score, intent_a.expected_move_to_cost * features_a.relative_volume)

    low_volume = list(setup)
    bar = low_volume[-1]
    low_volume[-1] = module.Bar(bar.ts, bar.open, bar.high, bar.low, bar.close, 50.0)
    assert module.decide_momentum_long("BTCUSDT", regime, low_volume, config, 0.1316910918).reason == "RELATIVE_VOLUME_TOO_LOW"

    flat = trend(module, 30, 100.0, 0.0, module.FIFTEEN_MIN_MS, end_ts)
    assert module.decide_momentum_long("BTCUSDT", flat, setup, config, 0.1316910918).reason == "REGIME_NOT_DIRECTIONAL_UP"

    future_mutation = list(setup)
    future_mutation.append(module.Bar(
        ts=setup[-1].ts + module.FIVE_MIN_MS,
        open=500.0,
        high=600.0,
        low=400.0,
        close=550.0,
        volume=1_000_000.0,
    ))
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

    gap = list(setup)
    prior = gap[-3]
    changed = gap[-2]
    gap[-2] = module.Bar(prior.ts + 400_000, changed.open, changed.high, changed.low, changed.close, changed.volume)
    try:
        module.compute_features(regime, gap, config)
    except ValueError as exc:
        assert "timestamp discontinuity" in str(exc)
    else:
        raise AssertionError("5m gap must fail closed")

    misaligned_regime = [
        module.Bar(bar.ts - module.FIFTEEN_MIN_MS, bar.open, bar.high, bar.low, bar.close, bar.volume)
        for bar in regime
    ]
    try:
        module.compute_features(misaligned_regime, setup, config)
    except ValueError as exc:
        assert "alignment mismatch" in str(exc)
    else:
        raise AssertionError("stale 15m regime must fail closed")

    latest_closed_regime = [
        module.Bar(bar.ts - module.FIVE_MIN_MS, bar.open, bar.high, bar.low, bar.close, bar.volume)
        for bar in regime
    ]
    assert module.compute_features(latest_closed_regime, setup, config).signal_ts == setup[-1].ts

    print("PASS_ZEL_FEATURE_STRATEGY_SSOT_V1")


if __name__ == "__main__":
    main()
