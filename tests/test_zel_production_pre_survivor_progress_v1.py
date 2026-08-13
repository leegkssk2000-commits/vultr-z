from __future__ import annotations

import json
from pathlib import Path

from backend.production.zel_production_improvement_controller_v1 import stable_sha
from backend.production.zel_production_pre_survivor_progress_v1 import (
    HISTORY_SCHEMA,
    append_history_event,
    economic_metrics,
    progress_tick,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "config/zel_production_pre_survivor_progress_v1.json").read_text())
COST = json.loads((ROOT / "config/zel_production_carry_positioning_v1.json").read_text())
BASE_TS = 1_780_000_000_000
CID = "c" * 32
FAMILY = "l2_basis_inventory_pressure"


def admission(state: str = "REJECT_AI_ADMISSION_ECONOMIC_EDGE") -> dict:
    row = {
        "schema_version": "zel.production_ai_admission_executor.v1",
        "state": state,
        "results": [
            {
                "family_id": FAMILY,
                "contract_id": CID,
                "template_id": "l2_inventory_pressure_v1",
                "state": state,
                "economic_candidate": state == "PASS_AI_ADMISSION_ECONOMIC_CANDIDATE",
            }
        ],
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def observation(index: int, close: float, side: int = 1, context_pass: bool = True) -> dict:
    return {
        "schema_version": "zel.production_ai_admission_observation.v1",
        "contract_id": CID,
        "family_id": FAMILY,
        "template_id": "l2_inventory_pressure_v1",
        "symbol": "BTC-USDT",
        "observed_at_ms": BASE_TS + index * 3_600_000 + 3_600_000,
        "outcome_candle_ts_ms": BASE_TS + index * 3_600_000,
        "outcome_close": close,
        "primary_imbalance_sign": side,
        "context_pass": context_pass,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def test_economic_metrics_exposes_wr_pnl_expectancy_pf_and_dd() -> None:
    metrics = economic_metrics([10.0, -5.0, 15.0, -10.0])
    assert metrics["trade_count"] == 4
    assert metrics["win_count"] == 2
    assert metrics["win_rate_pct"] == 50.0
    assert metrics["net_pnl_bps"] == 10.0
    assert metrics["net_pnl_pct"] == 0.1
    assert metrics["net_expectancy_bps"] == 2.5
    assert abs(metrics["profit_factor"] - (25.0 / 15.0)) < 1e-12
    assert metrics["max_drawdown_bps"] == 10.0
    assert metrics["max_drawdown_pct"] == 0.1


def test_progress_tick_tracks_real_prospective_improvement_without_becoming_authority() -> None:
    baseline_rows = [
        observation(0, 100.0),
        observation(1, 105.0),
        observation(2, 110.0),
        observation(3, 115.0),
    ]
    baseline, _, feedback = progress_tick(
        POLICY,
        admission_result=admission(),
        observation_history=baseline_rows,
        cost_authority=COST,
        now_ms=BASE_TS,
    )
    assert baseline["state"] == "PASS_PRE_SURVIVOR_PROGRESS_CAPTURED"
    assert baseline["families"][0]["progress_direction"] == "BASELINE"
    assert baseline["families"][0]["metrics"]["win_rate_pct"] == 100.0
    assert feedback["state"] == "PASS_PRE_SURVIVOR_ECONOMIC_FEEDBACK"
    assert feedback["numeric_threshold_proposals_allowed"] is False
    assert feedback["parameter_search_allowed"] is False

    improved_rows = baseline_rows + [observation(4, 121.0)]
    improved, _, _ = progress_tick(
        POLICY,
        admission_result=admission(),
        observation_history=improved_rows,
        cost_authority=COST,
        previous_state=baseline,
        now_ms=BASE_TS + 3_600_000,
    )
    family = improved["families"][0]
    assert family["progress_direction"] == "IMPROVED"
    assert family["delta_vs_previous"]["trade_count"] == 1
    assert family["delta_vs_previous"]["net_pnl_bps"] > 0.0
    assert improved["progress_summary"]["improved"] == 1
    assert improved["selection_authority"] is False
    assert improved["promotion_authority"] is False
    assert improved["execution_authority"] == "NONE"
    assert improved["order_authority"] == "BLOCKED"
    assert improved["live_trade_authority"] == "BLOCKED"
    assert improved["action"] == "hold"


def test_progress_tick_marks_worsening_prospective_economics_as_regression() -> None:
    baseline_rows = [
        observation(0, 100.0),
        observation(1, 105.0),
        observation(2, 110.0),
        observation(3, 115.0),
    ]
    baseline, _, _ = progress_tick(
        POLICY,
        admission_result=admission(),
        observation_history=baseline_rows,
        cost_authority=COST,
        now_ms=BASE_TS,
    )
    worse_rows = baseline_rows + [observation(4, 80.0)]
    regressed, _, feedback = progress_tick(
        POLICY,
        admission_result=admission(),
        observation_history=worse_rows,
        cost_authority=COST,
        previous_state=baseline,
        now_ms=BASE_TS + 3_600_000,
    )
    family = regressed["families"][0]
    assert family["progress_direction"] == "REGRESSED"
    assert family["delta_vs_previous"]["win_rate_pct"] < 0.0
    assert family["delta_vs_previous"]["net_expectancy_bps"] < 0.0
    assert family["delta_vs_previous"]["max_drawdown_bps"] > 0.0
    assert regressed["progress_summary"]["regressed"] == 1
    assert feedback["entries"][0]["progress_direction"] == "REGRESSED"


def test_progress_tick_fail_closed_on_authority_drift() -> None:
    bad = admission()
    bad["order_authority"] = "OPEN"
    try:
        progress_tick(POLICY, admission_result=bad, observation_history=[], cost_authority=COST, now_ms=BASE_TS)
    except RuntimeError as exc:
        assert "EXECUTION_AUTHORITY_FORBIDDEN" in str(exc)
    else:
        raise AssertionError("authority drift must fail closed")


def test_history_append_is_fingerprint_idempotent(tmp_path: Path) -> None:
    state, event, _ = progress_tick(
        POLICY,
        admission_result=admission(),
        observation_history=[observation(0, 100.0), observation(1, 105.0)],
        cost_authority=COST,
        now_ms=BASE_TS,
    )
    assert event["schema_version"] == HISTORY_SCHEMA
    path = tmp_path / "progress.ndjson"
    assert append_history_event(path, event) is True
    assert append_history_event(path, event) is False
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["economic_fingerprint_sha256"] == state["economic_fingerprint_sha256"]
