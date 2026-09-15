from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_fresh_forward_v2 as f


def frame(tf: int, count: int = 6) -> pd.DataFrame:
    width = tf * 60_000
    return pd.DataFrame(
        [
            {
                "open_ts_ms": i * width,
                "close_ts_ms": (i + 1) * width,
                "available_ts_ms": (i + 1) * width + 100,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1.0,
                "segment_id": 0,
            }
            for i in range(count)
        ]
    )


@pytest.fixture
def fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    config_path = tmp_path / "config.json"
    config_path.write_text("{}")
    config = {"fresh_start_ms": 1_800_000, "frozen_at_ms": 1_000_000, "regime_fit": {}}
    catalog = [
        {"identity": "TEST15", "tf": 15, "module": "TEST", "lane": "trend_rider"},
        {"identity": "TEST30", "tf": 30, "module": "TEST", "lane": "squeeze_break"},
    ]
    contract = {"candidates": catalog, "primary_identities": ["TEST15", "TEST30"]}
    monkeypatch.setattr(
        f, "read_config", lambda path: (config, contract, {s: 14.0 for s in f.SYMBOLS})
    )
    frames = {
        tf: {symbol: frame(tf, 6 if tf == 15 else 3) for symbol in f.SYMBOLS}
        for tf in (15, 30)
    }
    receipt = {
        "common_ends": {15: 5_400_000, 30: 5_400_000},
        "source_cursor_sha256": "a" * 64,
    }
    monkeypatch.setattr(
        f, "build_current_frames", lambda *args, **kwargs: (frames, frames, receipt)
    )
    monkeypatch.setattr(f, "bind_frozen_context", lambda frames, fit: frames)
    out = tmp_path / "out"
    f.initialize(out, config_path, now_ms=1_700_000)
    return {
        "out": out,
        "config_path": config_path,
        "config": config,
        "frames": frames,
        "receipt": receipt,
    }


def event(identity: str, opened: int, tf: int = 15) -> dict[str, Any]:
    return {
        "identity": identity,
        "lane": "trend_rider",
        "symbol": "BTC-USDT",
        "timeframe_min": tf,
        "side": 1,
        "signal_open_ts_ms": opened,
        "signal_ts_ms": opened + tf * 60_000 + 100,
        "segment_id": 0,
        "stop_price": 99,
        "max_hold_bars": 3,
    }


def test_no_historical_trade_credit_and_real_observation_time(
    fixture: dict[str, Any]
) -> None:
    def provider(spec: dict[str, Any], frames: dict, costs: dict) -> list[dict]:
        if spec["tf"] == 30:
            return []
        return [event(spec["identity"], 0), event(spec["identity"], 1_800_000)]

    result = f.poll(
        fixture["out"], fixture["config_path"], now_ms=6_000_000, provider=provider
    )
    assert result["new_signals"] == 1
    assert result["fresh_closed_trades"] == 0
    lines = (fixture["out"] / "fresh_signals.jsonl").read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["signal"]["signal_ts_ms"] == record["observed_at_ms"] == 6_000_000
    assert record["signal"]["original_feature_signal_ts_ms"] == 2_700_100
    assert record["signal"]["earliest_entry_ts_ms"] == 6_000_001
    assert record["previous_sha256"] == "0" * 64
    saved = record.pop("record_sha256")
    assert f.digest(record) == saved


def test_restart_no_duplicate_and_projection_recovery(fixture: dict[str, Any]) -> None:
    def provider(spec: dict, frames: dict, costs: dict) -> list[dict]:
        return [event(spec["identity"], 1_800_000, spec["tf"])]

    first = f.poll(
        fixture["out"], fixture["config_path"], now_ms=6_000_000, provider=provider
    )
    assert first["new_signals"] == 2
    path = fixture["out"] / "fresh_signals.jsonl"
    before = path.read_bytes()
    path.unlink()  # Crash after STATE commit but before first projection publish.
    second = f.poll(
        fixture["out"], fixture["config_path"], now_ms=6_100_000, provider=provider
    )
    assert second["state"] == "WAIT_NEW_COMPLETE_DECISION_BAR"
    assert path.read_bytes() == before


def test_provider_error_does_not_advance_atomic_cursor(fixture: dict[str, Any]) -> None:
    def provider(spec: dict, frames: dict, costs: dict) -> list[dict]:
        if spec["tf"] == 30:
            raise ValueError("provider failure")
        return [event(spec["identity"], 1_800_000)]

    with pytest.raises(ValueError, match="provider failure"):
        f.poll(
            fixture["out"], fixture["config_path"], now_ms=6_000_000, provider=provider
        )
    assert not (fixture["out"] / "STATE.json").exists()
    assert (fixture["out"] / "fresh_signals.jsonl").read_bytes() == b""


def test_future_feature_never_emitted_or_cursor_advanced(
    fixture: dict[str, Any]
) -> None:
    def provider(spec: dict, frames: dict, costs: dict) -> list[dict]:
        signal = event(spec["identity"], 1_800_000, spec["tf"])
        signal["signal_ts_ms"] = 9_000_000
        return [signal]

    with pytest.raises(f.FreshForwardError, match="FUTURE_OBSERVATION"):
        f.poll(
            fixture["out"], fixture["config_path"], now_ms=6_000_000, provider=provider
        )
    assert not (fixture["out"] / "STATE.json").exists()


