from __future__ import annotations

import copy
import json
from pathlib import Path

import pandas as pd
import pytest

from ops import issue1388_alpha_screen_v1 as screen


def frame(rows: int = 500) -> pd.DataFrame:
    start = screen.START_MS - 200 * 900_000
    values = []
    price = 100.0
    for i in range(rows):
        if 200 <= i < 280:
            price *= 0.996
        elif 280 <= i < 360:
            price *= 1.005
        open_ = price
        values.append({
            "open_ts_ms": start + i * 900_000,
            "close_ts_ms": start + (i + 1) * 900_000,
            "available_ts_ms": start + (i + 1) * 900_000,
            "open": open_, "high": open_ * 1.004, "low": open_ * 0.996,
            "close": open_, "volume": 1.0,
        })
    return pd.DataFrame(values)


def test_signals_are_past_only_and_entry_is_next_open() -> None:
    data = frame()
    entry, _ = screen.signals(data)
    indexes = list(data.index[entry])
    assert indexes
    trades, _, _ = screen.replay_symbol("BTC-USDT", data, 10.0)
    if trades:
        first = trades[0]
        assert first["entry_ts_ms"] >= first["signal_available_ts_ms"]
        assert first["signal_available_ts_ms"] > first["signal_open_ts_ms"]


def test_same_bar_stop_precedes_roi() -> None:
    data = frame(260)
    original = screen.signals
    try:
        def fixed(candidate):
            entry = pd.Series(False, index=candidate.index)
            exit_ = pd.Series(False, index=candidate.index)
            entry.iloc[210] = True
            candidate.loc[211, "low"] = 1.0
            candidate.loc[211, "high"] = 1000.0
            return entry, exit_
        screen.signals = fixed
        trades, _, _ = screen.replay_symbol("BTC-USDT", data, 10.0)
        assert trades[0]["exit_reason"] == "STOP_FIRST"
    finally:
        screen.signals = original


def test_end_position_is_unresolved_not_forced_closed() -> None:
    data = frame(260)
    original_end = screen.END_MS
    original = screen.signals
    try:
        screen.END_MS = int(data.iloc[-1].close_ts_ms)
        def last(candidate):
            entry = pd.Series(False, index=candidate.index)
            exit_ = pd.Series(False, index=candidate.index)
            entry.iloc[-2] = True
            return entry, exit_
        screen.signals = last
        trades, _, unresolved = screen.replay_symbol("BTC-USDT", data, 10.0)
        assert not trades and unresolved == 1
    finally:
        screen.END_MS = original_end
        screen.signals = original


def test_saved_result_rehash_cannot_hide_accounting_tamper(tmp_path: Path) -> None:
    trades = [{"symbol": "BTC-USDT", "gross_bps": 20.0, "cost_bps": 10.0}]
    value = {"trades": trades, "cost_1x": screen.summarize(trades, 1), "cost_2x": screen.summarize(trades, 2)}
    altered = copy.deepcopy(value)
    altered["cost_1x"]["Net_bps"] += 1
    path = tmp_path / "result.json"
    path.write_text(json.dumps(altered))
    loaded = json.loads(path.read_text())
    assert loaded["cost_1x"] != screen.summarize(loaded["trades"], 1)


def test_activation_binds_cost_source_period_and_files(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.py"
    source.write_text("x=1\n")
    monkeypatch.setattr(screen, "ROOT", tmp_path)
    head = "a" * 40
    value = {
        "schema": "zel.issue1388.alpha_screen_activation.v1", "issue": 1388,
        "candidate_id": screen.CANDIDATE_ID, "token": screen.ACTIVATION_TOKEN,
        "reviewed_source_sha": head, "source_commit": screen.SOURCE_COMMIT,
        "source_blob": screen.SOURCE_BLOB, "source_inventory_sha256": screen.SOURCE_INVENTORY_SHA256,
        "cost_sha256": screen.COST_SHA256, "period_ms": [screen.START_MS, screen.END_MS],
        "timeframe_min": 15, "global_heavy_group": screen.GLOBAL_HEAVY_GROUP,
        "order_authority": "BLOCKED", "promotion": False,
        "source_files_sha256": {"source.py": screen.file_sha256(source)},
    }
    path = tmp_path / "activation.json"
    path.write_text(json.dumps(value))
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("ISSUE1388_GLOBAL_HEAVY_GROUP", screen.GLOBAL_HEAVY_GROUP)
    assert screen.validate_activation(path, head)["candidate_id"] == screen.CANDIDATE_ID
    value["cost_sha256"] = "0" * 64
    path.write_text(json.dumps(value))
    with pytest.raises(screen.ScreenError, match="ACTIVATION_BINDING:cost_sha256"):
        screen.validate_activation(path, head)
