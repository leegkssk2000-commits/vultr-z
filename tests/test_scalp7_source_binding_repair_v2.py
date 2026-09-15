from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_source_binding_repair_v2 as adapter
from backend.research.rebuild import scalp7_campaign_binding_repair_v2 as recovery


def frames() -> dict[str, pd.DataFrame]:
    return {
        "BTC-USDT": pd.DataFrame(
            [
                {
                    "open_ts_ms": 0,
                    "close_ts_ms": 900_000,
                    "available_ts_ms": 900_000,
                    "segment_id": 1,
                    "open": 100.0,
                    "high": 102.0,
                    "low": 98.0,
                    "close": 101.0,
                },
                {
                    "open_ts_ms": 900_000,
                    "close_ts_ms": 1_800_000,
                    "available_ts_ms": 1_800_000,
                    "segment_id": 1,
                    "open": 100.0,
                    "high": 125.0,
                    "low": 99.0,
                    "close": 110.0,
                },
                {
                    "open_ts_ms": 1_800_000,
                    "close_ts_ms": 2_700_000,
                    "available_ts_ms": 2_700_000,
                    "segment_id": 1,
                    "open": 110.0,
                    "high": 112.0,
                    "low": 105.0,
                    "close": 108.0,
                },
            ]
        )
    }


def signal() -> dict[str, Any]:
    return {
        "identity": "synthetic",
        "lane": "synthetic",
        "symbol": "BTC-USDT",
        "side": 1,
        "timeframe_min": 15,
        "signal_open_ts_ms": 0,
        "signal_ts_ms": 900_000,
        "segment_id": "1",
        "stop_price": 90.0,
        "max_hold_bars": 10,
        "take_profit_r": None,
        "partial_take_profit_r": 2.0,
        "partial_fraction": 0.25,
        "meta": {"keep": True},
    }


def test_exact_lexical_segment_type_equivalence_without_source_mutation() -> None:
    x = frames()
    raw = signal()
    before = copy.deepcopy(raw)
    frame_before = x["BTC-USDT"].copy(deep=True)
    bound = adapter.bind_segments([raw], x)
    assert bound[0]["segment_id"] == 1 and isinstance(bound[0]["segment_id"], int)
    assert raw == before
    pd.testing.assert_frame_equal(x["BTC-USDT"], frame_before)
    bound[0]["meta"]["keep"] = False
    assert raw["meta"]["keep"] is True


@pytest.mark.parametrize("bad", ["2", "01", "1.0", 2])
def test_different_segment_identity_never_repaired(bad: Any) -> None:
    s = signal()
    s["segment_id"] = bad
    with pytest.raises(ValueError, match="SEGMENT_VALUE_MISMATCH"):
        adapter.bind_segments([s], frames())


def test_missing_signal_bar_is_not_remapped() -> None:
    s = signal()
    s["signal_open_ts_ms"] = -900_000
    assert adapter.bind_segments([s], frames())[0]["signal_open_ts_ms"] == -900_000


def partial_exit(
    position: dict[str, Any], bar: dict[str, Any], history: pd.DataFrame
) -> dict[str, Any]:
    return {
        "partial_fraction": 0.25,
        "partial_price": 120.0,
        "exit_next_open": True,
        "reason": "SYNTHETIC_RESTING_LIMIT",
    }


def test_cashflow_logger_does_not_change_fill_gross_fee_or_original_signal() -> None:
    x = frames()
    raw = signal()
    baseline = copy.deepcopy(raw)
    baseline["segment_id"] = 1
    frozen = adapter.engine.replay(
        [baseline],
        x,
        {"BTC-USDT": 14.0},
        identity="synthetic",
        exit_update=partial_exit,
    )
    logged = adapter.replay(
        [raw], x, {"BTC-USDT": 14.0}, identity="synthetic", exit_update=partial_exit
    )
    assert len(frozen["trades"]) == len(logged["trades"]) == 1
    old, new = frozen["trades"][0], logged["trades"][0]
    for key in old:
        assert new[key] == old[key]
    assert new["gross_bps"] == pytest.approx(1250)
    assert new["cost_bps"] == 14
    assert new["net_bps"] == pytest.approx(1236)
    assert new["terminal_fraction_original_notional"] == 0.75
    assert new["partial_cashflows"] == [
        {
            "fraction_original_notional": 0.25,
            "fill_price": 120.0,
            "fill_interval_start_ms": 900_000,
            "fill_interval_end_ms": 1_800_000,
            "observed_at_ms": 1_800_000,
            "rule": "FROZEN_RESTING_LIMIT_STOP_FIRST",
        }
    ]
    assert raw["segment_id"] == "1"


