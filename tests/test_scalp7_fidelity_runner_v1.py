"""Independent synthetic runner review; never loads real market data or scope.

Hand-computed prices are logic fixtures, not source-author trades/economic data.
All registry writes and artifacts are confined to pytest temporary directories.
"""

from __future__ import annotations

import copy
import gzip
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_fidelity_runner_v1 as runner

TF = 900_000
ALIAS = "synthetic"
IDENTITY = "synthetic_fidelity_review"
SYMBOL = "BTC-USDT"


def signal(side: int = 1, opened: int = 0) -> dict[str, Any]:
    return {
        "identity": IDENTITY,
        "lane": "synthetic",
        "symbol": SYMBOL,
        "timeframe_min": 15,
        "side": side,
        "signal_open_ts_ms": opened,
        "signal_ts_ms": opened + TF,
        "segment_id": "1",
        "stop_price": 90.0 if side == 1 else 110.0,
        "max_hold_bars": 1,
        "take_profit_r": None,
        "partial_take_profit_r": 1.0,
        "partial_fraction": 0.3,
    }


def frames(side: int = 1) -> dict[str, pd.DataFrame]:
    ohlc = [
        (100, 101, 99, 100),
        (100, 111, 96, 108) if side == 1 else (100, 104, 89, 92),
        (105, 106, 104, 105) if side == 1 else (95, 96, 94, 95),
        (100, 101, 99, 100),
    ] * 2
    return {
        SYMBOL: pd.DataFrame(
            [
                dict(
                    open_ts_ms=i * TF,
                    close_ts_ms=(i + 1) * TF,
                    available_ts_ms=(i + 1) * TF,
                    segment_id=1,
                    **dict(zip(("open", "high", "low", "close"), prices)),
                )
                for i, prices in enumerate(ohlc)
            ]
        )
    }


def partial_exit(position: dict[str, Any], *_: Any) -> dict[str, Any]:
    return {
        "partial_fraction": 0.3,
        "partial_price": 110.0 if position["side"] == 1 else 90.0,
        "exit_next_open": True,
        "reason": "SYNTHETIC_FIXED_LIMIT",
    }


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, side: int = 1
) -> SimpleNamespace:
    out = tmp_path / "out"
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    windows = [
        {"label": "v", "partition": "validation", "start_ms": 0, "end_ms": 4 * TF},
        {"label": "r", "partition": "rolling", "start_ms": 4 * TF, "end_ms": 8 * TF},
    ]
    spec = {
        "identity": IDENTITY,
        "lane": "synthetic",
        "parent": "synthetic_parent",
        "axis": "SYNTHETIC_SINGLE_AXIS",
        "module": "synthetic_module",
        "tf": 15,
        "verified_case_and_review_paths": [],
    }
    frozen = {
        "candidate": spec,
        "hashes": {},
        "rule_sha256": "1" * 64,
        "execution_sha256": "2" * 64,
        "data_sha256": "3" * 64,
        "cost_sha256": "4" * 64,
        "window_sha256": "5" * 64,
        "windows": windows,
    }
    selection = {
        "candidates": {ALIAS: spec},
        "max_candidates": 1,
        "max_full_executions": 1,
    }
    candles = frames(side)
    module = SimpleNamespace(
        generate_signals=lambda *_a, **_k: [signal(side), signal(side, 4 * TF)],
        exit_update=partial_exit,
    )
    for name, value in (
        ("ROOT", tmp_path),
        ("OUT", out),
        ("RUNTIME", runtime),
        ("SELECTION", out / "BATCH_SELECTION.json"),
    ):
        monkeypatch.setattr(runner, name, value)
    monkeypatch.setattr(runner.base, "COST_PATH", tmp_path / "cost.json")
    monkeypatch.setattr(runner.base, "verify_freeze", lambda: {})
    monkeypatch.setattr(runner.base, "module", lambda _name: module)
    monkeypatch.setattr(runner, "prepare", lambda *_a: candles)
    dump(runner.SELECTION, selection)
    dump(out / "freezes" / (ALIAS + ".json"), frozen)
    dump(tmp_path / "cost.json", {"costs_bps": {SYMBOL: 14.0}})
    return SimpleNamespace(
        out=out,
        runtime=runtime,
        windows=windows,
        spec=spec,
        module=module,
        candles=candles,
        frozen=frozen,
    )


