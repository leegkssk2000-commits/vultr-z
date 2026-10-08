from __future__ import annotations

import pandas as pd
import pytest

from ops import issue1388_alpha_screen_v1 as screen


def oversold_frame(rows: int = 1254) -> pd.DataFrame:
    start = screen.START_MS - 1250 * 3_600_000
    close = [100.0 + float(i % 2) for i in range(rows)]
    close[1250] = 60.0
    close[1251] = 61.0
    return pd.DataFrame({
        "open_ts_ms": [start + i * 3_600_000 for i in range(rows)],
        "close_ts_ms": [start + (i + 1) * 3_600_000 for i in range(rows)],
        "available_ts_ms": [start + (i + 1) * 3_600_000 for i in range(rows)],
        "segment_id": ["one"] * rows,
        "open": close,
        "high": [value * 1.001 for value in close],
        "low": [value * 0.999 for value in close],
        "close": close,
        "volume": [1.0] * rows,
    })


def test_oversold_reversion_exact_cross_dislocation_and_prefix_causality() -> None:
    frame = oversold_frame()
    raw, ready = screen.oversold_reversion_entry_signals(frame)
    assert not ready.iloc[:1249].any()
    assert ready.iloc[1249:].all()
    assert raw[raw].index.tolist() == [1250]

    prefix, _ = screen.oversold_reversion_entry_signals(frame.iloc[:1252].copy())
    assert prefix.equals(raw.iloc[:1252])
    changed = frame.copy()
    changed.loc[1252:, "close"] = 1e8
    assert screen.oversold_reversion_entry_signals(changed)[0].iloc[:1252].equals(raw.iloc[:1252])


def test_oversold_reversion_requires_positive_volume_and_strict_conditions(monkeypatch) -> None:
    frame = oversold_frame()
    frame.loc[1250, "volume"] = 0.0
    raw, _ = screen.oversold_reversion_entry_signals(frame)
    assert not raw.any()

    rsi = pd.Series(50.0, index=frame.index)
    rsi.iloc[1250] = 30.0
    monkeypatch.setattr(screen, "_rsi", lambda close, period: rsi.copy())
    assert not screen.oversold_reversion_entry_signals(frame)[0].any()


def test_oversold_reversion_segment_reset_and_gap_fail_closed() -> None:
    frame = oversold_frame()
    frame.loc[1250:, "segment_id"] = "two"
    raw, ready = screen.oversold_reversion_entry_signals(frame)
    assert not raw.iloc[1250:].any()
    assert not ready.iloc[1250:].any()

    frame = oversold_frame()
    frame.loc[1252, "open_ts_ms"] += 3_600_000
    with pytest.raises(screen.ScreenError, match="OVERSOLD_REVERSION_CENSUS_SEGMENT_GAP"):
        screen.oversold_reversion_entry_signals(frame)


def test_oversold_density_is_signal_only_and_never_calls_economic_model(monkeypatch) -> None:
    frame = oversold_frame()
    market = {"frames": {symbol: frame.copy() for symbol in screen.SYMBOLS}}
    monkeypatch.setattr(screen, "summarize", lambda *args: pytest.fail("PnL forbidden in density"))
    monkeypatch.setattr(screen, "replay_symbol", lambda *args: pytest.fail("replay forbidden in density"))

    result = screen.density_census(market, [screen.OVERSOLD_REVERSION_ID])
    candidate = result["candidates"][screen.OVERSOLD_REVERSION_ID]
    assert candidate["source_exact_episodes"] == 6
    assert candidate["symbols_with_episodes"] == 6
    assert candidate["source_native_lifecycle_bound"] is False
    assert candidate["economic_screen_ready"] is False
    assert result["economic_screen_consumed"] == 0
    assert result["order_authority"] == "BLOCKED"
    forbidden = {"trades", "exits", "cost_1x", "net", "PF", "outcomes"}
    assert forbidden.isdisjoint(result)
    assert forbidden.isdisjoint(candidate)


def test_oversold_profile_rejects_economic_activation_before_io(monkeypatch, tmp_path) -> None:
    activation = {"candidate_id": screen.OVERSOLD_REVERSION_ID}
    monkeypatch.setattr(screen, "current_head", lambda: "a" * 40)
    monkeypatch.setattr(screen, "read_json", lambda path: activation)
    monkeypatch.setattr(screen, "load_market", lambda *args: pytest.fail("market load forbidden"))
    monkeypatch.setattr(screen, "create_record", lambda *args: pytest.fail("Git write forbidden"))

    with pytest.raises(screen.ScreenError, match="DENSITY_ONLY_PROFILE_NO_ECONOMIC_ACTIVATION"):
        screen.execute(tmp_path, tmp_path / "activation.json", tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_oversold_density_workflow_binds_exact_source_review_without_shadowing() -> None:
    workflow = (screen.ROOT / ".github/workflows/issue1388-internet-alpha-v1.yml").read_text()
    density = workflow.split("  density-preflight-003:", 1)[1].split("  cheap-screen-003:", 1)[0]
    assert "import hashlib, json, os, subprocess" in density
    assert "[issue1388-density-preflight-9-v1]" in density
    assert "['E_FT_OVERSOLD_REVERSION_1H_V1'] if number == '009'" in density
    assert "source_review_sha256" in density and "pre_screen_thesis_sha256" in density
    assert "source_review = json.loads(review.read_bytes())" in density
    assert "source = json.loads(review.read_bytes())" not in density
    assert "--density-candidates '${{ steps.activation.outputs.candidate_ids }}'" in density
