#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    path = Path(__file__).resolve().parents[1] / "backend/research/momentum_breakout_continuation_v1.py"
    spec = importlib.util.spec_from_file_location("momentum_breakout_continuation_v1", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load candidate")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def bars(module, count, start, step, timeframe_ms, base_volume=100.0):
    out = []
    price = start
    for i in range(count):
        nxt = price + step
        out.append(module.Bar(
            ts=1_700_000_000_000 + i * timeframe_ms,
            open=price,
            high=max(price, nxt) + 0.15,
            low=min(price, nxt) - 0.15,
            close=nxt,
            volume=base_volume,
        ))
        price = nxt
    return out


def main() -> None:
    module = load_module()
    config = module.Config(
        regime_lookback=24,
        directional_efficiency_min=0.35,
        breakout_lookback=12,
        breakout_buffer_atr=0.0,
        expansion_atr_multiple=0.8,
        relative_volume_min=1.3,
        stop_atr_multiple=1.1,
        target_r=1.6,
        max_hold_bars=12,
        expected_move_to_cost_min=2.0,
    )

    regime = bars(module, 30, 100.0, 0.35, 900_000)
    setup = bars(module, 25, 110.0, 0.04, 300_000)
    last = setup[-1]
    setup[-1] = module.Bar(
        ts=last.ts,
        open=last.open,
        high=last.open + 2.2,
        low=last.open - 0.1,
        close=last.open + 2.0,
        volume=220.0,
    )
    decision = module.decide_long(regime, setup, config, 0.1316910918)
    assert decision.action == "long", decision
    assert decision.stop_price < decision.entry_reference < decision.target_price
    assert decision.expected_move_to_cost >= 2.0
    assert decision.relative_volume >= 1.3

    low_volume = list(setup)
    final = low_volume[-1]
    low_volume[-1] = module.Bar(
        ts=final.ts,
        open=final.open,
        high=final.high,
        low=final.low,
        close=final.close,
        volume=80.0,
    )
    decision = module.decide_long(regime, low_volume, config, 0.1316910918)
    assert decision.action == "hold"
    assert decision.reason == "RELATIVE_VOLUME_TOO_LOW"

    flat_regime = bars(module, 30, 100.0, 0.0, 900_000)
    decision = module.decide_long(flat_regime, setup, config, 0.1316910918)
    assert decision.action == "hold"
    assert decision.reason == "REGIME_NOT_DIRECTIONAL_UP"

    try:
        module.decide_long(regime, setup, config, 0.0)
    except ValueError as exc:
        assert "all-in cost" in str(exc)
    else:
        raise AssertionError("zero cost must fail")

    print("PASS_MOMENTUM_BREAKOUT_CONTINUATION_FIXTURES")


if __name__ == "__main__":
    main()
