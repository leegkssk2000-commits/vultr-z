from __future__ import annotations

import copy
import json
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

from backend.contracts.zel_event_sourced_shadow_v2 import ShadowEventV2Error
from backend.runtime.zel_shadow_event_journal_v1 import ShadowJournalError
from backend.runtime.zel_shadow_event_journal_v2 import SqliteShadowEventJournalV2, build_event_v2
from tools.zel_event_sourced_exact25_cutover_preflight_v1 import audit as preflight
from tools.zel_event_sourced_exact25_producer_v2 import EventSourcedProducerHooksV2

OWNER_SHA = "2cdf64e5e66cf9e2151fbf6d82546d2a9b65a024d1acb1d53bd3d4a62fac30e3"


def frame() -> pd.DataFrame:
    timestamps = pd.date_range("2026-07-31T17:00:00Z", periods=3, freq="min")
    return pd.DataFrame({
        "timestamp_ms": [int(ts.timestamp() * 1000) for ts in timestamps],
        "timestamp": timestamps,
        "open": [100.0, 100.5, 101.0],
        "high": [101.0, 101.5, 102.0],
        "low": [99.5, 100.0, 100.5],
        "close": [100.5, 101.0, 101.5],
        "volume": [1000.0, 1100.0, 1200.0],
    })


def fake_module() -> ModuleType:
    module = ModuleType("fake_exact25_producer")

    def make_position(strategy_id, owner_sha, symbol, timeframe, result, frame_value, risk_usdt, fee_rate, slippage_bps):
        if result.get("action") != "enter":
            return None
        return {
            "position_id": "exact25.shadow.test001",
            "event_id": "exact25.shadow.test001",
            "strategy_id": strategy_id,
            "owner_sha256": owner_sha,
            "symbol": symbol,
            "timeframe": timeframe,
            "side": "long",
            "entry_ts": pd.Timestamp(frame_value.iloc[-1]["timestamp"]).isoformat(),
            "entry_price": 101.5,
            "stop_price": 100.5,
            "take_profit_price": 103.5,
            "qty": 1.0,
            "initial_risk_usdt": risk_usdt,
            "entry_features": {"observer_only": True},
            "entry_reason": "test",
            "entry_confidence": 0.8,
        }

    def apply_add(position, result, *args, **kwargs):
        position["qty"] = float(position["qty"]) + 0.1
        position["add_count"] = int(position.get("add_count", 0)) + 1
        return True

    def apply_partial(position, result, *args, **kwargs):
        position["qty"] = float(position["qty"]) * 0.7
        position["partial_count"] = int(position.get("partial_count", 0)) + 1
        return True

    def close_position(position, exit_price, exit_ts, reason, *args, **kwargs):
        return {
            "schema": "q4r3_exact25_dedicated_shadow_close_v1",
            "event_id": str(position["position_id"]) + ":close",
            "position_id": position["position_id"],
            "strategy_id": position["strategy_id"],
            "owner_sha256": position["owner_sha256"],
            "symbol": position["symbol"],
            "side": position["side"],
            "exit_ts": exit_ts,
            "exit_reason": reason,
            "realized_R": 1.0,
        }

    def append_jsonl_once(path, row):
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        if any(json.loads(line).get("event_id") == row.get("event_id") for line in existing):
            return False
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(row), sort_keys=True) + "\n")
        return True

    def atomic_json(path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(payload), default=str, sort_keys=True), encoding="utf-8")

    module.make_position = make_position
    module.apply_add = apply_add
    module.apply_partial_reduce = apply_partial
    module.close_position = close_position
    module.append_jsonl_once = append_jsonl_once
    module.atomic_json = atomic_json
    module.now_iso = lambda: "2026-07-31T17:10:00+00:00"
    return module


def test_v2_adapter_records_shadow_ledger_without_false_formal_claim(tmp_path: Path) -> None:
    module = fake_module()
    journal = SqliteShadowEventJournalV2(tmp_path / "events.sqlite3", tmp_path / "events.jsonl")
    hooks = EventSourcedProducerHooksV2(module, journal, tmp_path / "status.json", "a" * 40)
    hooks.install()
    result = {
        "action": "enter", "side": "long", "entry": 101.5, "sl": 100.5, "tp": 103.5,
        "why": "test", "confidence": 0.8, "method_id": "TEST_METHOD", "team_id": "ALPHA",
    }
    position = module.make_position("alpha_combo", OWNER_SHA, "BTCUSDT", "1m", result, frame(), 1.0, 0.0, 0.0)
    assert position is not None
    state = {
        "schema": "q4r3_exact25_dedicated_shadow_producer_state_v1",
        "epoch_id": "EXACT25_EDGE_V1",
        "positions": {"alpha_combo|BTCUSDT|1m": position},
    }
    module.atomic_json(tmp_path / "state.json", state)
    close = module.close_position(
        position, 103.5, "2026-07-31T17:05:00+00:00", "take_profit", {}, 0.0, 0.0
    )
    assert module.append_jsonl_once(tmp_path / "shadow_ledger.jsonl", close) is True
    coverage = journal.coverage()
    assert coverage["shadow_event_lineage_coverage_pct"] == 100.0
    assert coverage["formal_ledger_lineage_coverage_pct"] == 0.0
    assert coverage["shadow_pass"] is True
    assert coverage["p1_pass"] is False
    assert journal.events(position["position_id"])[-1]["event_type"] == "shadow_ledger_joined"

    identity = copy.deepcopy(position["_zel_event_identity"])
    identity["runtime_bound"] = True
    formal = build_event_v2(
        identity,
        "formal_ledger_joined",
        "2026-07-31T17:06:00+00:00",
        {"formal_ledger_row_sha256": "3" * 64},
        journal,
        formal_ledger_write_allowed=True,
    )
    journal.append(formal)
    final = journal.coverage()
    assert final["formal_ledger_lineage_coverage_pct"] == 100.0
    assert final["p1_pass"] is True


