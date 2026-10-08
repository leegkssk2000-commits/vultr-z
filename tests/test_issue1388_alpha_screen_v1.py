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


def test_rsi_w1_open_position_at_gap_blocks_survivor(monkeypatch) -> None:
    data = frame_30m(12, start=screen.START_MS)
    data.loc[5:, "segment_id"] = "B"

    def fixed(candidate):
        long_signal = pd.Series(False, index=candidate.index)
        short_signal = pd.Series(False, index=candidate.index)
        long_signal.iloc[1] = True
        short_signal.iloc[8] = True
        return long_signal, short_signal

    monkeypatch.setattr(screen, "rsi_w1_signals", fixed)
    trades, _, _, _, quarantined = screen.replay_rsi_w1_symbol("BTC-USDT", data, 14.0)
    assert quarantined == 1
    market = {
        "frames": {symbol: data.copy() for symbol in screen.SYMBOLS},
        "costs": {symbol: 14.0 for symbol in screen.SYMBOLS},
    }
    result = screen.screen(market, screen.PROFILES[screen.RSI_W1_ID])
    assert result["disposition"] == "BLOCKED_INPUT_GAP_WITH_OPEN_STATE"
    assert result["census"]["missing_fill_evidence"] == 1


def test_load_market_derives_complete_1h_from_supported_30m_loader(tmp_path: Path, monkeypatch) -> None:
    from backend.research.rebuild import scalp7_source_data_v2 as source

    start = screen.START_MS - screen.WARMUP_MS
    rows = int((screen.END_MS - start) / 1_800_000)
    base = frame_30m(rows, start=start)
    base.attrs = {
        "source_inventory_sha256": screen.SOURCE_INVENTORY_SHA256,
        "minute_gaps": [],
        "incomplete_buckets": [],
    }
    observed: list[int] = []

    def fake_load(root, timeframe, cache_dir):
        observed.append(timeframe)
        return {symbol: base.copy() for symbol in screen.SYMBOLS}

    cost_path = tmp_path / "cost.json"
    cost_path.write_text(json.dumps({"costs_bps": {symbol: 14.0 for symbol in screen.SYMBOLS}}))
    monkeypatch.setattr(source, "load_candles", fake_load)
    monkeypatch.setattr(screen, "COST_PATH", cost_path)
    monkeypatch.setattr(screen, "COST_SHA256", screen.file_sha256(cost_path))
    market = screen.load_market(tmp_path, screen.PROFILES[screen.ETH_SESSION_ID])
    assert observed == [30]
    eth = market["frames"]["ETH-USDT"]
    assert int(eth.iloc[-1].close_ts_ms) == screen.END_MS
    assert eth.open_ts_ms.diff().dropna().eq(3_600_000).all()
    assert eth.attrs["derived_from_timeframe_min"] == 30


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


