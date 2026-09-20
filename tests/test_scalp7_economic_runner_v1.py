"""Independent synthetic runner tests: no real candles, scope claims or economics.

Every artifact and registry is confined to a pytest temporary directory.
Prices are hand-computed execution fixtures, not source-author trades.
"""

from __future__ import annotations
import fcntl
import gzip
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import pandas as pd
import pytest
from backend.research.rebuild import scalp7_economic_runner_v1 as runner

TF = 900_000
ALIASES = ("SQ0", "SQ2", "R15", "R30")
ALIAS = "SQ0"
IDENTITY = runner.EXPECTED[ALIAS][0]
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


def selection_fixture() -> dict[str, Any]:
    return {
        "scope_key": runner.SCOPE,
        "max_hypotheses": 2,
        "max_candidates": 4,
        "max_full_executions": 4,
        "base_master_sha": "0" * 40,
        "shared_dependency_paths": ["shared.json"],
        "candidates": {
            alias: {
                "identity": runner.EXPECTED[alias][0],
                "lane": "synthetic_"
                + ("squeeze" if alias.startswith("SQ") else "rider"),
                "parent": "synthetic_parent",
                "axis": "SYNTHETIC_AXIS_" + alias,
                "module": runner.EXPECTED[alias][1],
                "tf": 15,
                "eligibility_path": "eligibility/" + alias + ".json",
                "verified_case_and_review_paths": ["review/" + alias + ".json"],
            }
            for alias in ALIASES
        },
    }


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
    selection = selection_fixture()
    candles = frames(side)
    module = SimpleNamespace(
        prepare_frames=lambda primary, context, **_k: primary,
        generate_signals=lambda *_a, identity, **_k: [
            dict(signal(side), identity=identity),
            dict(signal(side, 4 * TF), identity=identity),
        ],
        exit_update=partial_exit,
        SPEC={"synthetic_fixture": True},
        SPEC_SHA256="1" * 64,
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
    monkeypatch.setattr(runner, "prepare", lambda *_a: (candles, candles))
    dump(runner.SELECTION, selection)
    original = {
        "data_hashes": {"fixture": "3" * 64},
        "cost_sha256": "4" * 64,
        "windows": windows,
    }
    monkeypatch.setattr(runner.base, "verify_freeze", lambda: original)
    for path in (
        "shared.json",
        "backend/research/rebuild/scalp7_economic_runner_v1.py",
        "backend/research/rebuild/scalp7_source_binding_repair_v2.py",
        "backend/research/rebuild/scalp7_fidelity_runner_v1.py",
        "backend/research/rebuild/scalp7_execution_v2.py",
    ):
        p = tmp_path / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("synthetic placeholder: " + path)
    for spec in selection["candidates"].values():
        source = tmp_path / "backend/research/rebuild" / (spec["module"] + ".py")
        source.write_text("synthetic placeholder: " + spec["module"])
        dump(
            tmp_path / spec["eligibility_path"],
            {
                "state": "READY_FOR_ECONOMIC_DIAGNOSTIC",
                "module_sha256": runner.base.sha(source),
            },
        )
        dump(
            tmp_path / spec["verified_case_and_review_paths"][0],
            {"synthetic_review": True},
        )
    freezes = runner.freeze_all()
    dump(tmp_path / "cost.json", {"costs_bps": {SYMBOL: 14.0}})
    return SimpleNamespace(
        out=out,
        runtime=runtime,
        windows=windows,
        module=module,
        candles=candles,
        frozen=freezes[ALIAS],
        freezes=freezes,
        selection=selection,
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "extra_alias",
        "missing_alias",
        "candidate_budget",
        "execution_budget",
        "hypothesis_budget",
        "scope",
        "duplicate_identity",
        "timeframe",
    ],
)
def test_selection_enforces_authorized_two_four_four(mutation: str) -> None:
    selection = selection_fixture()
    runner.validate_selection(selection)
    if mutation == "extra_alias":
        selection["candidates"]["EXTRA"] = selection["candidates"]["SQ0"].copy()
    elif mutation == "missing_alias":
        del selection["candidates"]["SQ2"]
    elif mutation == "candidate_budget":
        selection["max_candidates"] = 5
    elif mutation == "execution_budget":
        selection["max_full_executions"] = 5
    elif mutation == "hypothesis_budget":
        selection["max_hypotheses"] = 3
    elif mutation == "scope":
        selection["scope_key"] = "UNAUTHORIZED"
    elif mutation == "duplicate_identity":
        selection["candidates"]["SQ2"]["identity"] = selection["candidates"]["SQ0"][
            "identity"
        ]
    else:
        selection["candidates"]["R30"]["tf"] = 30
    with pytest.raises(ValueError, match="ECONOMIC_"):
        runner.validate_selection(selection)