def test_runtime_journal_rejects_private_payload_and_timestamp_regression(tmp_path: Path) -> None:
    journal = SqliteShadowEventJournalV2(tmp_path / "events.sqlite3", tmp_path / "events.jsonl")
    identity = {
        "decision_id": "decision.test",
        "position_id": "position.test",
        "strategy_id": "alpha_combo",
        "strategy_source_sha256": OWNER_SHA,
        "method_id": "TEST",
        "skill_set": [],
        "team_id": "ALPHA",
        "symbol": "BTCUSDT",
        "side": "LONG",
        "market_snapshot_sha256": "1" * 64,
        "risk_snapshot_sha256": "2" * 64,
        "source_ids": ["runtime:test"],
        "runtime_bound": True,
    }
    private = build_event_v2(identity, "strategy_signal_emitted", "2026-07-31T17:00:00Z", {"api_key": "x"}, journal)
    with pytest.raises(ShadowEventV2Error, match="PRIVATE_FIELD_FORBIDDEN"):
        journal.append(private)
    first = build_event_v2(identity, "strategy_signal_emitted", "2026-07-31T17:02:00Z", {"action": "enter"}, journal)
    journal.append(first)
    second = build_event_v2(identity, "admission_decided", "2026-07-31T17:01:00Z", {"admitted": True}, journal)
    with pytest.raises(ShadowJournalError, match="EVENT_TIMESTAMP_REGRESSION"):
        journal.append(second)


def test_projection_recovers_atomically_from_sqlite(tmp_path: Path) -> None:
    journal = SqliteShadowEventJournalV2(tmp_path / "events.sqlite3", tmp_path / "events.jsonl")
    module = fake_module()
    hooks = EventSourcedProducerHooksV2(module, journal, tmp_path / "status.json", "a" * 40)
    hooks.install()
    result = {
        "action": "enter", "side": "long", "entry": 101.5, "sl": 100.5, "tp": 103.5,
        "method_id": "TEST", "team_id": "ALPHA",
    }
    module.make_position("alpha_combo", OWNER_SHA, "BTCUSDT", "1m", result, frame(), 1.0, 0.0, 0.0)
    projection = tmp_path / "events.jsonl"
    projection.write_text("corrupt\n", encoding="utf-8")
    receipt = journal.sync_projection()
    rows = [json.loads(line) for line in projection.read_text(encoding="utf-8").splitlines()]
    assert receipt["event_count"] == 3
    assert len(rows) == 3
    assert rows[0]["event_type"] == "strategy_signal_emitted"


def test_cutover_preflight_requires_zero_open_positions(tmp_path: Path) -> None:
    source = tmp_path / "producer.py"
    source.write_text("print('safe')\n", encoding="utf-8")
    import subprocess
    blob = subprocess.check_output(["git", "hash-object", str(source)], text=True).strip()
    state = tmp_path / "state.json"
    status = tmp_path / "status.json"
    ledger = tmp_path / "formal.jsonl"
    state.write_text(json.dumps({"positions": {}}), encoding="utf-8")
    status.write_text(json.dumps({
        "paper_enabled": False, "live_enabled": False, "order_enabled": False,
        "private_credentials_used": False, "historical_backfill_allowed": False,
    }), encoding="utf-8")
    ledger.write_text("{}\n", encoding="utf-8")
    passed = preflight(source, blob, state, status, ledger, tmp_path / "events.db", tmp_path / "events.jsonl")
    assert passed["state"] == "PASS_P1_EVENT_SOURCE_CUTOVER_READY"
    state.write_text(json.dumps({"positions": {"p": {"position_id": "p"}}}), encoding="utf-8")
    held = preflight(source, blob, state, status, ledger, tmp_path / "events.db", tmp_path / "events.jsonl")
    assert held["state"] == "HOLD_P1_EVENT_SOURCE_CUTOVER"
    assert "OPEN_POSITIONS_MUST_BE_ZERO_AT_CUTOVER" in held["blockers"]
