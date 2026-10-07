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
            "segment_id": "A",
            "open": open_, "high": open_ * 1.004, "low": open_ * 0.996,
            "close": open_, "volume": 1.0,
        })
    return pd.DataFrame(values)


def frame_30m(rows: int = 1600, start: int | None = None) -> pd.DataFrame:
    start = start if start is not None else screen.START_MS - 32 * 86_400_000
    values = []
    price = 100.0
    for i in range(rows):
        price *= 1 + (0.001 if i % 11 < 5 else -0.0012)
        values.append({
            "open_ts_ms": start + i * 1_800_000,
            "close_ts_ms": start + (i + 1) * 1_800_000,
            "available_ts_ms": start + (i + 1) * 1_800_000,
            "segment_id": "A", "open": price * 1.001, "high": price * 1.004,
            "low": price * 0.996, "close": price, "volume": 1.0,
        })
    return pd.DataFrame(values)


def test_signals_are_past_only_and_entry_is_next_open() -> None:
    data = frame()
    entry, _ = screen.signals(data)
    indexes = list(data.index[entry])
    assert indexes
    trades, _, _, _, _ = screen.replay_symbol("BTC-USDT", data, 10.0)
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
        trades, _, _, _, _ = screen.replay_symbol("BTC-USDT", data, 10.0)
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
        trades, _, _, unresolved, _ = screen.replay_symbol("BTC-USDT", data, 10.0)
        assert not trades and unresolved == 1
    finally:
        screen.END_MS = original_end
        screen.signals = original


def test_gap_resets_indicators_and_quarantines_open_position() -> None:
    data = frame(320)
    data.loc[212:, "segment_id"] = "B"
    original = screen.signals
    try:
        def fixed(candidate):
            entry = pd.Series(False, index=candidate.index)
            exit_ = pd.Series(False, index=candidate.index)
            entry.iloc[210] = True
            return entry, exit_
        screen.signals = fixed
        trades, signals, _, unresolved, quarantined = screen.replay_symbol("BTC-USDT", data, 10.0)
        assert not trades and unresolved == 0 and quarantined == 1
        assert signals == 1
    finally:
        screen.signals = original

    actual_entry, _ = screen.signals(data)
    isolated_entry, _ = screen.signals(data.loc[212:].copy())
    assert actual_entry.loc[212:].tolist() == isolated_entry.tolist()


def test_rsi_matches_talib_wilder_seed_and_zero_loss_cases() -> None:
    seeded = screen._rsi(pd.Series([1.0, 2.0, 3.0, 2.0, 3.0]), 3)
    assert seeded.iloc[:3].isna().all()
    assert seeded.iloc[3] == pytest.approx(66.66666666666667)
    assert seeded.iloc[4] == pytest.approx(77.77777777777777)
    rising = screen._rsi(pd.Series([1.0, 2.0, 3.0, 4.0, 5.0]), 3)
    assert rising.iloc[3:].tolist() == [100.0, 100.0]
    flat = screen._rsi(pd.Series([1.0, 1.0, 1.0, 1.0]), 3)
    assert flat.iloc[3] == 0.0


def test_cenderawasih_source_exact_wma_uses_prior_bars_only() -> None:
    values = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    actual = screen._tv_wma(values, 4)
    # Donor loop uses shift(1) weight 12 and shift(2) weight 8.
    assert actual.iloc[2] == pytest.approx((2.0 * 12 + 1.0 * 8) / 20)
    changed = values.copy()
    changed.iloc[3:] = 999.0
    assert screen._tv_wma(changed, 4).iloc[2] == actual.iloc[2]


def test_cenderawasih_informative_values_arrive_only_after_bucket_close() -> None:
    start = 0
    data = frame_30m(8, start=start)
    data.loc[:3, "close"] = 100.0
    data.loc[4:, "close"] = 110.0
    pct, _ = screen._informative_at_bar_close(data)
    assert pct.iloc[:7].isna().all()
    assert pct.iloc[7] == pytest.approx(0.10)


def test_cenderawasih_daily_age_guard_needs_thirty_completed_days() -> None:
    data = frame_30m(30 * 48 + 1, start=0)
    _, age = screen._informative_at_bar_close(data)
    assert not age.iloc[: 30 * 48 - 1].any()
    assert bool(age.iloc[30 * 48 - 1])
    assert bool(age.iloc[-1])  # incomplete day 31 does not fabricate a new daily bar