def recovery_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hidden_raw_trade: bool = False
) -> dict[str, Any]:
    base = recovery.base
    catalog = base.candidates()
    report = tmp_path / "report"
    report.mkdir()
    original = {
        "candidates": catalog,
        "code_hashes": {},
        "data_hashes": {},
        "cost_sha256": "a" * 64,
        "windows": [],
    }
    (report / "CAMPAIGN_PREREGISTERED_V2.json").write_text(json.dumps(original))
    monkeypatch.setattr(base, "ROOT", tmp_path)
    monkeypatch.setattr(base, "REPORT", report)
    monkeypatch.setattr(recovery, "REPORT", report)
    monkeypatch.setattr(
        recovery, "CONTRACT", report / "SOURCE_BINDING_REPAIR_PREREG_V2.json"
    )
    monkeypatch.setattr(base, "verify_freeze", lambda: original)
    for name in (
        "scalp7_source_binding_repair_v2.py",
        "scalp7_campaign_binding_repair_v2.py",
    ):
        path = tmp_path / "backend/research/rebuild" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic mock source\n")
    zeros = [
        s["identity"]
        for s in catalog
        if s["kind"] == "parent" and s["identity"] not in recovery.PRESERVED
    ][:2]
    for identity in [*recovery.PRESERVED, *zeros]:
        preserved = identity in recovery.PRESERVED
        raw_trades = (
            [{"synthetic": "completed"}] if preserved or hidden_raw_trade else []
        )
        payload = {"trades": raw_trades, "unresolved": []}
        ledger = report / "results" / (identity + ".trades.json.gz")
        ledger.parent.mkdir(exist_ok=True)
        ledger.write_bytes(gzip.compress(json.dumps(payload).encode(), mtime=0))
        receipt = {
            "window_receipts": [
                {
                    "cost1x": {"T": 1 if preserved else 0},
                    "rejections": {} if preserved else {"SIGNAL_SEGMENT_MISMATCH": 10},
                }
            ],
            "unresolved_count": 0,
            "ledger_path": str(ledger.relative_to(tmp_path)),
            "ledger_sha256": base.sha(ledger),
        }
        (report / "results" / (identity + ".json")).write_text(json.dumps(receipt))
    return original


def test_recovery_separate17_budget_preserves4_and_invalidates_zero2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recovery_fixture(tmp_path, monkeypatch)
    contract = recovery.freeze()
    assert len(contract["candidates"]) == contract["max_executions"] == 17
    assert not set(recovery.PRESERVED) & {s["identity"] for s in contract["candidates"]}
    assert (
        sum(
            p["state"] == "VALID_PRESERVED_NO_REPLAY"
            for p in contract["preserved_prior"].values()
        )
        == 4
    )
    assert (
        sum(
            p["state"] == "INVALID_SOURCE_BINDING_ZERO_FILLS_NOT_STRATEGY_PERFORMANCE"
            for p in contract["preserved_prior"].values()
        )
        == 2
    )
    assert contract["economic_rules_changed"] is False
    assert contract["execution_scope"] != contract["scope_key"]
    assert recovery.verify_contract() == contract


def test_recovery_refuses_raw_trade_hidden_by_window_end_exclusion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recovery_fixture(tmp_path, monkeypatch, hidden_raw_trade=True)
    with pytest.raises(ValueError, match="REPEAT_ECONOMIC_FILLS"):
        recovery.freeze()
