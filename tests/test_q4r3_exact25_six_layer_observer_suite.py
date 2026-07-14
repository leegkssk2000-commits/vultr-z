from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


suite = load_module("six_layer_suite", ROOT / "tools/q4r3_exact25_six_layer_observer_suite.py")
collector = load_module("market_collector", ROOT / "tools/q4r3_exact25_market_context_collector.py")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def base_ssot(minimum_replay_sample: int = 50) -> dict:
    payload = json.loads((ROOT / "backend/config/q4r3_exact25_six_layer_observer_ssot_v1.json").read_text(encoding="utf-8"))
    payload["expected_strategy_count"] = 2
    payload["minimum_bucket_sample"] = 1
    payload["minimum_pair_sample"] = 1
    payload["minimum_replay_sample"] = minimum_replay_sample
    payload["replay_lab"]["ledger_ablation_enabled"] = True
    return payload


def row(event_id: str, strategy: str, owner: str, symbol: str, side: str, entry: datetime, result_r: float, close_reason: str) -> dict:
    risk = 1.0
    pnl = result_r * risk
    exit_ts = entry + timedelta(minutes=30)
    entry_price = 100.0
    exit_price = 101.0 if side == "long" else 99.0
    return {
        "event_id": event_id,
        "position_id": event_id.removesuffix(":close"),
        "strategy_id": strategy,
        "owner_sha256": owner,
        "symbol": symbol,
        "side": side,
        "entry_ts": entry.isoformat(),
        "exit_ts": exit_ts.isoformat(),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "qty": 1.0,
        "initial_risk_usdt": risk,
        "gross_pnl_usdt": pnl + 0.02,
        "realized_pnl_usdt": pnl,
        "realized_R": result_r,
        "fee": 0.01,
        "slippage": 0.01,
        "latency_ms": 5.0,
        "MFE_R": max(result_r + 0.4, 0.2),
        "MAE_R": min(result_r - 0.2, -0.1),
        "time_exposure_min": 30.0,
        "close_reason": close_reason,
        "partial_count": 0,
        "entry_features": {
            "htf_bias": side,
            "swing_sequence": "HH_HL" if side == "long" else "LH_LL",
            "premium_discount_side": "discount" if side == "long" else "premium",
            "ote_0_5_0_79": True,
            "ltf_reversal_confirm": True,
            "session_window": "london",
        },
        "epoch_id": "EXACT25_EDGE_V1",
        "measurement_namespace": "EXACT25_EDGE_V1",
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
    }


def make_args(tmp_path: Path, rows: list[dict], *, minimum_replay_sample: int = 50, producer_closed: int | None = None) -> tuple[argparse.Namespace, Path]:
    owners = {"alpha": "a" * 64, "beta": "b" * 64}
    ledger = tmp_path / "formal.jsonl"
    write_jsonl(ledger, rows)
    write_json(tmp_path / "manifest.json", {
        "strategies": [
            {"strategy_id": name, "owner_sha256": sha}
            for name, sha in owners.items()
        ]
    })
    write_json(tmp_path / "ssot.json", base_ssot(minimum_replay_sample))
    write_json(tmp_path / "producer_status.json", {
        "state": "RUNNING",
        "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT"],
        "signal_count": max(len(rows), 1),
        "open_event_count": max(len(rows), 1),
        "close_event_count": len(rows) if producer_closed is None else producer_closed,
        "open_position_count": 0,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
    })
    write_json(tmp_path / "producer_state.json", {
        "signal_count": max(len(rows), 1), "open_count": max(len(rows), 1), "close_count": len(rows)
    })
    write_json(tmp_path / "open_positions.json", {"open_count": 0, "positions": []})

    contexts = []
    for item in rows:
        entry = datetime.fromisoformat(item["entry_ts"])
        contexts.append({
            "snapshot_id": f"ctx-{item['event_id']}",
            "epoch_id": "EXACT25_EDGE_V1",
            "measurement_namespace": "EXACT25_EDGE_V1",
            "symbol": item["symbol"],
            "bar_ts": entry.isoformat(),
            "bar_epoch": entry.timestamp(),
            "atr_pct": 0.25,
            "realized_volatility_pct": 0.2,
            "trend_strength": 0.7,
            "trend_direction": item["side"],
            "volume_zscore": 1.2,
            "spread_bps": 1.5,
            "funding_8h_pct": 0.01,
            "observer_only": True,
            "paper_enabled": False,
            "live_enabled": False,
            "order_enabled": False,
        })
    write_jsonl(tmp_path / "context.jsonl", contexts)
    write_json(tmp_path / "context_status.json", {"state": "RUNNING", "error_count": 0})

    output = tmp_path / "out"
    args = argparse.Namespace(
        ledger=ledger,
        manifest=tmp_path / "manifest.json",
        producer_status=tmp_path / "producer_status.json",
        producer_state=tmp_path / "producer_state.json",
        open_positions=tmp_path / "open_positions.json",
        context_ledger=tmp_path / "context.jsonl",
        context_status=tmp_path / "context_status.json",
        ssot=tmp_path / "ssot.json",
        projection=output / "outcome_projection.jsonl",
        outcome_report=output / "outcome_report.json",
        funnel_report=output / "funnel_report.json",
        cost_exit_report=output / "cost_exit_report.json",
        market_report=output / "market_report.json",
        portfolio_report=output / "portfolio_report.json",
        replay_report=output / "replay_report.json",
        status=output / "status.json",
        violations=output / "violations.json",
    )
    return args, ledger


