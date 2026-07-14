from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from tools import q4r3_exact25_skill_trigger_lineage_observer as observer


SKILLS = [
    "SK_ENTRY_LONG_BEAM",
    "SK_ENTRY_SHORT_BEAM",
    "SK_ADD_DCA",
    "SK_ADD_AVG_DOWN",
    "SK_ADD_WATER_ADD",
    "SK_ADD_PYRAMIDING",
    "SK_ADD_PROFITABLE_SCALE_IN",
    "SK_EXIT_PARTIAL_30",
    "SK_EXIT_TRAILING_STOP",
    "SK_EXIT_MFE_RUNNER",
    "SK_EXIT_RUNNER_HOLD",
    "SK_EXIT_TIME_STOP",
    "SK_EXIT_BREAK_EVEN_SHIFT",
    "SK_RISK_REDUCE_25",
    "SK_RISK_LOSS_CAP",
    "SK_RISK_COOLDOWN",
    "SK_RISK_EXPOSURE_LIMITER",
    "SK_RISK_LIQUIDATION_BUFFER_GUARD",
]


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def write_matrix(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["strategy_id", "method_id", "skill_id"])
        writer.writeheader()
        writer.writerow({"strategy_id": "alpha", "method_id": "scalp_first/revert", "skill_id": "SK_ENTRY_LONG_BEAM"})


def fixture(tmp_path: Path, skill_value: str = "long_beam") -> argparse.Namespace:
    root = tmp_path / "root"
    open_path = root / "runtime/exact25_edge_v1/dedicated_shadow_producer/open_positions_latest.json"
    ledger = root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
    ssot = tmp_path / "ssot.json"
    registry = tmp_path / "registry.json"
    contract = tmp_path / "contract.json"
    audit = tmp_path / "audit.json"
    matrix = tmp_path / "matrix.csv"
    activation = tmp_path / "activation.json"
    events = tmp_path / "out/events.jsonl"
    coverage = tmp_path / "out/coverage.json"
    violations = tmp_path / "out/violations.json"
    status = tmp_path / "out/status.json"

    write_json(ssot, {
        "epoch_id": "EXACT25_EDGE_V1",
        "expected_matrix_rows": 1,
        "required_skill_audit_verdict_prefix": "ACTIVE_IMPORT_CALL_SURFACE_PASS",
        "open_position_candidates": ["runtime/exact25_edge_v1/dedicated_shadow_producer/open_positions_latest.json"],
        "formal_ledger": "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl",
        "preentry_globs": ["runtime/**/*preentry*context*.json"],
        "runtime_scan_max_files": 10,
        "runtime_scan_max_age_hours": 72,
        "identity_aliases": {
            "position_id": ["position_id"], "strategy_id": ["strategy_id"], "method_id": ["method_id"],
            "symbol": ["symbol"], "side": ["side"], "entry_ts": ["entry_ts"], "event_ts": ["event_ts"],
            "skill": ["entry_skill"],
        },
        "close_aliases": {
            "position_id": ["position_id"], "close_event_id": ["event_id"], "closed_at": ["closed_at"],
            "realized_r": ["realized_r"], "realized_pnl_usdt": ["realized_pnl_usdt"], "fee_bps": ["fee_bps"],
            "fee": ["fee"], "slippage_bps": ["slippage_bps"], "slippage": ["slippage"],
            "mfe_r": ["mfe_r"], "mae_r": ["mae_r"], "exposure_time_min": ["exposure_time_min"],
            "exit_reason": ["exit_reason"],
        },
        "manual_skill_aliases": {"long_beam": "SK_ENTRY_LONG_BEAM"},
        "ambiguous_aliases": ["scale_in"],
    })
    write_json(registry, {
        "version": "2.0.0-candidate.1", "activation_allowed": False, "runtime_mutation_allowed": False,
        "skills": [{"skill_id": value, "label_ko": value, "category": "test", "risk_tier": "M"} for value in SKILLS],
    })
    write_json(contract, {"historical_backfill_allowed": False, "required_pretrigger_context": ["reference_price"]})
    write_json(audit, {"state": "PASS", "verdict": "ACTIVE_IMPORT_CALL_SURFACE_PASS_TRIGGER_LINEAGE_NOT_YET_PROVEN"})
    write_matrix(matrix)
    write_json(activation, {"activated_at": "2026-07-14T16:00:00+00:00", "baseline_ledger_rows": 0, "baseline_position_ids": []})
    write_json(open_path, {"positions": [{
        "position_id": "p1", "strategy_id": "alpha", "method_id": "scalp_first/revert", "symbol": "BTCUSDT",
        "side": "long", "entry_ts": "2026-07-14T16:01:00+00:00", "event_ts": "2026-07-14T16:01:00+00:00",
        "entry_price": 100.0, "entry_skill": skill_value,
    }]})
    write_jsonl(ledger, [{
        "event_id": "p1:close", "position_id": "p1", "closed_at": "2026-07-14T16:10:00+00:00",
        "realized_r": 1.25, "realized_pnl_usdt": 1.25, "symbol": "BTCUSDT", "side": "long",
    }])
    return argparse.Namespace(root=root, ssot=ssot, registry=registry, contract=contract, audit_result=audit,
                              matrix=matrix, activation=activation, events=events, coverage=coverage,
                              violations=violations, status=status)


def test_forward_trigger_and_exact_close_join(tmp_path: Path) -> None:
    args = fixture(tmp_path)
    assert observer.run(args) == 0
    status = json.loads(args.status.read_text())
    events, errors = observer.read_jsonl(args.events)
    assert errors == []
    assert status["state"] == "PASS"
    assert status["skill_triggered_count"] == 1
    assert status["close_outcome_joined_count"] == 1
    assert [row["event_type"] for row in events] == ["skill_triggered", "close_outcome_joined"]
    assert events[1]["position_id"] == events[0]["position_id"] == "p1"
    assert events[1]["realized_r"] == 1.25


def test_ambiguous_legacy_alias_fails_closed(tmp_path: Path) -> None:
    args = fixture(tmp_path, "scale_in")
    assert observer.run(args) == 2
    status = json.loads(args.status.read_text())
    violations = json.loads(args.violations.read_text())
    assert status["state"] == "HOLD"
    assert status["skill_triggered_count"] == 0
    assert any(row["code"] == "AMBIGUOUS_LEGACY_SKILL_ALIAS" for row in violations["violations"])


def test_baseline_position_is_not_backfilled(tmp_path: Path) -> None:
    args = fixture(tmp_path)
    write_json(args.activation, {"activated_at": "2026-07-14T16:00:00+00:00", "baseline_ledger_rows": 1, "baseline_position_ids": ["p1"]})
    assert observer.run(args) == 0
    status = json.loads(args.status.read_text())
    assert status["verdict"] == "SKILL_TRIGGER_LINEAGE_OBSERVER_HEALTHY_WAITING_FORWARD_EVIDENCE"
    assert status["event_count"] == 0
    assert status["historical_backfill_performed"] is False