@pytest.mark.parametrize("mutation", ["missing", "time", "source_hash"])
def test_sibling_freeze_required_before_any_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    h = harness(tmp_path, monkeypatch)
    sibling = h.out / "freezes" / "R30.json"
    if mutation == "missing":
        sibling.unlink()
    else:
        frozen = runner.read(sibling)
        if mutation == "time":
            frozen["frozen_at_utc"] = "2026-01-02T00:00:00Z"
        else:
            source = (
                tmp_path
                / "backend/research/rebuild"
                / (runner.EXPECTED["R30"][1] + ".py")
            )
            source.write_text("changed\n")
        dump(sibling, frozen)
    with pytest.raises((ValueError, FileNotFoundError)):
        runner.run(ALIAS)
    assert not (h.runtime / "candidate_registry.sqlite3").exists()


def test_root_lock_contention_cannot_create_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness(tmp_path, monkeypatch)
    with (h.runtime / "root_execution.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            runner.run(ALIAS)
    assert not (h.runtime / "candidate_registry.sqlite3").exists()


def test_exactly_four_synthetic_runs_and_idempotent_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness(tmp_path, monkeypatch)
    for alias in ALIASES:
        runner.run(alias)
    assert ledger_state(h) == (["COMPLETED"] * 4, 4)
    monkeypatch.setattr(
        runner, "prepare", lambda *_a: pytest.fail("saved recovery cannot read candles")
    )
    monkeypatch.setattr(
        runner.binding,
        "replay",
        lambda *_a, **_k: pytest.fail("saved recovery cannot replay"),
    )
    for alias in ALIASES:
        assert runner.run(alias)["state"] == "PASS_SAVED_ECONOMIC_NO_ECONOMIC_REPLAY"
    with pytest.raises(KeyError):
        runner.run("UNAPPROVED")
    assert ledger_state(h) == (["COMPLETED"] * 4, 4)


def freeze_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    h = harness(tmp_path, monkeypatch)
    for p in (h.out / "freezes").glob("*.json"):
        p.unlink()
    original = {
        "data_hashes": {"fixture": "3" * 64},
        "cost_sha256": "4" * 64,
        "windows": h.windows,
    }
    monkeypatch.setattr(runner.base, "verify_freeze", lambda: original)
    for path in (
        "shared.json",
        "backend/research/rebuild/scalp7_economic_runner_v1.py",
        "backend/research/rebuild/scalp7_source_binding_repair_v2.py",
        "backend/research/rebuild/scalp7_fidelity_runner_v1.py",
        "backend/research/rebuild/scalp7_execution_v2.py",
    ):
        p = tmp_path / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("synthetic placeholder: " + path)
    for alias, spec in h.selection["candidates"].items():
        source = tmp_path / "backend/research/rebuild" / (spec["module"] + ".py")
        source.write_text("synthetic placeholder: " + spec["module"])
        dump(
            tmp_path / spec["eligibility_path"],
            {
                "state": "READY_FOR_ECONOMIC_DIAGNOSTIC",
                "module_sha256": runner.base.sha(source),
            },
        )
        dump(
            tmp_path / spec["verified_case_and_review_paths"][0],
            {"synthetic_review": True},
        )
    return h


def test_all_four_freeze_before_economics_and_hash_every_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = freeze_harness(tmp_path, monkeypatch)
    frozen = runner.freeze_all()
    assert set(frozen) == set(ALIASES)
    assert len({f["frozen_at_utc"] for f in frozen.values()}) == 1
    assert not (h.runtime / "candidate_registry.sqlite3").exists()
    for f in frozen.values():
        for spec in h.selection["candidates"].values():
            assert spec["eligibility_path"] in f["hashes"]
            assert spec["verified_case_and_review_paths"][0] in f["hashes"]
            assert "backend/research/rebuild/" + spec["module"] + ".py" in f["hashes"]
    snapshots = {p.name: p.read_bytes() for p in (h.out / "freezes").glob("*.json")}
    assert runner.freeze_all() == frozen
    assert {
        p.name: p.read_bytes() for p in (h.out / "freezes").glob("*.json")
    } == snapshots
    changed = (
        tmp_path / "backend/research/rebuild" / (runner.EXPECTED["R30"][1] + ".py")
    )
    changed.write_text("changed after all four frozen")
    with pytest.raises(ValueError, match="FROZEN_HASH_DRIFT"):
        runner.verify_freeze("SQ0")


@pytest.mark.parametrize("mutation", ["not_ready", "module_sha"])
def test_last_source_gate_failure_freezes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    h = freeze_harness(tmp_path, monkeypatch)
    p = tmp_path / h.selection["candidates"]["R30"]["eligibility_path"]
    gate = runner.read(p)
    gate["state" if mutation == "not_ready" else "module_sha256"] = "NOT_READY"
    dump(p, gate)
    with pytest.raises(ValueError, match="ALL_SOURCE_CASE_GATES"):
        runner.freeze_all()
    assert not list((h.out / "freezes").glob("*.json"))
    assert not (h.runtime / "candidate_registry.sqlite3").exists()


def test_partial_freeze_cannot_be_silently_refrozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = freeze_harness(tmp_path, monkeypatch)
    runner._freeze_one("SQ0", "2026-01-01T00:00:00Z")
    with pytest.raises(FileNotFoundError):
        runner.freeze_all()
    assert len(list((h.out / "freezes").glob("*.json"))) == 1
    assert not (h.runtime / "candidate_registry.sqlite3").exists()


def test_freeze_uses_same_exclusive_root_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = freeze_harness(tmp_path, monkeypatch)
    with (h.runtime / "root_execution.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            runner.freeze_all()
    assert not list((h.out / "freezes").glob("*.json"))


def test_prepare_requests_both_existing_timeframes_without_filling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.research.rebuild import scalp7_fidelity_runner_v1 as prior

    calls = []
    original_windows = [{"synthetic_window": True}]
    primary, context = {"15m": object()}, {"30m": object()}

    def prepare(tf: int, windows: Any) -> Any:
        assert windows is original_windows
        calls.append(tf)
        return primary if tf == 15 else context

    monkeypatch.setattr(prior, "prepare", prepare)
    assert runner.prepare(15, original_windows) == (primary, context)
    assert calls == [15, 30]
    with pytest.raises(ValueError, match="15M_EXECUTION"):
        runner.prepare(30, original_windows)
    assert calls == [15, 30]


def test_candidate_receives_actual_costs_and_both_bound_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness(tmp_path, monkeypatch)
    context = {"synthetic_context": object()}
    monkeypatch.setattr(runner, "prepare", lambda *_a: (h.candles, context))
    calls = []

    def prepare(primary: Any, supplied_context: Any, *, costs: Any) -> Any:
        assert primary is h.candles and supplied_context is context
        assert costs == {SYMBOL: 14.0}
        calls.append("prepared")
        return primary

    h.module.prepare_frames = prepare
    runner.run(ALIAS)
    assert calls == ["prepared"]


@pytest.mark.parametrize(
    "field",
    [
        "alias",
        "scope",
        "owner",
        "candidate",
        "base_master_sha",
        "rule_spec",
        "rule_sha256",
        "data_sha256",
        "cost_sha256",
        "windows",
        "window_sha256",
        "execution_sha256",
        "fresh_T",
        "order",
        "live",
        "promotion",
        "missing_hash",
    ],
)
def test_semantic_or_dependency_tamper_blocks_before_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    h = harness(tmp_path, monkeypatch)
    path = h.out / "freezes" / "R30.json"
    frozen = runner.read(path)
    if field == "candidate":
        frozen[field]["identity"] = "unapproved"
    elif field == "rule_spec":
        frozen[field]["synthetic_fixture"] = False
    elif field == "windows":
        frozen[field][0]["end_ms"] += TF
    elif field == "missing_hash":
        frozen["hashes"].pop(next(iter(frozen["hashes"])))
    elif field in ("fresh_T", "promotion"):
        frozen[field] = 1
    else:
        frozen[field] = "TAMPERED"
    dump(path, frozen)
    with pytest.raises(ValueError, match="FROZEN_SEMANTIC_DRIFT|DEPENDENCY_MEMBERSHIP"):
        runner.run("SQ0")
    assert not (h.runtime / "candidate_registry.sqlite3").exists()


@pytest.mark.parametrize(
    "field",
    ["alias", "candidate", "identity_key", "fresh_T", "order", "live", "promotion"],
)
def test_saved_receipt_identity_and_authority_cannot_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    h = harness(tmp_path, monkeypatch)
    runner.run(ALIAS)
    path = h.out / "results" / (ALIAS + ".json")
    info = runner.read(path)
    if field == "candidate":
        info[field]["identity"] = "unapproved"
    elif field in ("fresh_T", "promotion"):
        info[field] = 1
    else:
        info[field] = "unapproved"
    dump(path, info)
    with pytest.raises(ValueError, match="SAVED_IDENTITY_OR_AUTHORITY"):
        runner.verify_saved(ALIAS)


@pytest.mark.parametrize(
    "field", ["signal_identity", "signal_timeframe", "row_identity", "causality"]
)
def test_saved_rehashed_signal_or_trade_tamper_fails_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    h = harness(tmp_path, monkeypatch)
    runner.run(ALIAS)
    path = h.out / "results" / (ALIAS + ".json")
    info = runner.read(path)
    lp = tmp_path / info["ledger_path"]
    data = runner.unpack(lp)
    row = data["trades"][0]
    if field == "signal_identity":
        row["signal"]["identity"] = "unapproved"
    elif field == "signal_timeframe":
        row["signal"]["timeframe_min"] = 30
    elif field == "row_identity":
        row["identity"] = "unapproved"
    else:
        row["entry_ts_ms"] = row["signal_ts_ms"] - 1
    lp.write_bytes(gzip.compress(json.dumps(data).encode(), mtime=0))
    info["ledger_sha256"] = runner.base.sha(lp)
    dump(path, info)
    with pytest.raises(
        ValueError, match="SAVED_SIGNAL_IDENTITY|SAVED_ROW_IDENTITY_OR_CAUSALITY"
    ):
        runner.verify_saved(ALIAS)


def test_changed_candidate_source_rejected_before_module_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness(tmp_path, monkeypatch)
    path = tmp_path / "backend/research/rebuild" / (runner.EXPECTED["R30"][1] + ".py")
    path.write_text("changed after freeze")
    monkeypatch.setattr(
        runner.base,
        "module",
        lambda *_a: pytest.fail("drifted code must not be imported"),
    )
    with pytest.raises(ValueError, match="FROZEN_HASH_DRIFT"):
        runner.verify_freeze("R30")