def test_provider_identity_mismatch_fails_closed(fixture: dict[str, Any]) -> None:
    with pytest.raises(f.FreshForwardError, match="PROVIDER_IDENTITY"):
        f.poll(
            fixture["out"],
            fixture["config_path"],
            now_ms=6_000_000,
            provider=lambda *args: [event("BAD", 1_800_000)],
        )


def test_state_tamper_detected(fixture: dict[str, Any]) -> None:
    f.poll(
        fixture["out"],
        fixture["config_path"],
        now_ms=6_000_000,
        provider=lambda *args: [],
    )
    path = fixture["out"] / "STATE.json"
    value = json.loads(path.read_text())
    value["fresh_closed_trades"] = 1
    path.write_text(json.dumps(value))
    with pytest.raises(f.FreshForwardError, match="STATE_HASH"):
        f.poll(
            fixture["out"],
            fixture["config_path"],
            now_ms=6_100_000,
            provider=lambda *args: [],
        )


def test_projection_prefix_tamper_is_not_silently_overwritten(
    fixture: dict[str, Any]
) -> None:
    path = fixture["out"] / "fresh_signals.jsonl"
    path.write_text("CORRUPT\n")
    with pytest.raises(f.FreshForwardError, match="IMMUTABLE_SIGNAL_PREFIX"):
        f.poll(
            fixture["out"],
            fixture["config_path"],
            now_ms=6_000_000,
            provider=lambda *args: [],
        )


def test_initialization_must_precede_shared_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.json"
    config.write_text("{}")
    monkeypatch.setattr(
        f,
        "read_config",
        lambda path: (
            {"fresh_start_ms": 1_800_000},
            {"candidates": [], "primary_identities": []},
            {},
        ),
    )
    with pytest.raises(f.FreshForwardError, match="INITIALIZE_BEFORE"):
        f.initialize(tmp_path / "out", config, now_ms=1_800_001)


def test_context_overlap_requires_exact_price_source_parity() -> None:
    history = frame(15, 3)
    observed = history.iloc[1:].copy()
    result = f.combine_context(history, observed, 15)
    assert len(result) == 3
    assert list(result.fresh_observed) == [False, True, True]
    observed.loc[1, "volume"] = 2
    with pytest.raises(f.FreshForwardError, match="OVERLAP_MISMATCH"):
        f.combine_context(history, observed, 15)


def test_context_gap_preserved_without_interpolation() -> None:
    history = frame(15, 2)
    observed = frame(15, 5).iloc[3:].copy()
    result = f.combine_context(history, observed, 15)
    assert list(result.open_ts_ms) == [0, 900_000, 2_700_000, 3_600_000]
    assert list(result.segment_id) == [0, 0, 1, 1]


def test_config_file_hash_pin(tmp_path: Path) -> None:
    path = tmp_path / "pinned.json"
    path.write_text("hello")
    pin = {"path": str(path), "sha256": f.sha_file(path)}
    assert f._pinned(pin) == path
    path.write_text("changed")
    with pytest.raises(f.FreshForwardError, match="PINNED_FILE_CHANGED"):
        f._pinned(pin)


def test_provider_runtime_does_not_backdate_signal_publication(
    fixture: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [6_000.0]
    monkeypatch.setattr(f.time, "time", lambda: clock[0])

    def provider(spec: dict, frames: dict, costs: dict) -> list[dict]:
        clock[0] = 7_000.0
        return [event(spec["identity"], 1_800_000, spec["tf"])]

    f.poll(fixture["out"], fixture["config_path"], provider=provider)
    records = [
        json.loads(line)
        for line in (fixture["out"] / "fresh_signals.jsonl").read_text().splitlines()
    ]
    assert all(row["observed_at_ms"] == 7_000_000 for row in records)
    assert all(row["signal"]["signal_ts_ms"] == 7_000_000 for row in records)
    state = json.loads((fixture["out"] / "STATE.json").read_text())
    assert all(row["input_snapshot_cutoff_ms"] == 6_000_000 for row in state["signals"])


def test_recovery_keeps_old_opportunities_observation_only(
    fixture: dict[str, Any]
) -> None:
    def provider(spec: dict, frames: dict, costs: dict) -> list[dict]:
        if spec["tf"] == 30:
            return []
        return [event(spec["identity"], 1_800_000), event(spec["identity"], 4_500_000)]

    f.poll(fixture["out"], fixture["config_path"], now_ms=6_000_000, provider=provider)
    records = [
        json.loads(line)
        for line in (fixture["out"] / "fresh_signals.jsonl").read_text().splitlines()
    ]
    assert (
        records[0]["execution_eligibility"]
        == "MISSED_SUPERSEDED_DECISION_OBSERVATION_ONLY"
    )
    assert (
        records[1]["execution_eligibility"] == "CURRENT_DECISION_BAR_REQUIRES_NEW_QUOTE"
    )
    assert records[1]["decision_bar_close_ms"] == 5_400_000
    assert records[0]["latest_common_decision_close_ms"] == 5_400_000