def ledger_state(h: SimpleNamespace) -> tuple[list[str], int]:
    with sqlite3.connect(h.runtime / "candidate_registry.sqlite3") as db:
        states = [r[0] for r in db.execute("SELECT state FROM claims")]
        starts = db.execute(
            "SELECT count(*) FROM events WHERE event='STARTED'"
        ).fetchone()[0]
    return states, starts


@pytest.mark.parametrize("side", [1, -1])
def test_real_engine_cashflow_and_saved_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, side: int
) -> None:
    h = harness(tmp_path, monkeypatch, side)
    result = runner.run(ALIAS)
    assert result["raw_T"] == 2 and result["unresolved"] == 0
    info = runner.read(h.out / "results" / (ALIAS + ".json"))
    payload = runner.unpack(tmp_path / info["ledger_path"])
    for row in payload["trades"]:
        # 30% gains ten price units; 70% gains five. Original entry is 100.
        assert row["gross_bps"] == pytest.approx(650)
        assert row["net_bps"] == pytest.approx(636)
        assert row["cost_bps"] == 14
        assert row["terminal_fraction_original_notional"] == pytest.approx(0.7)
        assert len(row["partial_cashflows"]) == 1
        assert row["partial_cashflows"][0]["observed_at_ms"] <= row["exit_ts_ms"]
    for partition in ("validation", "rolling"):
        m = info["summary"][partition]
        assert m["cost1x"]["T"] == m["cost2x"]["T"] == 1
        assert m["cost1x"]["Net_bps"] == pytest.approx(636)
        assert m["cost2x"]["Net_bps"] == pytest.approx(622)
        assert m["cost1x"]["Cost_bps_T"] == 14
        assert m["cost2x"]["Cost_bps_T"] == 28
    assert ledger_state(h) == (["COMPLETED"], 1)
    monkeypatch.setattr(
        runner.binding,
        "replay",
        lambda *_a, **_k: pytest.fail("saved verification must not replay"),
    )
    assert runner.run(ALIAS) == result
    assert ledger_state(h) == (["COMPLETED"], 1)


def test_stop_wins_over_resting_partial() -> None:
    x = frames()
    x[SYMBOL].loc[1, ["low", "high"]] = [89, 115]
    result = runner.binding.replay(
        [signal()], x, {SYMBOL: 14.0}, identity=IDENTITY, exit_update=partial_exit
    )
    row = result["trades"][0]
    assert row["reason"] == "STOP_FIRST"
    assert row["gross_bps"] == pytest.approx(-1000)
    assert row["partial_cashflows"] == []
    assert row["terminal_fraction_original_notional"] == 1


def test_source_gap_preserves_unresolved_ownership() -> None:
    x = frames()
    x[SYMBOL] = x[SYMBOL].drop(index=2).reset_index(drop=True)
    raw = signal()
    raw["max_hold_bars"] = 9
    result = runner.binding.replay(
        [raw, signal(opened=4 * TF)],
        x,
        {SYMBOL: 14.0},
        identity=IDENTITY,
        exit_update=lambda *_a: {},
    )
    assert not result["trades"]
    assert len(result["unresolved"]) == 1
    assert result["rejections"]["POSITION_ALREADY_OWNED"] == 1


@pytest.mark.parametrize("kind", ["availability", "segment"])
def test_source_binding_cannot_repair_causal_mismatch(kind: str) -> None:
    x = frames()
    if kind == "availability":
        x[SYMBOL].loc[0, "available_ts_ms"] = TF + 1
        result = runner.binding.replay(
            [signal()],
            x,
            {SYMBOL: 14.0},
            identity=IDENTITY,
            exit_update=partial_exit,
        )
        assert not result["trades"]
        assert result["rejections"]["SIGNAL_BEFORE_FEATURE_AVAILABILITY"] == 1
    else:
        raw = signal()
        raw["segment_id"] = "01"
        with pytest.raises(ValueError, match="SEGMENT_VALUE_MISMATCH"):
            runner.binding.replay(
                [raw],
                x,
                {SYMBOL: 14.0},
                identity=IDENTITY,
                exit_update=partial_exit,
            )


