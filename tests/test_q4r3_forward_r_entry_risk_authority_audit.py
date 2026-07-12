from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_forward_r_entry_risk_authority_audit.py"
    spec = importlib.util.spec_from_file_location("test_q4r3_forward_r_entry_risk_authority_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def base_open() -> dict:
    return {
        "status": "open",
        "trade_id": "T1",
        "entry_ts": 1_700_000_000_000,
        "entry_price": 100.0,
        "stop_loss_price": 99.0,
        "side": "long",
        "strategy": "alpha",
        "symbol": "BTCUSDT",
    }


def test_explicit_initial_risk_has_priority() -> None:
    row = base_open()
    row.update({"initial_risk_usdt": 7.5, "quantity": 2.0})
    contract = MODULE.risk_contract(row)
    assert contract is not None
    assert contract["formula_method"] == "EXPLICIT_RISK_USDT"
    assert contract["calculated_initial_risk_usdt"] == 7.5


def test_base_quantity_formula_is_exact() -> None:
    row = base_open()
    row["quantity"] = 2.5
    contract = MODULE.risk_contract(row)
    assert contract is not None
    assert contract["formula_method"] == "PRICE_DISTANCE_X_BASE_QTY"
    assert contract["calculated_initial_risk_usdt"] == 2.5
    assert contract["orientation"] == "VALID"


def test_notional_formula_is_exact() -> None:
    row = base_open()
    row["position_notional_usdt"] = 500.0
    contract = MODULE.risk_contract(row)
    assert contract is not None
    assert contract["formula_method"] == "PRICE_DISTANCE_RATIO_X_NOTIONAL"
    assert contract["calculated_initial_risk_usdt"] == 5.0


def test_contract_quantity_requires_explicit_multiplier() -> None:
    row = base_open()
    row["contracts"] = 10
    contract = MODULE.risk_contract(row)
    assert contract is not None
    assert contract["formula_ready"] is False
    assert "base_qty_or_notional_or_contract_multiplier" in contract["missing"]
    row["contract_multiplier"] = 0.01
    contract = MODULE.risk_contract(row)
    assert contract is not None
    assert contract["formula_method"] == "PRICE_DISTANCE_X_CONTRACT_QTY_X_MULTIPLIER"
    assert contract["calculated_initial_risk_usdt"] == 0.1


def test_leverage_position_percent_and_rr_are_never_used() -> None:
    row = base_open()
    row.update({"leverage": 20, "position_size_pct": 15, "rr": 2.0})
    contract = MODULE.risk_contract(row)
    assert contract is not None
    assert contract["formula_ready"] is False
    assert contract["calculated_initial_risk_usdt"] is None


def test_closed_record_is_not_an_entry_contract() -> None:
    row = base_open()
    row["status"] = "closed"
    row["quantity"] = 1.0
    assert MODULE.risk_contract(row) is None


def test_short_stop_orientation_is_valid_only_above_entry() -> None:
    row = base_open()
    row.update({"side": "short", "quantity": 1.0, "stop_loss_price": 101.0})
    contract = MODULE.risk_contract(row)
    assert contract is not None
    assert contract["orientation"] == "VALID"
    row["stop_loss_price"] = 99.0
    contract = MODULE.risk_contract(row)
    assert contract is not None
    assert contract["orientation"] == "INVALID"


def test_decision_selects_single_writer_patch_when_formula_ready() -> None:
    audit = {
        "unique_open_ids": 10,
        "explicit_risk_rows": 0,
        "formula_ready_unique_ids": 8,
        "formula_ready_rate_pct": 80.0,
        "missing_fields": {},
    }
    writer = {"dominant_single_entry_writer": True, "dominant_entry_writer": {"path": "entry.py"}}
    prior = {"stable_id_join_rate_pct": 82.068}
    decision = MODULE.decide(audit, writer, prior)
    assert decision["verdict"] == "ENTRY_RISK_SINGLE_WRITER_PATCH_READY"


def test_decision_selects_stop_persistence_when_stop_is_largest_gap() -> None:
    audit = {
        "unique_open_ids": 10,
        "explicit_risk_rows": 0,
        "formula_ready_unique_ids": 0,
        "formula_ready_rate_pct": 0.0,
        "missing_fields": {"stop_price": 10, "base_qty_or_notional_or_contract_multiplier": 3},
    }
    writer = {"dominant_single_entry_writer": False, "dominant_entry_writer": None}
    prior = {"stable_id_join_rate_pct": 82.068}
    decision = MODULE.decide(audit, writer, prior)
    assert decision["verdict"] == "ENTRY_RISK_STOP_PRICE_PERSISTENCE_GAP"
    assert decision["next_action"] == "PATCH_INITIAL_STOP_PRICE_AT_ENTRY_AUTHORITY"
