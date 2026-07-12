from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools/q4r3_exact25_active_runtime_smoke.py"
    spec = importlib.util.spec_from_file_location("q4r3_exact25_active_runtime_smoke_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def valid_output(action: str = "hold", size: float = 0.0):
    return {
        "side": "flat",
        "action": action,
        "size": size,
        "entry": None,
        "sl": None,
        "tp": None,
        "pyramiding": 0,
        "why": "test",
        "skill": [],
        "confidence": 0.0,
        "tags": [],
        "indicators": {},
    }


def test_expected_universe_is_exactly_25_unique() -> None:
    assert len(MODULE.EXPECTED_25) == 25
    assert len(set(MODULE.EXPECTED_25)) == 25


def test_synthetic_frame_has_required_market_columns() -> None:
    frame = MODULE.synthetic_frame(360)
    assert len(frame) == 360
    assert {"timestamp", "open", "high", "low", "close", "volume"}.issubset(frame.columns)
    assert frame[["open", "high", "low", "close", "volume"]].isna().sum().sum() == 0
    assert (frame["high"] >= frame[["open", "close"]].max(axis=1)).all()
    assert (frame["low"] <= frame[["open", "close"]].min(axis=1)).all()


def test_validate_output_accepts_safe_hold() -> None:
    assert MODULE.validate_output(valid_output(), require_hold=True)


def test_validate_output_rejects_nonzero_block_size() -> None:
    assert not MODULE.validate_output(valid_output(size=0.1), require_hold=True)


def test_validate_output_rejects_missing_contract_key() -> None:
    output = valid_output()
    output.pop("indicators")
    assert not MODULE.validate_output(output)


def test_strategy_smoke_pass_requires_all_checks() -> None:
    item = MODULE.StrategySmoke(
        strategy_id="alpha_combo",
        module="backend.strategies.alpha_combo",
        owner_path="backend/strategies/alpha_combo.py",
        sha_match=True,
        module_origin_match=True,
        import_ok=True,
        signature_ok=True,
        empty_contract_ok=True,
        block_contract_ok=True,
        synthetic_contract_ok=True,
        elapsed_ms=1,
        error=None,
    )
    assert item.passed
    item.synthetic_contract_ok = False
    assert not item.passed
