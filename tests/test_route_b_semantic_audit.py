from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "q4r3_route_b_semantic_audit.py"
)
SPEC = importlib.util.spec_from_file_location("route_b_audit", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def test_vwap_identity_scores_as_b1() -> None:
    source = """
class Config:
    zscore = 2.0

def strategy(df, state=None, risk_action='hold'):
    vwap = (df.close * df.volume).sum() / df.volume.sum()
    deviation = (df.close.iloc[-1] - vwap) / df.close.std()
    if deviation < -2.0 and df.rsi.iloc[-1] < 30:
        return {'action': 'enter', 'side': 'long'}
    return {'action': 'hold'}
"""
    scope = AUDIT.read_strategy_scope(source)
    result = AUDIT.family_score(scope, "B1_VWAP_DEVIATION_REVERSION")
    assert result["identity"] in {"medium", "strong"}
    assert result["score"] >= 10


def test_structure_reclaim_scores_as_b2() -> None:
    source = """
def strategy(df):
    support = df.low.rolling(20).min().iloc[-1]
    reclaim = df.low.iloc[-1] <= support and df.close.iloc[-1] > support
    rejection = df.close.iloc[-1] > df.open.iloc[-1]
    if reclaim and rejection:
        return {'action': 'enter', 'side': 'long'}
    return {'action': 'hold'}
"""
    scope = AUDIT.read_strategy_scope(source)
    result = AUDIT.family_score(scope, "B2_STRUCTURE_RECLAIM")
    assert result["score"] >= 10


def test_liquidity_sweep_scores_as_b3() -> None:
    source = """
def strategy(df):
    previous_low = df.low.iloc[-10:-1].min()
    sweep = df.low.iloc[-1] < previous_low
    reclaim = df.close.iloc[-1] > previous_low
    wick = df.close.iloc[-1] - df.low.iloc[-1]
    if sweep and reclaim and wick > 0:
        return {'action': 'enter', 'side': 'long'}
    return {'action': 'hold'}
"""
    scope = AUDIT.read_strategy_scope(source)
    result = AUDIT.family_score(scope, "B3_LIQUIDITY_SWEEP_REVERSAL")
    assert result["score"] >= 10


def test_generic_beam_tag_does_not_create_route_b_identity() -> None:
    source = """
def strategy(df):
    long_beam = True
    return {'action': 'hold', 'why': 'beam'}
"""
    scope = AUDIT.read_strategy_scope(source)
    scores = [AUDIT.family_score(scope, family)["score"] for family in AUDIT.FAMILIES]
    assert max(scores) < 8
