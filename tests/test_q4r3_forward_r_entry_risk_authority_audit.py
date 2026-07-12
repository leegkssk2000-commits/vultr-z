from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / 'tools' / 'q4r3_forward_r_entry_risk_authority_audit.py'
    spec = importlib.util.spec_from_file_location('test_q4r3_forward_r_entry_risk_authority_module', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def test_open_row_extracts_explicit_risk() -> None:
    payload = {'status': 'open', 'trade_id': 'T1', 'entry_price': 100.0, 'stop_price': 99.0, 'qty': 2.0, 'initial_risk_usdt': 2.0}
    rows = list(MODULE.iter_open_rows(payload, 'memory.json'))
    assert len(rows) == 1
    assert rows[0]['risk_key'] == 'initial_risk_usdt'
    assert rows[0]['formula_ready_from_price_stop_qty'] is True


def test_open_row_formula_requires_entry_stop_qty() -> None:
    payload = {'status': 'open', 'position_id': 'P1', 'entry_price': 100.0, 'stop_price': 99.0}
    row = list(MODULE.iter_open_rows(payload, 'memory.json'))[0]
    assert row['formula_ready_from_price_stop_qty'] is False
    assert row['qty_key'] is None


def test_closed_row_is_not_entry_authority() -> None:
    payload = {'status': 'closed', 'trade_id': 'T1', 'entry_price': 100.0, 'stop_price': 99.0, 'qty': 2.0}
    assert list(MODULE.iter_open_rows(payload, 'memory.json')) == []


def test_pending_is_treated_as_open_contract() -> None:
    payload = {'state': 'pending', 'request_id': 'R1', 'entry_price': 100.0, 'sl': 99.0, 'quantity': 1.0}
    rows = list(MODULE.iter_open_rows(payload, 'memory.json'))
    assert len(rows) == 1
    assert rows[0]['formula_ready_from_price_stop_qty'] is True


def test_safe_float_rejects_non_finite() -> None:
    assert MODULE.safe_float('nan') is None
    assert MODULE.safe_float('inf') is None
    assert MODULE.safe_float('1.5') == 1.5


def test_line_hits_returns_line_numbers() -> None:
    text = 'x = 1\ntrade_id = 2\ninitial_risk_usdt = 3\n'
    assert MODULE.line_hits(text, MODULE.IDENTITY_TERMS) == [2]
    assert MODULE.line_hits(text, MODULE.RISK_TERMS) == [3]
