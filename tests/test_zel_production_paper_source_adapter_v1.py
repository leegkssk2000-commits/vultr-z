import json

import pytest

from backend.production.zel_production_owner_binding_v1 import ProductionEventLedger, run_cycle
from backend.production.zel_production_paper_source_adapter_v1 import (
    CanonicalPaperSourceAdapter,
    build_payload,
)


def test_missing_authority_emits_stable_no_alpha_without_market_or_sizing_values():
    row = build_payload(None)
    assert row["mode"] == "PAPER"
    assert row["alpha_state"] == "NONE"
    assert row["signal"] == "FLAT"
    assert row["risk_state"] == "HOLD"
    assert row["source_state"] == "NO_VALIDATED_ALPHA"
    assert row["authority_state"] == "ALPHA_AUTHORITY_MISSING"
    assert row["exchange_order_submitted"] is False
    assert "price" not in row
    assert "qty" not in row
    assert "signal_ts" not in row


def test_research_only_strategy11_style_authority_is_not_executable():
    authority = {
        "alpha_state": "SURVIVOR_ACTIVE",
        "research_only": True,
        "promotion_authority": False,
        "execution_allowed": False,
        "runtime_bound": False,
    }
    row = build_payload(authority)
    assert row["alpha_state"] == "NONE"
    assert row["authority_state"] == "ALPHA_AUTHORITY_NON_EXECUTABLE"
    assert row["source_state"] == "NO_VALIDATED_ALPHA"
    assert "price" not in row
    assert "qty" not in row


def test_executable_alpha_requires_real_data_risk_sizing_binding():
    authority = {
        "alpha_state": "SURVIVOR_ACTIVE",
        "research_only": False,
        "promotion_authority": True,
        "execution_allowed": True,
        "runtime_bound": True,
    }
    with pytest.raises(RuntimeError, match="ACTIVE_ALPHA_DATA_RISK_SIZING_BINDING_REQUIRED"):
        build_payload(authority)


def test_adapter_writes_exact_canonical_payload(tmp_path):
    authority = tmp_path / "authority.json"
    output = tmp_path / "input.json"
    adapter = CanonicalPaperSourceAdapter(authority, output)
    row = adapter.write()
    assert output.exists()
    assert json.loads(output.read_text()) == row
    assert row["authority_state"] == "ALPHA_AUTHORITY_MISSING"
    assert "price" not in row
    assert "qty" not in row


def test_invalid_authority_json_object_contract_fails_closed(tmp_path):
    authority = tmp_path / "authority.json"
    output = tmp_path / "input.json"
    authority.write_text("[]")
    adapter = CanonicalPaperSourceAdapter(authority, output)
    with pytest.raises(ValueError, match="ALPHA_AUTHORITY_MUST_BE_JSON_OBJECT"):
        adapter.write()
    assert not output.exists()


def test_no_alpha_payload_runs_full_owner_cycle_without_event_or_fake_price(tmp_path):
    row = build_payload(None)
    ledger = ProductionEventLedger(tmp_path / "events.sqlite")
    result = run_cycle(row, ledger)
    assert result["decision"]["state"] == "HOLD"
    assert result["decision"]["reason"] == "NO_VALIDATED_ALPHA"
    assert result["decision"]["order_intent"] == "NONE"
    assert result["fill"] is None
    assert result["snapshot"]["canonical"]["ledger_event_count"] == 0
    assert result["exchange_order_submitted"] is False
    assert ledger.count() == 0
