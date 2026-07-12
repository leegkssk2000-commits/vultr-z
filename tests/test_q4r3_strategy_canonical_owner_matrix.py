from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_strategy_canonical_owner_matrix.py"
    spec = importlib.util.spec_from_file_location("q4r3_strategy_canonical_owner_matrix_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def full_strategy_text(name: str = "range_fade") -> str:
    return f'''from dataclasses import dataclass
import pandas as pd
@dataclass
class Config:
    atr_len: int = 14

def helper(df):
    return df["close"].ewm(span=20).mean()

def risk(df):
    return df["high"].rolling(14).max()

def strategy(df, state=None, risk_action="hold", market_context=None):
    price = float(df["close"].iloc[-1])
    atr = float((df["high"] - df["low"]).rolling(14).mean().iloc[-1])
    rsi = 40
    regime = "range"
    spread_bps = 2
    position_side = (state or {{}}).get("position_side")
    side = "long" if rsi < 45 else "short"
    sl = price - atr if side == "long" else price + atr
    tp = price + 2 * atr if side == "long" else price - 2 * atr
    return {{"side": side, "action": "enter", "size": 0.1, "entry": price, "sl": sl, "tp": tp, "pyramiding": 1, "why": "{name}", "skill": "long_beam", "confidence": 0.7, "tags": [regime], "indicators": {{"spread_bps": spread_bps, "position_side": position_side}}}}
'''


def test_specialized_canonical_beats_thin_legendary_wrapper() -> None:
    canonical = MODULE.score_module("range_fade", "backend/strategies/range_fade.py", full_strategy_text())
    wrapper = MODULE.score_module(
        "range_fade",
        "backend/legendary_rebuild/strategies/range_fade_legendary.py",
        "from .generic_legendary_templates import legendary_mean_reversion as _impl\n"
        "def strategy(df=None, **kwargs):\n    return _impl('range_fade_legendary', df=df, **kwargs)\n",
    )
    assert canonical.direct_strategy_logic is True
    assert wrapper.generic_wrapper is True
    assert canonical.score > wrapper.score + MODULE.OWNER_CONFIDENCE_MARGIN
    decision = MODULE.owner_decision("range_fade", [canonical, wrapper])
    assert decision["proposed_owner"] == "backend/strategies/range_fade.py"
    assert decision["verdict"] == "PROPOSED_OWNER_CONFIDENT"
    assert decision["alternatives"][0]["role"] == "GENERIC_LEGENDARY_RESERVE"


def test_two_direct_implementations_close_score_require_review() -> None:
    first = MODULE.score_module("trend_rider", "backend/strategies/trend_rider.py", full_strategy_text("trend_rider"))
    second = MODULE.score_module("trend_rider", "backend/legendary_rebuild/strategies/trend_rider_legendary.py", full_strategy_text("trend_rider"))
    decision = MODULE.owner_decision("trend_rider", [first, second])
    assert decision["verdict"] == "MULTIPLE_DIRECT_IMPLEMENTATIONS_REVIEW_REQUIRED"
    assert decision["full_direct_count"] == 2


def test_single_direct_owner_candidate() -> None:
    only = MODULE.score_module("obv_trend", "backend/strategies/obv_trend.py", full_strategy_text("obv_trend"))
    decision = MODULE.owner_decision("obv_trend", [only])
    assert decision["verdict"] == "SINGLE_DIRECT_OWNER_CANDIDATE"
    assert decision["confidence"] == 0.93


def test_registry_audit_finds_single_exact_coverage(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    strategies = [f"strategy_{index:02d}" for index in range(25)]
    registry = source / "strategy_registry.json"
    registry.write_text(json.dumps({name: {"enabled": True} for name in strategies}), encoding="utf-8")
    other = source / "legacy_catalog.py"
    other.write_text("L_POOL=['strategy_00']", encoding="utf-8")
    result = MODULE.registry_audit(source, strategies)
    assert result["verdict"] == "SINGLE_EXACT_25_REGISTRY_CANDIDATE"
    assert result["authoritative_candidate"] == "strategy_registry.json"


def test_registry_split_when_no_file_covers_all(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    strategies = ["alpha", "beta", "gamma"]
    (source / "strategy_catalog.py").write_text("POOL=['alpha','beta']", encoding="utf-8")
    (source / "policy.json").write_text('{"gamma": {}}', encoding="utf-8")
    result = MODULE.registry_audit(source, strategies)
    assert result["verdict"] == "REGISTRY_AUTHORITY_SPLIT_OR_INCOMPLETE"


def test_module_kind_classification() -> None:
    assert MODULE.module_kind("backend/strategies/a.py") == "canonical"
    assert MODULE.module_kind("backend/legendary_rebuild/strategies/a_legendary.py") == "legendary"
    assert MODULE.module_kind("backend/strategies_v4/a_v4.py") == "v4"