def test_window_membership_keeps_exact_end_outcome_out() -> None:
    windows = [
        {"label": "v", "partition": "validation", "start_ms": 100, "end_ms": 200}
    ]
    rows = [
        {"window_label": "v", "signal_ts_ms": 100, "outcome_available_ts_ms": 199},
        {"window_label": "v", "signal_ts_ms": 100, "outcome_available_ts_ms": 200},
        {"window_label": "v", "signal_ts_ms": 99, "outcome_available_ts_ms": 150},
    ]
    assert runner.window_rows(rows, windows, "validation") == [rows[0]]


def test_preparation_failure_is_terminal_without_full_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness(tmp_path, monkeypatch)

    def broken(*_a: Any) -> Any:
        raise ValueError("SYNTHETIC_PREPARATION_FAILURE")

    monkeypatch.setattr(runner, "prepare", broken)
    with pytest.raises(ValueError):
        runner.run(ALIAS)
    states, starts = ledger_state(h)
    assert states in (["HOLD"], ["REJECTED"])
    assert starts == 0
    with pytest.raises(ValueError):
        runner.run(ALIAS)
    assert ledger_state(h) == (states, 0)


def test_generator_identity_mismatch_cannot_silently_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness(tmp_path, monkeypatch)
    h.module.generate_signals = lambda *_a, **_k: [dict(signal(), identity="wrong")]
    with pytest.raises(ValueError, match="IDENTITY"):
        runner.run(ALIAS)
    assert ledger_state(h)[1] == 0


def test_replay_failure_records_once_and_prevents_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness(tmp_path, monkeypatch)

    def broken(*_a: Any, **_k: Any) -> Any:
        raise ValueError("SYNTHETIC_REPLAY_FAILURE")

    monkeypatch.setattr(runner.binding, "replay", broken)
    with pytest.raises(ValueError, match="SYNTHETIC_REPLAY_FAILURE"):
        runner.run(ALIAS)
    assert ledger_state(h) == (["FAILED"], 1)
    with pytest.raises(ValueError, match="NO_REPEAT"):
        runner.run(ALIAS)
    assert ledger_state(h) == (["FAILED"], 1)


def test_uncommitted_result_never_accepted_as_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness(tmp_path, monkeypatch)
    original = runner.registry.CampaignLedger.finish

    def broken(self: Any, key: str, owner: str, state: str, receipt: Any) -> bool:
        if state == "COMPLETED":
            raise ValueError("SYNTHETIC_COMMIT_FAILURE")
        return original(self, key, owner, state, receipt)

    monkeypatch.setattr(runner.registry.CampaignLedger, "finish", broken)
    with pytest.raises(ValueError):
        runner.run(ALIAS)
    assert ledger_state(h) == (["FAILED"], 1)
    with pytest.raises(ValueError):
        runner.run(ALIAS)
    assert ledger_state(h) == (["FAILED"], 1)


def test_atomic_packed_write_rejects_nan_and_duplicate(
    tmp_path: Path,
) -> None:
    p = tmp_path / "payload.json.gz"
    with pytest.raises(ValueError):
        runner.packed_write(p, {"invalid": float("nan")})
    assert not p.exists()
    runner.packed_write(p, {"first": True})
    old = p.read_bytes()
    with pytest.raises(FileExistsError):
        runner.packed_write(p, {"second": True})
    assert p.read_bytes() == old


@pytest.mark.parametrize(
    "mutation", ["short_reciprocal", "partial_weight", "partial_price"]
)
def test_saved_arithmetic_rejects_rehashed_bad_cashflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    h = harness(tmp_path, monkeypatch, side=-1)
    runner.run(ALIAS)
    p = h.out / "results" / (ALIAS + ".json")
    info = runner.read(p)
    lp = tmp_path / info["ledger_path"]
    data = runner.unpack(lp)
    row = data["trades"][0]
    if mutation == "short_reciprocal":
        row["gross_bps"] = (100 / 90 - 1) * 3000 + (100 / 95 - 1) * 7000
        row["net_bps"] = row["gross_bps"] - 14
    elif mutation == "partial_weight":
        row["terminal_fraction_original_notional"] = 0.6
    else:
        row["partial_cashflows"][0]["fill_price"] = 89.0
    lp.write_bytes(gzip.compress(json.dumps(data).encode(), mtime=0))
    info["ledger_sha256"] = runner.base.sha(lp)
    dump(p, info)
    with pytest.raises(ValueError):
        runner.verify_saved(ALIAS)