def test_cenderawasih_volume_guard_uses_presence_not_magnitude() -> None:
    data = frame_30m()
    btc = data.copy()
    first = screen.cenderawasih_signals("ETH-USDT", data, btc)
    scaled = data.copy()
    scaled["volume"] = scaled.volume * 1_000_000
    btc_scaled = btc.copy()
    btc_scaled["volume"] = btc_scaled.volume * 0.000001
    second = screen.cenderawasih_signals("ETH-USDT", scaled, btc_scaled)
    assert first[0].tolist() == second[0].tolist()
    assert first[1].tolist() == second[1].tolist()


def test_cenderawasih_future_btc_close_does_not_change_prior_signal() -> None:
    data = frame_30m()
    btc = data.copy()
    before = screen.cenderawasih_signals("ETH-USDT", data, btc)[0]
    btc.loc[1200:, "close"] *= 10
    after = screen.cenderawasih_signals("ETH-USDT", data, btc)[0]
    assert before.iloc[:1200].tolist() == after.iloc[:1200].tolist()


def test_cenderawasih_next_open_and_same_bar_trailing_are_conservative(monkeypatch) -> None:
    data = frame_30m(20, start=screen.START_MS)

    def fixed(symbol, candidate, btc):
        entry = pd.Series(False, index=candidate.index)
        exit_ = pd.Series(False, index=candidate.index)
        entry.iloc[2] = True
        candidate.loc[3, "high"] = candidate.loc[3, "open"] * 1.20
        candidate.loc[3, "low"] = candidate.loc[3, "open"] * 0.90
        return entry, exit_

    monkeypatch.setattr(screen, "cenderawasih_signals", fixed)
    trades, _, _, _, _ = screen.replay_cenderawasih_symbol("ETH-USDT", data, data.copy(), 10.0)
    assert trades[0]["entry_ts_ms"] == int(data.iloc[3].open_ts_ms)
    assert trades[0]["entry_ts_ms"] >= trades[0]["signal_available_ts_ms"]
    assert trades[0]["exit_reason"] == "TRAILING_STOP_SAME_BAR_WORST_CASE"
    assert trades[0]["exit_price"] == pytest.approx(float(data.iloc[3].high) * 0.99)


def test_rsi_w1_is_completed_bar_only_and_future_invariant() -> None:
    data = frame_30m(80, start=screen.START_MS - 20 * 1_800_000)
    data.loc[5:15, "close"] *= 1.20
    before = screen.rsi_w1_signals(data)
    changed = data.copy()
    changed.loc[60:, "close"] *= 10
    after = screen.rsi_w1_signals(changed)
    assert before[0].iloc[:60].tolist() == after[0].iloc[:60].tolist()
    assert before[1].iloc[:60].tolist() == after[1].iloc[:60].tolist()


def test_rsi_w1_flip_uses_next_open_and_short_direction(monkeypatch) -> None:
    data = frame_30m(12, start=screen.START_MS)

    def fixed(candidate):
        long_signal = pd.Series(False, index=candidate.index)
        short_signal = pd.Series(False, index=candidate.index)
        long_signal.iloc[1] = True
        short_signal.iloc[4] = True
        return long_signal, short_signal

    monkeypatch.setattr(screen, "rsi_w1_signals", fixed)
    trades, transitions, _, unresolved, _ = screen.replay_rsi_w1_symbol("BTC-USDT", data, 14.0)
    assert transitions == 2 and len(trades) == 1 and unresolved == 1
    assert trades[0]["entry_ts_ms"] == int(data.iloc[2].open_ts_ms)
    assert trades[0]["exit_ts_ms"] == int(data.iloc[5].open_ts_ms)
    assert trades[0]["signal_available_ts_ms"] <= trades[0]["entry_ts_ms"]
    assert trades[0]["exit_reason"] == "NEXT_OPEN_OPPOSITE_EXTREME_FLIP"


