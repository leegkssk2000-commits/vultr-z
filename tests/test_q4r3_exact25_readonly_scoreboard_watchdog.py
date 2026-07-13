from __future__ import annotations

import importlib.util
import json
import pytest
from argparse import Namespace
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "q4r3_exact25_readonly_scoreboard_watchdog.py"
SPEC = importlib.util.spec_from_file_location("watchdog", MODULE_PATH)
assert SPEC and SPEC.loader
watchdog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watchdog)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def fixture(tmp_path: Path, rows: list[dict] | None = None) -> Namespace:
    now = 1_800_000_000.0
    strategies = [
        {"strategy_id": f"s{i:02d}", "owner_sha256": (f"{i:02x}" * 32)[:64]}
        for i in range(25)
    ]
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
    paths = {
        "ledger": tmp_path / "ledger.jsonl",
        "manifest": tmp_path / "manifest.json",
        "gate": tmp_path / "gate.json",
        "writer_status": tmp_path / "writer.json",
        "producer_status": tmp_path / "producer.json",
        "ssot": tmp_path / "ssot.json",
        "scoreboard": tmp_path / "scoreboard.json",
        "sample_matrix": tmp_path / "matrix.json",
        "status": tmp_path / "status.json",
        "violations": tmp_path / "violations.json",
    }
    write_json(paths["manifest"], {"strategies": strategies})
    write_json(
        paths["ssot"],
        {
            "expected_epoch": "EXACT25_EDGE_V1",
            "expected_namespace": "EXACT25_EDGE_V1",
            "expected_strategy_count": 25,
            "expected_symbol_count": 5,
            "required_core_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"],
            "status_stale_sec": 180,
            "max_clock_skew_sec": 30,
        },
    )
    write_json(
        paths["gate"],
        {
            "state": "ACTIVE",
            "epoch_id": "EXACT25_EDGE_V1",
            "measurement_namespace": "EXACT25_EDGE_V1",
            "symbols": symbols,
            "strategy_count": 25,
            "start_epoch": now - 100,
            "paper_enabled": False,
            "live_enabled": False,
            "order_enabled": False,
            "historical_backfill_allowed": False,
        },
    )
    write_json(
        paths["writer_status"],
        {
            "state": "RUNNING",
            "updated_at": now - 5,
            "last_error": None,
            "production_measurement_write_enabled": True,
            "historical_backfill_allowed": False,
            "symbols": symbols,
            "ledger_row_count": len(rows or []),
        },
    )
    write_json(
        paths["producer_status"],
        {
            "state": "RUNNING",
            "updated_at": now - 5,
            "processed_symbol_count": 5,
            "symbols": symbols,
            "cycle_errors": {},
            "feature_filter_enabled": False,
        },
    )
    with paths["ledger"].open("w", encoding="utf-8") as handle:
        for row in rows or []:
            handle.write(json.dumps(row) + "\n")
    return Namespace(**paths, now_epoch=now)


def row(strategy: int, realized_r: float, *, event: str, symbol: str = "BTCUSDT") -> dict:
    initial_risk = 2.0
    entry = 1_799_999_920.0
    exit_ = 1_799_999_950.0
    return {
        "event_id": event,
        "position_id": event.removesuffix(":close"),
        "strategy_id": f"s{strategy:02d}",
        "owner_sha256": (f"{strategy:02x}" * 32)[:64],
        "symbol": symbol,
        "side": "long",
        "regime": "long",
        "entry_ts": entry,
        "exit_ts": exit_,
        "source": "q4r3_exact25_dedicated_shadow_producer",
        "epoch_id": "EXACT25_EDGE_V1",
        "measurement_namespace": "EXACT25_EDGE_V1",
        "measurement_source": "q4r3_exact25_single_event_measurement_adapter",
        "formula_verified": True,
        "owner_lineage_verified": True,
        "mode": "shadow",
        "shadow": True,
        "status": "CLOSED",
        "closed": True,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "initial_risk_usdt": initial_risk,
        "realized_pnl_usdt": realized_r * initial_risk,
        "realized_R": realized_r,
        "fee": 0.01,
        "slippage": 0.02,
        "MFE_R": max(realized_r, 0.5),
        "MAE_R": min(realized_r, -0.2),
        "time_exposure_min": 0.5,
        "entry_features": {"session_window": "london"},
    }


def test_healthy_empty_ledger_is_accumulation_not_violation(tmp_path: Path) -> None:
    args = fixture(tmp_path)
    assert watchdog.run(args) == 0
    status = json.loads(args.status.read_text())
    scoreboard = json.loads(args.scoreboard.read_text())
    assert status["state"] == "HEALTHY"
    assert status["violation_count"] == 0
    assert not args.violations.exists()
    assert scoreboard["strategy_count"] == 25
    assert scoreboard["strategy_zero_close_count"] == 25
    assert scoreboard["comparison_ready"] is False


def test_scoreboard_metrics_and_sample_matrix(tmp_path: Path) -> None:
    rows = [
        row(0, 2.0, event="a:close", symbol="BTCUSDT"),
        row(0, -1.0, event="b:close", symbol="ETHUSDT"),
        row(0, 1.0, event="c:close", symbol="BTCUSDT"),
    ]
    args = fixture(tmp_path, rows)
    ledger_before = args.ledger.read_bytes()
    assert watchdog.run(args) == 0
    assert args.ledger.read_bytes() == ledger_before
    scoreboard = json.loads(args.scoreboard.read_text())
    strategy = next(item for item in scoreboard["strategies"] if item["strategy_id"] == "s00")
    assert strategy["closed_count"] == 3
    assert strategy["cumulative_R"] == 2.0
    assert strategy["expectancy_R"] == pytest.approx(2.0 / 3.0, abs=1e-8)
    assert strategy["profit_factor"] == 3.0
    assert strategy["max_drawdown_R"] == 1.0
    assert strategy["max_consecutive_losses"] == 1
    assert strategy["symbol_counts"] == {"BTCUSDT": 2, "ETHUSDT": 1}
    assert not args.violations.exists()


def test_formula_mismatch_creates_deduplicated_violation_only_alert(tmp_path: Path) -> None:
    bad = row(0, 1.0, event="bad:close")
    bad["realized_R"] = 9.0
    args = fixture(tmp_path, [bad])
    assert watchdog.run(args) == 0
    first = json.loads(args.violations.read_text())
    assert first["notify"] is True
    assert first["severity"] == "C"
    assert any(item["code"] == "REALIZED_R_FORMULA_MISMATCH" for item in first["violations"])
    assert watchdog.run(args) == 0
    second = json.loads(args.violations.read_text())
    assert second["notify"] is False
    assert second["fingerprint"] == first["fingerprint"]


def test_malformed_and_duplicate_rows_are_blocking_integrity_violations(tmp_path: Path) -> None:
    duplicate = row(0, 1.0, event="dup:close")
    args = fixture(tmp_path, [duplicate, duplicate])
    args.ledger.write_text(args.ledger.read_text() + "{broken\n", encoding="utf-8")
    writer = json.loads(args.writer_status.read_text())
    writer["ledger_row_count"] = 2
    write_json(args.writer_status, writer)
    assert watchdog.run(args) == 0
    alert = json.loads(args.violations.read_text())
    codes = {item["code"] for item in alert["violations"]}
    assert "DUPLICATE_EVENT_ID" in codes
    assert "LEDGER_JSON_MALFORMED" in codes
    assert alert["action"] == "HOLD"
