import pandas as pd
import pytest

from ops import issue1388_alpha_screen_v1 as screen


def frame_for(closes: list[str]) -> pd.DataFrame:
    close_ts = pd.to_datetime(closes, utc=True)
    close_ms = close_ts.astype("int64") // 1_000_000
    return pd.DataFrame({
        "open_ts_ms": close_ms - 3_600_000,
        "close_ts_ms": close_ms,
        "available_ts_ms": close_ms,
        "segment_id": ["s1"] * len(closes),
    })


def test_monday_drift_uses_completed_close_clock_only():
    frame = frame_for([
        "2026-01-11T23:00:00Z",
        "2026-01-12T00:00:00Z",
        "2026-01-12T01:00:00Z",
        "2026-01-13T00:00:00Z",
    ])
    assert screen.monday_drift_entry_signals(frame).tolist() == [False, True, False, False]


def test_monday_drift_rejects_incomplete_or_premature_bars():
    incomplete = frame_for(["2026-01-12T00:00:00Z"])
    incomplete.loc[0, "open_ts_ms"] += 1
    with pytest.raises(screen.ScreenError, match="ONE_HOUR_COMPLETED"):
        screen.monday_drift_entry_signals(incomplete)
    premature = frame_for(["2026-01-12T00:00:00Z"])
    premature.loc[0, "available_ts_ms"] -= 1
    with pytest.raises(screen.ScreenError, match="PREMATURE_AVAILABILITY"):
        screen.monday_drift_entry_signals(premature)


def test_monday_drift_density_is_btc_native_and_no_pnl(monkeypatch):
    frame = frame_for(["2026-01-12T00:00:00Z", "2026-01-19T00:00:00Z"])
    monkeypatch.setattr(screen, "START_MS", int(frame.open_ts_ms.min()))
    monkeypatch.setattr(screen, "END_MS", int(frame.close_ts_ms.max()) + 1)
    market = {"frames": {symbol: frame.copy() for symbol in screen.SYMBOLS}, "costs": {symbol: 10.0 for symbol in screen.SYMBOLS}}
    result = screen.density_census(market, [screen.MONDAY_DRIFT_ID])
    candidate = result["candidates"][screen.MONDAY_DRIFT_ID]
    assert candidate["source_exact_episodes"] == 2
    assert candidate["symbols_with_episodes"] == 1
    assert candidate["source_native_btc"]["source_exact_episodes"] == 2
    assert candidate["by_symbol"]["ETH-USDT"]["source_exact_episodes"] == 0
    assert result["economic_screen_consumed"] == 0
    assert "trades" not in candidate and "net" not in candidate