def test_market_context_computation_is_observer_only() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = 100.0
    for index in range(120):
        price += 0.05
        rows.append([
            int((start + timedelta(minutes=index)).timestamp() * 1000),
            price - 0.1, price + 0.2, price - 0.2, price, 1000 + index,
        ])
    frame = collector.closed_frame(rows, minimum=60)
    result = collector.compute_context(
        "BTCUSDT",
        frame,
        {"bid": 105.9, "ask": 106.1, "mark": 106.0, "index": 105.95},
        {"fundingRate": 0.0001},
        {"openInterestAmount": 12345},
    )
    assert result["observer_only"] is True
    assert result["private_credentials_used"] is False
    assert result["paper_enabled"] is False
    assert result["atr_pct"] > 0
    assert result["spread_bps"] > 0
    assert result["funding_8h_pct"] == 0.01


def test_six_layers_run_without_mutating_formal_ledger(tmp_path: Path) -> None:
    owners = {"alpha": "a" * 64, "beta": "b" * 64}
    start = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)
    rows = [
        row("alpha-1:close", "alpha", owners["alpha"], "BTCUSDT", "long", start, 1.2, "take_profit"),
        row("beta-1:close", "beta", owners["beta"], "BTCUSDT", "long", start + timedelta(minutes=10), -0.5, "stop_loss"),
    ]
    args, ledger = make_args(tmp_path, rows)
    before = hashlib.sha256(ledger.read_bytes()).hexdigest()
    assert suite.run(args) == 0
    after = hashlib.sha256(ledger.read_bytes()).hexdigest()
    assert before == after

    status = json.loads(args.status.read_text(encoding="utf-8"))
    assert status["layer_count"] == 6
    assert status["formal_ledger_mutated"] is False
    assert status["producer_modified"] is False
    assert status["writer_modified"] is False

    outcome = json.loads(args.outcome_report.read_text(encoding="utf-8"))
    assert outcome["core_complete_count"] == 2
    assert outcome["full_complete_count"] == 0

    market = json.loads(args.market_report.read_text(encoding="utf-8"))
    assert market["entry_context_joined_count"] == 2
    assert market["filter_enabled"] is False

    portfolio = json.loads(args.portfolio_report.read_text(encoding="utf-8"))
    assert portfolio["pair_count"] == 1
    assert portfolio["max_concurrent_positions"] == 2

    replay = json.loads(args.replay_report.read_text(encoding="utf-8"))
    assert replay["minimum_replay_sample_met"] is False
    assert replay["experiment_count"] == 0
    assert replay["promotion_enabled"] is False


def test_funnel_gap_and_duplicate_are_reported_hold(tmp_path: Path) -> None:
    owner = "a" * 64
    start = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    duplicate = row("dup:close", "alpha", owner, "ETHUSDT", "long", start, 0.4, "take_profit")
    args, _ledger = make_args(tmp_path, [duplicate, dict(duplicate)], producer_closed=3)
    assert suite.run(args) == 0
    violations = json.loads(args.violations.read_text(encoding="utf-8"))
    codes = {item["code"] for item in violations["violations"]}
    assert "DUPLICATE_EVENT_ID" in codes
    assert "CLOSE_TO_FORMAL_LEDGER_GAP" in codes
    assert violations["action"] == "hold"


def test_replay_lab_executes_only_after_minimum_forward_sample(tmp_path: Path) -> None:
    owners = {"alpha": "a" * 64, "beta": "b" * 64}
    start = datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc)
    rows = [
        row("alpha-2:close", "alpha", owners["alpha"], "SOLUSDT", "long", start, 1.0, "take_profit"),
        row("beta-2:close", "beta", owners["beta"], "XRPUSDT", "short", start + timedelta(minutes=40), -0.4, "stop_loss"),
    ]
    args, _ledger = make_args(tmp_path, rows, minimum_replay_sample=2)
    assert suite.run(args) == 0
    replay = json.loads(args.replay_report.read_text(encoding="utf-8"))
    assert replay["minimum_replay_sample_met"] is True
    assert replay["experiment_count"] == 6
    assert replay["strategy_signal_replay_enabled"] is False
    assert all(item["decision"] == "OBSERVE_ONLY_NO_PROMOTION" for item in replay["experiments"])