def test_eth_density_uses_prior_completed_day_and_counts_transitions() -> None:
    start = pd.Timestamp("2026-01-13T00:00:00Z").value // 1_000_000
    rows = []
    for i in range(72):
        open_ms = start + i * 3_600_000
        price = 100.0
        hour = pd.Timestamp(open_ms, unit="ms", tz="UTC").hour
        day = i // 24
        if hour >= 17 or hour < 5:
            price += day
        elif day == 0:
            price += hour
        elif day == 1:
            price -= hour
        rows.append({
            "open_ts_ms": open_ms, "close_ts_ms": open_ms + 3_600_000,
            "available_ts_ms": open_ms + 3_600_000, "segment_id": "A",
            "open": price, "high": price + 1, "low": price - 1,
            "close": price, "volume": 1.0,
        })
    data = pd.DataFrame(rows)
    available, transitions = screen.eth_session_decisions(data)
    decision_hours = [pd.Timestamp(int(data.loc[idx, "open_ts_ms"]), unit="ms", tz="UTC").hour for idx in data.index[available]]
    assert decision_hours[0] == 17  # first 05:00 has no completed prior day input
    assert set(decision_hours) == {5, 17}
    assert int(transitions.sum()) <= int(available.sum())
    first_day_decision = data.index[
        (data.open_ts_ms == pd.Timestamp("2026-01-14T05:00:00Z").value // 1_000_000)
    ][0]
    assert bool(available.loc[first_day_decision])


def test_eth_density_counts_zero_prior_day_return_as_cash_transition() -> None:
    start = pd.Timestamp("2026-01-13T00:00:00Z").value // 1_000_000
    rows = []
    for i in range(36):
        open_ms = start + i * 3_600_000
        rows.append({
            "open_ts_ms": open_ms, "close_ts_ms": open_ms + 3_600_000,
            "available_ts_ms": open_ms + 3_600_000, "segment_id": "A",
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
            "volume": 1.0,
        })
    data = pd.DataFrame(rows)
    available, transitions = screen.eth_session_decisions(data)
    at_17 = data.index[data.open_ts_ms == pd.Timestamp("2026-01-13T17:00:00Z").value // 1_000_000][0]
    at_05 = data.index[data.open_ts_ms == pd.Timestamp("2026-01-14T05:00:00Z").value // 1_000_000][0]
    assert bool(transitions.loc[at_17])  # cash -> long night
    assert bool(available.loc[at_05])
    assert bool(transitions.loc[at_05])  # long night -> cash day


def test_eth_density_uses_completed_boundary_closes_not_current_opens() -> None:
    start = pd.Timestamp("2026-01-13T00:00:00Z").value // 1_000_000
    rows = []
    for i in range(36):
        open_ms = start + i * 3_600_000
        close = 100.0 + (i if 5 <= i <= 16 else 0.0)
        rows.append({
            "open_ts_ms": open_ms, "close_ts_ms": open_ms + 3_600_000,
            "available_ts_ms": open_ms + 3_600_000, "segment_id": "A",
            "open": close, "high": close + 1, "low": close - 1,
            "close": close, "volume": 1.0,
        })
    data = pd.DataFrame(rows)
    baseline = screen.eth_session_decisions(data)
    changed = data.copy()
    changed.loc[changed.open_ts_ms.map(lambda value: pd.Timestamp(int(value), unit="ms", tz="UTC").hour in (5, 17)), "open"] *= 10
    after = screen.eth_session_decisions(changed)
    assert baseline[0].tolist() == after[0].tolist()
    assert baseline[1].tolist() == after[1].tolist()


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


def test_hansen_recovery_uses_new_one_shot_token_without_changing_permanent_refs() -> None:
    profile = screen.PROFILES[screen.HANSEN_ID]
    assert profile["activation_token"] == "[issue1388-alpha-screen-10-hansen-1h-v1]"
    assert profile["execution_ref"] == "refs/heads/research-execution-consumptions/issue1388-cheap-hansen-1h-v1"
    assert profile["result_ref"] == "refs/heads/research-results/issue1388-cheap-hansen-1h-v1"


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


def test_btc_shock_log_threshold_is_not_simple_return() -> None:
    # -1.495% arithmetic is below the exact log threshold, but above simple -1.5%.
    data = frame_30m(6, screen.START_MS)
    data = screen.aggregate_30m_to_1h(data)
    data.loc[:, 'close'] = [100.0, 98.505, 98.505]
    assert screen.btc_shock_signals(data).tolist() == [False, True, False]


def test_btc_shock_counts_consecutive_events_without_exit_or_pnl() -> None:
    data = screen.aggregate_30m_to_1h(frame_30m(8, screen.START_MS))
    data.loc[:, 'close'] = [100.0, 98.0, 96.0, 96.0]
    market = {'frames': {s: data.copy() for s in screen.SYMBOLS}}
    result = screen.density_census(market, [screen.BTC_SHOCK_ID])
    value = result['candidates'][screen.BTC_SHOCK_ID]
    assert value['source_native_btc']['raw_signal_bars'] == 2
    assert value['source_native_btc']['source_exact_episodes'] == 2
    assert result['economic_screen_consumed'] == 0
    assert 'trades' not in result and 'cost_1x' not in result


def test_btc_shock_never_bridges_missing_hour_or_segment() -> None:
    data = screen.aggregate_30m_to_1h(frame_30m(8, screen.START_MS))
    data.loc[:, 'close'] = [100.0, 90.0, 80.0, 70.0]
    data.loc[1, 'segment_id'] = 'B'
    data.loc[2:, 'segment_id'] = 'B'
    data.loc[3, 'open_ts_ms'] += 3600000
    assert screen.btc_shock_signals(data).tolist() == [False, False, True, False]


def test_btc_shock_signal_is_past_only() -> None:
    data = screen.aggregate_30m_to_1h(frame_30m(8, screen.START_MS))
    data.loc[:, 'close'] = [100.0, 98.0, 96.0, 96.0]
    original = screen.btc_shock_signals(data)
    data.loc[3, 'close'] = 1.0
    assert screen.btc_shock_signals(data).iloc[:3].equals(original.iloc[:3])


def shock_frame(hours=32):
    data = screen.aggregate_30m_to_1h(frame_30m(hours * 2, screen.START_MS))
    data.loc[:, 'close'] = 100.0
    data.loc[1:, 'close'] = 98.0
    return data


def test_shock_event_deadline_entry_and_occupied_boundary() -> None:
    data = shock_frame()
    data.loc[13:, 'close'] = 96.0  # event directly before deadline; rejected while occupied
    trades, attempts, rejected, unresolved, gaps = screen.replay_btc_shock_symbol('BTC-USDT', data, 14)
    assert (attempts, rejected, unresolved, gaps) == (2, 1, 0, 0)
    assert len(trades) == 1
    assert trades[0]['entry_ts_ms'] == int(data.iloc[2].open_ts_ms)
    assert trades[0]['exit_ts_ms'] == int(data.iloc[14].open_ts_ms)
    assert trades[0]['exit_ts_ms'] == int(data.iloc[1].close_ts_ms) + 12 * 3600000
    assert trades[0]['net_bps'] == trades[0]['gross_bps'] - 14


def test_shock_gap_and_end_never_invent_exit() -> None:
    data = shock_frame(8)
    trades, _, _, unresolved, gaps = screen.replay_btc_shock_symbol('BTC-USDT', data, 14)
    assert trades == [] and unresolved == 1 and gaps == 0
    data.loc[4:, 'segment_id'] = 'B'
    trades, _, _, unresolved, gaps = screen.replay_btc_shock_symbol('BTC-USDT', data, 14)
    assert trades == [] and gaps == 1 and unresolved == 1


def test_shock_delayed_receipt_does_not_extend_deadline() -> None:
    data = shock_frame()
    data.loc[1, 'available_ts_ms'] = int(data.iloc[4].open_ts_ms)
    trades, _, _, _, _ = screen.replay_btc_shock_symbol('BTC-USDT', data, 14)
    assert trades[0]['entry_ts_ms'] == int(data.iloc[4].open_ts_ms)
    assert trades[0]['exit_ts_ms'] == int(data.iloc[14].open_ts_ms)


def test_shock_requires_nonzero_saved_density_bound_to_input_before_claim() -> None:
    data = shock_frame()
    market = {'frames': {s: data.copy() for s in screen.SYMBOLS}, 'costs': {s:14.0 for s in screen.SYMBOLS}}
    proof = screen.density_census(market, [screen.BTC_SHOCK_ID])
    proof.pop('result_sha256')
    receipt = screen.source_receipt(market, screen.PROFILES[screen.BTC_SHOCK_ID])
    proof['receipts'] = {'60':receipt}
    proof['result_sha256'] = screen.digest(proof)
    screen.validate_btc_preflight({'density_preflight':proof}, receipt)
    altered = copy.deepcopy(proof)
    altered['candidates'][screen.BTC_SHOCK_ID]['source_native_btc']['raw_signal_bars'] = 0
    altered.pop('result_sha256')
    altered['result_sha256'] = screen.digest(altered)
    with pytest.raises(screen.ScreenError, match='ZERO_OR_UNCONFIRMED_DENSITY'):
        screen.validate_btc_preflight({'density_preflight':altered}, receipt)
    with pytest.raises(screen.ScreenError, match='PREFLIGHT_INPUT_DRIFT'):
        screen.validate_btc_preflight({'density_preflight':proof}, {**receipt, 'cost_sha256':'tampered'})


def test_shock_density_excludes_unavailable_or_end_boundary_event() -> None:
    data = shock_frame(4)
    data.loc[1, 'available_ts_ms'] = screen.END_MS
    market = {'frames': {s:data.copy() for s in screen.SYMBOLS}}
    result = screen.density_census(market, [screen.BTC_SHOCK_ID])
    assert result['candidates'][screen.BTC_SHOCK_ID]['source_native_btc']['raw_signal_bars'] == 0
    data.loc[1, 'available_ts_ms'] = int(data.iloc[1].close_ts_ms)
    old_end = screen.END_MS
    try:
        screen.END_MS = int(data.iloc[1].close_ts_ms)
        result = screen.density_census({'frames':{s:data.copy() for s in screen.SYMBOLS}}, [screen.BTC_SHOCK_ID])
        assert result['candidates'][screen.BTC_SHOCK_ID]['source_native_btc']['raw_signal_bars'] == 0
    finally:
        screen.END_MS = old_end


def test_shock_terminal_unknown_cannot_be_survivor() -> None:
    data = shock_frame(8)
    market = {'frames': {s:data.copy() for s in screen.SYMBOLS}, 'costs': {s:14.0 for s in screen.SYMBOLS}}
    result = screen.screen(market, screen.PROFILES[screen.BTC_SHOCK_ID])
    assert result['census']['unresolved_end'] == 1
    assert result['disposition'] == 'BLOCKED_TERMINAL_OUTCOME_UNRESOLVED'
    assert result['funding_bps'] is None and result['mark_account_NAV'] is None


@pytest.mark.parametrize('gross', [-100.0, 100.0])
def test_shock_missing_funding_blocks_both_economic_verdicts(monkeypatch, gross) -> None:
    data = shock_frame()
    trade = {'identity':screen.BTC_SHOCK_ID, 'symbol':'BTC-USDT', 'exit_ts_ms':screen.START_MS+3600000, 'gross_bps':gross, 'cost_bps':14.0, 'net_bps':gross-14.0}
    monkeypatch.setattr(screen, 'replay_btc_shock_symbol', lambda *args:([trade], 1, 0, 0, 0))
    market = {'frames':{'BTC-USDT':data}, 'costs':{'BTC-USDT':14.0}}
    result = screen.screen(market, screen.PROFILES[screen.BTC_SHOCK_ID])
    assert result['disposition'] == 'BLOCKED_MISSING_FUNDING'
    assert result['funding_bps'] is None
    assert result['cost_1x']['Net_bps'] == gross - 14.0  # explicit scenario diagnostic only


def test_btc_funding_archive_is_complete_and_hash_bound() -> None:
    rows = screen.load_btc_funding()
    assert len(rows) == 465
    assert rows[0]['fundingTime'] == screen.START_MS
    assert rows[-1]['fundingTime'] == screen.END_MS - 8 * 3600000
    raw = screen.read_json(screen.INTAKE_PATH.parent / 'BTC_FUNDING_RAW.json')
    raw['data'].pop()
    with pytest.raises(screen.ScreenError, match='FIXED_WINDOW_COVERAGE'):
        screen.validate_btc_funding(raw)


def test_btc_funding_signed_mark_notional_and_adverse_boundary() -> None:
    trade = {'entry_ts_ms':100, 'exit_ts_ms':300, 'entry_price':100.0}
    rows = [{'fundingTime':100,'fundingRate':'0.001','markPrice':'100'},
            {'fundingTime':200,'fundingRate':'-0.001','markPrice':'110'},
            {'fundingTime':300,'fundingRate':'-0.002','markPrice':'120'}]
    value, count = screen.funding_for_btc_trade(trade, rows)
    assert value == pytest.approx(-1.0)  # boundary debit10 + interior credit-11; boundary credit omitted
    assert count == 2
    rows[-1]['fundingRate'] = '0.002'
    value, count = screen.funding_for_btc_trade(trade, rows)
    assert value == pytest.approx(23.0) and count == 3


def test_btc_funding_remains_signed_when_taker_costs_are_stressed() -> None:
    trades = [{'symbol':'BTC-USDT','exit_ts_ms':200,'gross_bps':100.0,'cost_bps':14.0,'funding_bps':-5.0}]
    assert screen.summarize(trades,1)['Net_bps'] == 91.0
    assert screen.summarize(trades,2)['Net_bps'] == 77.0
    assert screen.summarize(trades,2)['Cost_bps'] == 23.0
    assert screen.summarize(trades,2)['Funding_bps'] == -5.0


def test_btc_bound_funding_resolves_only_cost_block_not_terminal(monkeypatch) -> None:
    data = shock_frame()
    trade = {'identity':screen.BTC_SHOCK_ID,'symbol':'BTC-USDT','entry_ts_ms':screen.START_MS+2*3600000,'exit_ts_ms':screen.START_MS+14*3600000,'entry_price':100.0,'gross_bps':-100.0,'cost_bps':14.0,'net_bps':-114.0}
    monkeypatch.setattr(screen,'replay_btc_shock_symbol',lambda *args:([trade.copy()],1,0,0,0))
    market = {'frames':{'BTC-USDT':data},'costs':{'BTC-USDT':14.0},'btc_funding':screen.load_btc_funding()}
    result = screen.screen(market,screen.PROFILES[screen.BTC_SHOCK_ID])
    assert result['disposition'] == 'REJECT_ECONOMIC_EARLY'
    assert result['funding_bps'] is not None
    monkeypatch.setattr(screen,'replay_btc_shock_symbol',lambda *args:([trade.copy()],2,0,1,0))
    assert screen.screen(market,screen.PROFILES[screen.BTC_SHOCK_ID])['disposition'] == 'BLOCKED_TERMINAL_OUTCOME_UNRESOLVED'


def ema800_fixture():
    stamps = [screen.START_MS - 801 * 3600000 + i * 3600000 for i in range(805)]
    values = [100.] * 800 + [101., 102., 98., 101., 102.]
    return pd.DataFrame({'open_ts_ms':stamps,'close_ts_ms':[t+3600000 for t in stamps],
                         'available_ts_ms':[t+3600000 for t in stamps],
                         'segment_id':['one']*805,'close':values,'volume':[1.]*805})


def test_ema800_exact_sma_seed_cross_and_prefix_causality():
    f=ema800_fixture(); raw,ready=screen.ema800_entry_signals(f)
    assert not ready.iloc[:799].any() and ready.iloc[799:].all()
    assert raw[raw].index.tolist()==[800,803]
    prefix,_=screen.ema800_entry_signals(f.iloc[:802])
    assert prefix.equals(raw.iloc[:802])
    f.loc[804,'close']=1e8
    assert screen.ema800_entry_signals(f)[0].iloc[:804].equals(raw.iloc[:804])


def test_ema800_volume_guard_and_gap_warmup_reset():
    f=ema800_fixture();f.loc[800,'volume']=0
    assert screen.ema800_entry_signals(f)[0][lambda x:x].index.tolist()==[803]
    f.loc[802:,'segment_id']='two'
    raw,ready=screen.ema800_entry_signals(f)
    assert not raw.iloc[802:].any() and not ready.iloc[802:].any()
    f=ema800_fixture();f.loc[802,'open_ts_ms']+=3600000
    with pytest.raises(screen.ScreenError,match='SEGMENT_GAP'):screen.ema800_entry_signals(f)


def test_ema800_density_never_calls_economic_model_and_separates_universe(monkeypatch):
    f=ema800_fixture()
    monkeypatch.setattr(screen,'summarize',lambda *a:pytest.fail('PNL forbidden in density'))
    monkeypatch.setattr(screen,'replay_symbol',lambda *a:pytest.fail('model forbidden in density'))
    result=screen.density_census({'frames':{s:f.copy() for s in screen.SYMBOLS}},[screen.EMA800_ID])
    c=result['candidates'][screen.EMA800_ID]
    assert c['raw_signal_bars']==6 and c['source_exact_episodes']==6
    assert set(c['source_native_overlap'])=={'BTC-USDT','ETH-USDT','XRP-USDT'}
    assert set(c['warmup_ready_bars_by_symbol'])==set(screen.SYMBOLS)
    assert result['economic_screen_consumed']==0 and 'trades' not in c


def test_ema_profile_requires_complete_bound_activation(tmp_path):
    p=tmp_path/'activation.json';p.write_text(json.dumps({'candidate_id':screen.EMA800_ID}))
    with pytest.raises(screen.ScreenError,match='ACTIVATION_BINDING'):screen.validate_activation(p,'a'*40)

