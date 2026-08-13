from __future__ import annotations

import json
from pathlib import Path

from backend.production.zel_production_improvement_controller_v1 import stable_sha
from backend.production.zel_production_pre_survivor_feedback_bridge_v1 import project_feedback

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "config/zel_production_pre_survivor_feedback_bridge_v1.json").read_text())
BASE_TS = 1_780_000_000_000
ACCUMULATING_STATE = "HOLD_AI_ADMISSION_REJECTION_EVIDENCE_INSUFFICIENT"


def feedback() -> dict:
    row = {
        "schema_version": "zel.production_pre_survivor_feedback.v1",
        "state": "PASS_PRE_SURVIVOR_ECONOMIC_FEEDBACK",
        "entries": [
            {
                "family_id": "weak_family",
                "contract_id": "a" * 32,
                "template_id": "l2_inventory_pressure_v1",
                "admission_state": "REJECT_AI_ADMISSION_ECONOMIC_EDGE",
                "progress_direction": "REGRESSED",
                "metrics": {
                    "trade_count": 12,
                    "win_rate_pct": 41.6666666667,
                    "net_pnl_bps": -85.0,
                    "net_pnl_pct": -0.85,
                    "net_expectancy_bps": -7.0833333333,
                    "profit_factor": 0.74,
                    "max_drawdown_bps": 130.0,
                    "max_drawdown_pct": 1.3,
                },
                "delta_vs_previous": {
                    "trade_count": 3,
                    "win_rate_pct": -8.3333333333,
                    "net_pnl_bps": -60.0,
                    "net_expectancy_bps": -5.0,
                    "profit_factor": -0.2,
                    "max_drawdown_bps": 40.0,
                },
            },
            {
                "family_id": "more_evidence_family",
                "contract_id": "b" * 32,
                "template_id": "basis_oi_deleveraging_v1",
                "admission_state": "REJECT_AI_ADMISSION_ECONOMIC_EDGE",
                "progress_direction": "IMPROVED",
                "metrics": {
                    "trade_count": 20,
                    "win_rate_pct": 55.0,
                    "net_pnl_bps": 35.0,
                    "net_pnl_pct": 0.35,
                    "net_expectancy_bps": 1.75,
                    "profit_factor": 1.08,
                    "max_drawdown_bps": 75.0,
                    "max_drawdown_pct": 0.75,
                },
                "delta_vs_previous": {
                    "trade_count": 4,
                    "win_rate_pct": 5.0,
                    "net_pnl_bps": 30.0,
                    "net_expectancy_bps": 1.1,
                    "profit_factor": 0.08,
                    "max_drawdown_bps": -5.0,
                },
            },
        ],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "action": "hold",
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def progress() -> dict:
    row = {
        "schema_version": "zel.production_pre_survivor_progress.v1",
        "state": "PASS_PRE_SURVIVOR_PROGRESS_CAPTURED",
        "families": [],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "action": "hold",
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def _re_receipt(row: dict) -> dict:
    row["receipt_sha256"] = stable_sha({k: v for k, v in row.items() if k != "receipt_sha256"})
    return row


def test_bridge_projects_most_evidence_reject_without_optimization_authority() -> None:
    result = project_feedback(POLICY, feedback=feedback(), progress=progress(), now_ms=BASE_TS)
    assert result["state"] == "PASS_PRE_SURVIVOR_REJECT_CONTEXT_PROJECTED"
    assert result["context_kind"] == "TERMINAL_REJECT"
    assert result["non_terminal_context"] is False
    assert result["family_id"] == "more_evidence_family"
    assert result["trade_count"] == 20
    assert result["win_rate_pct"] == 55.0
    assert result["net_pnl"] == 35.0
    assert result["net_expectancy"] == 1.75
    assert result["profit_factor"] == 1.08
    assert result["max_dd_pct"] == 0.75
    assert result["projection_role"] == "CONTEXT_ONLY_NOT_GATE"
    assert result["win_rate_role"] == "OBSERVATION_ONLY_NOT_GATE"
    assert result["numeric_threshold_proposals_allowed"] is False
    assert result["parameter_search_allowed"] is False
    assert result["selection_authority"] is False
    assert result["promotion_authority"] is False
    assert result["execution_authority"] == "NONE"
    assert result["order_authority"] == "BLOCKED"
    assert result["live_trade_authority"] == "BLOCKED"
    assert result["action"] == "hold"


def test_bridge_projects_accumulating_family_as_provisional_context() -> None:
    row = feedback()
    current = dict(row["entries"][0])
    current["admission_state"] = ACCUMULATING_STATE
    current["progress_direction"] = "UNCHANGED"
    row["entries"] = [current]
    result = project_feedback(POLICY, feedback=_re_receipt(row), progress=progress(), now_ms=BASE_TS)
    assert result["state"] == "PASS_PRE_SURVIVOR_ACCUMULATING_CONTEXT_PROJECTED"
    assert result["context_kind"] == "PROVISIONAL_ACCUMULATING"
    assert result["non_terminal_context"] is True
    assert result["source_admission_state"] == ACCUMULATING_STATE
    assert result["family_id"] == "weak_family"
    assert result["trade_count"] == 12
    assert result["progress_direction"] == "UNCHANGED"
    assert result["context_intent"] == "INFORM_NEXT_NEW_ECONOMIC_FAMILY_WHILE_CURRENT_FAMILY_ACCUMULATES"
    assert result["selection_authority"] is False
    assert result["promotion_authority"] is False
    assert result["execution_authority"] == "NONE"
    assert result["order_authority"] == "BLOCKED"
    assert result["live_trade_authority"] == "BLOCKED"
    assert result["action"] == "hold"


def test_bridge_terminal_reject_has_priority_over_larger_accumulating_sample() -> None:
    row = feedback()
    provisional = dict(row["entries"][0])
    provisional["admission_state"] = ACCUMULATING_STATE
    provisional["metrics"] = dict(provisional["metrics"], trade_count=999)
    terminal = dict(row["entries"][1])
    row["entries"] = [provisional, terminal]
    result = project_feedback(POLICY, feedback=_re_receipt(row), progress=progress(), now_ms=BASE_TS)
    assert result["state"] == "PASS_PRE_SURVIVOR_REJECT_CONTEXT_PROJECTED"
    assert result["context_kind"] == "TERMINAL_REJECT"
    assert result["family_id"] == "more_evidence_family"
    assert result["trade_count"] == 20


def test_bridge_holds_without_supported_economic_context() -> None:
    row = feedback()
    row["entries"] = [dict(row["entries"][0], admission_state="HOLD_AI_ADMISSION_HISTORY_INSUFFICIENT")]
    result = project_feedback(POLICY, feedback=_re_receipt(row), progress=progress(), now_ms=BASE_TS)
    assert result["state"] == "HOLD_PRE_SURVIVOR_FEEDBACK_BRIDGE_NO_ECONOMIC_CONTEXT"
    assert "net_pnl" not in result


def test_bridge_fail_closed_on_feedback_authority_drift() -> None:
    row = feedback()
    row["live_trade_authority"] = "OPEN"
    try:
        project_feedback(POLICY, feedback=row, progress=progress(), now_ms=BASE_TS)
    except RuntimeError as exc:
        assert "LIVE_AUTHORITY_FORBIDDEN" in str(exc)
    else:
        raise AssertionError("authority drift must fail closed")


def test_terminal_feedback_policy_uses_pre_survivor_context_policy() -> None:
    bridge = json.loads((ROOT / "config/zel_production_pre_survivor_feedback_bridge_v1.json").read_text())
    terminal = json.loads((ROOT / "config/zel_production_ai_terminal_feedback_v1.json").read_text())
    proposal = json.loads((ROOT / "config/zel_production_ai_proposal_layer_pre_survivor_v1.json").read_text())
    assert bridge["selection_rule"] == "TERMINAL_REJECT_ELSE_MOST_EVIDENCE_ACCUMULATING_NO_OPTIMIZATION"
    assert bridge["accumulating_context_allowed"] is True
    assert bridge["accumulating_admission_state"] == ACCUMULATING_STATE
    assert terminal["proposal_policy_path"] == "config/zel_production_ai_proposal_layer_pre_survivor_v1.json"
    assert proposal["improvement_evidence_path"] == "/home/z/z/ledger/production_pre_survivor_improvement_evidence_v1.json"
    assert proposal["numeric_threshold_proposals_allowed"] is False
    assert proposal["selection_authority"] is False
    assert proposal["promotion_authority"] is False
    assert proposal["execution_authority"] == "NONE"
    assert proposal["order_authority"] == "BLOCKED"
    assert proposal["live_trade_authority"] == "BLOCKED"