def test_density_census_has_no_pnl_and_keeps_source_native_btc_separate(monkeypatch) -> None:
    market = {"frames": {symbol: frame_30m(20, start=screen.START_MS) for symbol in screen.SYMBOLS}, "costs": {symbol: 14.0 for symbol in screen.SYMBOLS}}

    def fixed(candidate):
        long_signal = pd.Series(False, index=candidate.index)
        short_signal = pd.Series(False, index=candidate.index)
        long_signal.iloc[1] = True
        short_signal.iloc[4] = True
        return long_signal, short_signal

    monkeypatch.setattr(screen, "rsi_w1_signals", fixed)
    result = screen.density_census(market, [screen.RSI_W1_ID])
    row = result["candidates"][screen.RSI_W1_ID]
    assert row["source_exact_episodes"] == 12
    assert row["source_native_btc"]["source_exact_episodes"] == 2
    assert result["economic_screen_consumed"] == 0
    assert "trades" not in result and "net" not in json.dumps(result).lower()


def test_bband_rsi_entry_uses_typical_price_and_completed_1h_segments() -> None:
    data = frame_30m(80, start=screen.START_MS)
    data["open_ts_ms"] = screen.START_MS + data.index * 3_600_000
    data["close_ts_ms"] = data.open_ts_ms + 3_600_000
    data["available_ts_ms"] = data.close_ts_ms
    signal = screen.bband_rsi_entry_signals(data)
    changed = data.copy()
    changed.loc[60:, "close"] *= 0.1
    assert signal.iloc[:60].tolist() == screen.bband_rsi_entry_signals(changed).iloc[:60].tolist()


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


def test_activation_selects_cenderawasih_profile(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.py"
    source.write_text("x=1\n")
    monkeypatch.setattr(screen, "ROOT", tmp_path)
    profile = screen.PROFILES[screen.CENDERAWASIH_ID]
    head = "b" * 40
    value = {
        "schema": "zel.issue1388.alpha_screen_activation.v1", "issue": 1388,
        "candidate_id": profile["candidate_id"], "token": profile["activation_token"],
        "reviewed_source_sha": head, "source_commit": profile["source_commit"],
        "source_blob": profile["source_blob"], "source_inventory_sha256": screen.SOURCE_INVENTORY_SHA256,
        "cost_sha256": screen.COST_SHA256, "period_ms": [screen.START_MS, screen.END_MS],
        "timeframe_min": 30, "global_heavy_group": screen.GLOBAL_HEAVY_GROUP,
        "order_authority": "BLOCKED", "promotion": False,
        "source_files_sha256": {"source.py": screen.file_sha256(source)},
    }
    path = tmp_path / "activation.json"
    path.write_text(json.dumps(value))
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("ISSUE1388_GLOBAL_HEAVY_GROUP", screen.GLOBAL_HEAVY_GROUP)
    assert screen.validate_activation(path, head)["candidate_id"] == screen.CENDERAWASIH_ID


def test_activation_binds_paper_version_and_sha_without_fake_git_identity(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.py"
    source.write_text("x=1\n")
    monkeypatch.setattr(screen, "ROOT", tmp_path)
    profile = screen.PROFILES[screen.RSI_W1_ID]
    head = "c" * 40
    value = {
        "schema": "zel.issue1388.alpha_screen_activation.v1", "issue": 1388,
        "candidate_id": profile["candidate_id"], "token": profile["activation_token"],
        "reviewed_source_sha": head, "source_version": profile["source_version"],
        "source_sha256": profile["source_sha256"], "source_inventory_sha256": screen.SOURCE_INVENTORY_SHA256,
        "cost_sha256": screen.COST_SHA256, "period_ms": [screen.START_MS, screen.END_MS],
        "timeframe_min": 30, "global_heavy_group": screen.GLOBAL_HEAVY_GROUP,
        "order_authority": "BLOCKED", "promotion": False,
        "source_files_sha256": {"source.py": screen.file_sha256(source)},
    }
    path = tmp_path / "activation.json"
    path.write_text(json.dumps(value))
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("ISSUE1388_GLOBAL_HEAVY_GROUP", screen.GLOBAL_HEAVY_GROUP)
    assert screen.validate_activation(path, head)["source_version"] == "arXiv:2503.18096v1"
    value["source_sha256"] = "0" * 64
    path.write_text(json.dumps(value))
    with pytest.raises(screen.ScreenError, match="ACTIVATION_BINDING:source_sha256"):
        screen.validate_activation(path, head)