def test_cached_parent_reconstruction_checks_exact_signal_without_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness(tmp_path, monkeypatch)
    raw = signal()
    path = tmp_path / "parent.json"
    lp = tmp_path / "parent.json.gz"
    runner.packed_write(
        lp, {"trades": [dict(raw, signal=copy.deepcopy(raw))], "unresolved": []}
    )
    dump(path, {"candidate": {"module": "synthetic_parent"}, "ledger_path": lp.name})
    monkeypatch.setattr(runner.base, "_signals", lambda *_a: [raw])
    monkeypatch.setattr(
        runner.binding,
        "replay",
        lambda *_a, **_k: pytest.fail("parent reconstruction cannot replay"),
    )
    spec = {"cached_parent": path.name}
    got = runner.cached_parent_signals(spec, h.candles, {SYMBOL: 14})
    assert len(got) == 1
    raw["stop_price"] = 91
    with pytest.raises(ValueError, match="RECONSTRUCTION_DRIFT"):
        runner.cached_parent_signals(spec, h.candles, {SYMBOL: 14})


@pytest.mark.parametrize(
    "selection",
    [
        {"candidates": {}, "max_candidates": 7, "max_full_executions": 1},
        {
            "candidates": {"a": {"identity": "a"}},
            "max_candidates": 1,
            "max_full_executions": 7,
        },
        {
            "candidates": {"a": {"identity": "a"}, "b": {"identity": "a"}},
            "max_candidates": 2,
            "max_full_executions": 2,
        },
    ],
)
def test_selection_cannot_exceed_budget_or_duplicate_identity(
    selection: dict[str, Any]
) -> None:
    with pytest.raises(ValueError, match="BUDGET|DUPLICATE"):
        runner.validate_selection(selection)


def test_parent_unresolved_and_duplicate_events_are_not_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness(tmp_path, monkeypatch)
    raw = signal()
    prior = dict(raw, stop_price=91)
    lp = tmp_path / "parent_unresolved.json.gz"
    runner.packed_write(
        lp, {"trades": [], "unresolved": [{"position": {"signal": prior}}]}
    )
    p = tmp_path / "parent_unresolved.json"
    dump(p, {"candidate": {"module": "synthetic_parent"}, "ledger_path": lp.name})
    spec = {"cached_parent": p.name}
    monkeypatch.setattr(runner.base, "_signals", lambda *_a: [raw])
    with pytest.raises(ValueError, match="RECONSTRUCTION_DRIFT"):
        runner.cached_parent_signals(spec, h.candles, {SYMBOL: 14})
    monkeypatch.setattr(runner.base, "_signals", lambda *_a: [raw, copy.deepcopy(raw)])
    with pytest.raises(ValueError, match="DUPLICATE"):
        runner.cached_parent_signals(spec, h.candles, {SYMBOL: 14})


@pytest.mark.parametrize(
    "field", ["nonfinite_price", "nonfinite_weight", "future_cashflow"]
)
def test_saved_cashflow_causality_and_finiteness_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    h = harness(tmp_path, monkeypatch)
    runner.run(ALIAS)
    p = h.out / "results" / (ALIAS + ".json")
    info = runner.read(p)
    lp = tmp_path / info["ledger_path"]
    data = runner.unpack(lp)
    row = data["trades"][0]
    if field == "nonfinite_price":
        row["partial_cashflows"][0]["fill_price"] = float("nan")
    elif field == "nonfinite_weight":
        row["terminal_fraction_original_notional"] = float("nan")
    else:
        row["partial_cashflows"][0]["observed_at_ms"] = (
            row["outcome_available_ts_ms"] + TF
        )
    lp.write_bytes(gzip.compress(json.dumps(data).encode(), mtime=0))
    info["ledger_sha256"] = runner.base.sha(lp)
    dump(p, info)
    with pytest.raises(ValueError):
        runner.verify_saved(ALIAS)


def test_final_verification_failure_never_commits_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness(tmp_path, monkeypatch)

    def broken(*_a: Any) -> Any:
        raise ValueError("SYNTHETIC_FINAL_VERIFY_FAILURE")

    monkeypatch.setattr(runner, "verify_saved", broken)
    with pytest.raises(ValueError, match="SYNTHETIC_FINAL_VERIFY_FAILURE"):
        runner.run(ALIAS)
    assert ledger_state(h) == (["FAILED"], 1)
