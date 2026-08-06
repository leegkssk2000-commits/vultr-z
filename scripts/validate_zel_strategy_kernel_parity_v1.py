#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.research.zel_feature_strategy_ssot_v1 import (  # noqa: E402
    Bar,
    FIFTEEN_MIN_MS,
    FIVE_MIN_MS,
    StrategyConfig,
)
from backend.research.zel_strategy_intent_adapters_v1 import (  # noqa: E402
    MarketSnapshot,
    paper_dry_run,
    replay_dry_run,
)


def trend(count: int, start: float, step: float, timeframe_ms: int, end_ts: int, volume: float = 100.0):
    bars = []
    price = start
    first_ts = end_ts - (count - 1) * timeframe_ms
    for index in range(count):
        close = price + step
        bars.append(Bar(
            ts=first_ts + index * timeframe_ms,
            open=price,
            high=max(price, close) + 0.1,
            low=min(price, close) - 0.1,
            close=close,
            volume=volume,
        ))
        price = close
    return bars


def build_snapshots():
    end_ts = 1_800_000_000_000
    regime = trend(30, 100.0, 0.30, FIFTEEN_MIN_MS, end_ts)
    setup = trend(30, 108.0, 0.03, FIVE_MIN_MS, end_ts)
    last = setup[-1]
    setup[-1] = Bar(last.ts, last.open, last.open + 2.2, last.open - 0.1, last.open + 2.0, 220.0)

    positive = MarketSnapshot("BTCUSDT", tuple(regime), tuple(setup), 0.1316910918)
    low_volume = list(setup)
    bar = low_volume[-1]
    low_volume[-1] = Bar(bar.ts, bar.open, bar.high, bar.low, bar.close, 50.0)
    negative = MarketSnapshot("BTCUSDT", tuple(regime), tuple(low_volume), 0.1316910918)
    return positive, negative


def assert_pair(snapshot: MarketSnapshot, config: StrategyConfig, expected_side: str, expected_reason: str) -> None:
    replay = replay_dry_run(snapshot, config)
    paper = paper_dry_run(snapshot, config)

    assert replay.intent == paper.intent
    assert replay.intent_sha256 == paper.intent_sha256 == replay.intent.sha256()
    assert replay.intent.side == expected_side
    assert replay.intent.reason == expected_reason
    assert replay.execution_model == paper.execution_model == "NO_FILL_DRY_RUN"
    assert replay.economic_projection_allowed is False
    assert paper.economic_projection_allowed is False
    assert replay.execution_authority == paper.execution_authority == "NONE"
    assert replay.order_authority == paper.order_authority == "BLOCKED"

    try:
        replay.intent.reason = "MUTATED"
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("DecisionIntent must be immutable")


def main() -> None:
    config = StrategyConfig()
    positive, negative = build_snapshots()
    assert_pair(positive, config, "long", "PASS_MOMENTUM_LONG")
    assert_pair(negative, config, "hold", "RELATIVE_VOLUME_TOO_LOW")

    print(json.dumps({
        "state": "PASS_REPLAY_PAPER_DECISION_INTENT_PARITY",
        "scenarios": 2,
        "parity_pct": 100.0,
        "economic_replay": "BLOCKED_PENDING_FEATURE_CONTRIBUTION",
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
