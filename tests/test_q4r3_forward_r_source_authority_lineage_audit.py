from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_forward_r_source_authority_lineage_audit_v2.py"
    spec = importlib.util.spec_from_file_location("test_q4r3_forward_r_source_authority_lineage_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def test_replay_sources_are_never_authoritative() -> None:
    source_class, reasons = MODULE.classify_source(Path("/home/z/z/runtime/q4r3_route_a_raschke_v3_2r_rescue_trades_latest.json"))
    assert source_class == "REPLAY_DIAGNOSTIC"
    assert "replay_or_diagnostic_token" in reasons


def test_forward_ledgers_can_be_authoritative() -> None:
    source_class, _ = MODULE.classify_source(Path("/home/z/z/runtime/h87_shadow_closed_ledger_latest.json"))
    assert source_class == "AUTHORITATIVE_FORWARD"
    source_class, _ = MODULE.classify_source(Path("/home/z/z/runtime/paper_order_ledger_state.json"))
    assert source_class == "AUTHORITATIVE_FORWARD"


def test_bounded_test_paths_are_diagnostic_without_matching_latest() -> None:
    source_class, reasons = MODULE.classify_source(Path("/home/z/z/tests/test_forward_ledger.json"))
    assert source_class == "REPLAY_DIAGNOSTIC"
    assert "bounded_test_path" in reasons
    source_class, _ = MODULE.classify_source(Path("/home/z/z/runtime/shadow_closed_ledger_latest.json"))
    assert source_class == "AUTHORITATIVE_FORWARD"


def test_contract_rows_extract_open_risk_and_closed_pnl() -> None:
    payload = {
        "rows": [
            {
                "status": "open",
                "trade_id": "T1",
                "entry_ts": 1_700_000_000_000,
                "initial_risk_usdt": 5.0,
                "strategy": "alpha",
            },
            {
                "status": "closed",
                "trade_id": "T1",
                "exit_ts": 1_700_000_060_000,
                "realized_pnl_usdt": 2.5,
                "strategy": "alpha",
            },
        ]
    }
    rows = list(MODULE.iter_contract_rows(payload, "memory.json"))
    assert len(rows) == 2
    assert rows[0]["state"] == "OPEN"
    assert rows[0]["risk_usdt"] == 5.0
    assert rows[1]["state"] == "CLOSED"
    assert rows[1]["realized_pnl_usdt"] == 2.5
    assert rows[0]["identity_hash"] == rows[1]["identity_hash"]


def test_lineage_metrics_join_by_stable_identity_without_emitting_raw_ids() -> None:
    rows = [
        {
            "source": "open.json",
            "state": "OPEN",
            "identity_hash": "abc",
            "risk_key": "initial_risk_usdt",
            "realized_usdt_key": None,
            "realized_r_key": None,
        },
        {
            "source": "close.json",
            "state": "CLOSED",
            "identity_hash": "abc",
            "risk_key": None,
            "realized_usdt_key": "realized_pnl_usdt",
            "realized_r_key": None,
        },
        {
            "source": "close.json",
            "state": "CLOSED",
            "identity_hash": "def",
            "risk_key": None,
            "realized_usdt_key": "realized_pnl_usdt",
            "realized_r_key": None,
        },
    ]
    report = MODULE.lineage_metrics(rows)
    assert report["joined_unique_ids"] == 1
    assert report["unique_close_ids"] == 2
    assert report["stable_id_join_rate_pct"] == 50.0
    assert report["joined_with_explicit_risk_count"] == 1
    assert report["joined_formula_ready_count"] == 1
    assert report["raw_ids_emitted"] is False


def test_decision_prioritizes_stable_id_before_risk_or_sidecar() -> None:
    authority = {"authoritative_files": [{"path": "ledger.json"}]}
    lineage = {
        "stable_id_join_rate_pct": 18.403,
        "joined_formula_ready_count": 0,
        "joined_with_explicit_risk_count": 0,
    }
    code = {"dominant_single_writer": False, "dominant_writer": None}
    decision = MODULE.decide(authority, lineage, code)
    assert decision["verdict"] == "AUTHORITATIVE_STABLE_ID_LINEAGE_GAP"
    assert decision["next_action"] == "PATCH_STABLE_ID_PROPAGATION_AT_OPEN_CLOSE_BOUNDARY"


def test_decision_selects_entry_risk_after_identity_gate() -> None:
    authority = {"authoritative_files": [{"path": "ledger.json"}]}
    lineage = {
        "stable_id_join_rate_pct": 90.0,
        "joined_formula_ready_count": 0,
        "joined_with_explicit_risk_count": 0,
    }
    code = {"dominant_single_writer": True, "dominant_writer": {"path": "writer.py"}}
    decision = MODULE.decide(authority, lineage, code)
    assert decision["verdict"] == "AUTHORITATIVE_ENTRY_RISK_DENOMINATOR_GAP"


def test_decision_allows_sidecar_only_after_identity_risk_and_pnl_are_ready() -> None:
    authority = {"authoritative_files": [{"path": "ledger.json"}]}
    lineage = {
        "stable_id_join_rate_pct": 90.0,
        "joined_formula_ready_count": 10,
        "joined_with_explicit_risk_count": 10,
    }
    code = {"dominant_single_writer": False, "dominant_writer": None}
    decision = MODULE.decide(authority, lineage, code)
    assert decision["verdict"] == "JOIN_READY_BUT_WRITER_SURFACE_DISTRIBUTED"
    assert decision["next_action"] == "INSTALL_APPEND_ONLY_FORWARD_R_SIDECAR_CANARY"
