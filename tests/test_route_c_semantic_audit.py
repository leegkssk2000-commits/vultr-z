from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "q4r3_route_c_semantic_audit.py"
)
SPEC = importlib.util.spec_from_file_location("route_c_audit", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def test_squeeze_identity_scores_c1() -> None:
    scope = """
class Config:
    squeeze = True
    compression = True

def strategy(df):
    bandwidth = 0.1
    expansion = 1.4
    breakout = True
    volume = 2.0
    atr = 1.0
"""
    scores = {
        family: AUDIT.family_score(scope, family)["score"]
        for family in AUDIT.FAMILIES
    }
    assert max(scores, key=scores.get) == "C1_SQUEEZE_EXPANSION_BREAKOUT"


def test_donchian_identity_scores_c2() -> None:
    scope = """
class TurtleConfig:
    donchian = 20
    channel_high = 1
    channel_low = 0

def strategy(df):
    rolling_high = 1
    rolling_low = 0
    breakout = True
    atr = 1
"""
    scores = {
        family: AUDIT.family_score(scope, family)["score"]
        for family in AUDIT.FAMILIES
    }
    assert max(scores, key=scores.get) == "C2_DONCHIAN_TURTLE_BREAKOUT"


def test_obv_identity_scores_c3() -> None:
    scope = """
class VolumeConfig:
    relative_volume = 2
    rvol = 2

def strategy(df):
    obv = 1
    on_balance_volume = 1
    volume_impulse = 1
    momentum_continuation = True
    ema = 1
    slope = 1
"""
    scores = {
        family: AUDIT.family_score(scope, family)["score"]
        for family in AUDIT.FAMILIES
    }
    assert max(scores, key=scores.get) == "C3_VOLUME_TREND_CONTINUATION"


def test_mean_reversion_language_penalizes_weak_breakout_identity() -> None:
    scope = "mean_revert reversion oversold overbought fade breakout"
    result = AUDIT.family_score(scope, "C1_SQUEEZE_EXPANSION_BREAKOUT")
    assert result["penalty"] == 6
