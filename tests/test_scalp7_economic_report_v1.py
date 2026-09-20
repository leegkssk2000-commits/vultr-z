"""Saved economics fixtures; no market data, strategy generation or replay."""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from backend.research.rebuild import scalp7_economic_report_v1 as report

TF = 900_000
FIELD = "origin_fire_ts_ms"
WINDOWS = [
    {"label": "v", "partition": "validation", "start_ms": 0, "end_ms": 10 * TF},
    {"label": "r", "partition": "rolling", "start_ms": 10 * TF, "end_ms": 20 * TF},
]


def row(
    stamp: int = TF,
    net: float = 100.0,
    origin: int | None = 0,
    window: str = "v",
    symbol: str = "BTC-USDT",
) -> dict[str, Any]:
    signal = {
        "identity": "fixture",
        "symbol": symbol,
        "side": 1,
        "timeframe_min": 15,
        "signal_ts_ms": stamp,
        "meta": {} if origin is None else {FIELD: origin},
    }
    return {
        **signal,
        "signal": signal,
        "window_label": window,
        "entry_ts_ms": stamp,
        "exit_ts_ms": stamp + TF,
        "outcome_available_ts_ms": stamp + TF,
        "entry_prices": {symbol: 100.0},
        "exit_prices": {symbol: 100 * (1 + (net + 14) / 10000)},
        "gross_bps": net + 14,
        "cost_bps": 14.0,
        "net_bps": net,
        "reason": "STRUCTURAL_CLOSE",
    }


def payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"trades": rows, "unresolved": [], "window_receipts": []}


def test_time_shift_matches_causal_origin_without_exact_event_match() -> None:
    p, c = row(net=100), row(stamp=2 * TF, net=60)
    x = report.compare(
        payload([p]), payload([c]), [p["signal"]], [c["signal"]], WINDOWS, FIELD
    )["validation"]
    assert x["attribution"]["common_count"] == 0
    assert x["attribution"]["parent_winner_profit_retained_ratio"] == 0
    o = x["same_opportunity"]
    assert o["matched_count"] == 1
    assert o["time_shifted_entry_count"] == 1
    assert o["pairs"][0]["entry_shift_min"] == 15
    assert o["parent_winner_profit_retained_ratio"] == 0.6
    assert o["total_net_delta_bps"] == -40
    assert x["signal_opportunity_stream"]["counts"] == {
        "SAME_ORIGIN_SIGNAL_TIME_SHIFT": 1
    }


def test_nearest_time_is_never_a_matching_rule() -> None:
    p, c = row(origin=0), row(stamp=2 * TF, origin=TF)
    x = report.same_opportunity([p], [c], FIELD)
    assert x["matched_count"] == 0
    assert x["parent_only_known_origin_count"] == 1
    assert x["child_only_known_origin_count"] == 1


def test_exact_event_with_different_setup_is_not_same_opportunity() -> None:
    p, c = row(origin=0), row(origin=TF)
    x = report.compare(
        payload([p]), payload([c]), [p["signal"]], [c["signal"]], WINDOWS, FIELD
    )["validation"]
    assert x["attribution"]["common_count"] == 1
    assert x["same_opportunity"]["matched_count"] == 0


def test_boundary_shift_is_found_before_economic_partitioning() -> None:
    p, c = row(stamp=9 * TF), row(stamp=11 * TF, window="r")
    stream = report.signal_stream([p["signal"]], [c["signal"]], WINDOWS, FIELD)
    assert stream["counts"] == {"SAME_ORIGIN_WINDOW_BOUNDARY_SHIFT": 1}
    x = report.compare(
        payload([p]), payload([c]), [p["signal"]], [c["signal"]], WINDOWS, FIELD
    )
    assert x["validation"]["parent"]["cost1x"]["T"] == 0
    assert x["validation"]["parent"]["closed_outside_strict_window_count"] == 1
    assert x["rolling"]["child"]["cost1x"]["T"] == 1
    assert x["rolling"]["same_opportunity"]["matched_count"] == 0
    assert x["rolling"]["unmatched_fill_diagnostics"]["child"]["counts"] == {
        "SAME_ORIGIN_SIGNAL_OUTSIDE_THIS_WINDOW": 1
    }
    assert x["rolling"]["signal_opportunity_stream"]["counts"] == {
        "SAME_ORIGIN_WINDOW_BOUNDARY_SHIFT": 1
    }


def test_same_origin_opposite_partition_pnl_never_pools() -> None:
    p, c = row(stamp=8 * TF, net=100), row(stamp=11 * TF, net=60, window="r")
    x = report.compare(
        payload([p]), payload([c]), [p["signal"]], [c["signal"]], WINDOWS, FIELD
    )
    assert x["validation"]["delta"]["Net_bps"] == -100
    assert x["rolling"]["delta"]["Net_bps"] == 60
    assert x["validation"]["same_opportunity"]["matched_count"] == 0
    assert x["rolling"]["same_opportunity"]["matched_count"] == 0


def test_ambiguous_origin_and_missing_metadata_stay_unknown() -> None:
    p = [row(), row(stamp=3 * TF), row(stamp=5 * TF, origin=None)]
    c = [row(stamp=2 * TF)]
    x = report.same_opportunity(p, c, FIELD)
    assert x["matched_count"] == 0
    assert x["ambiguous_origin_group_count"] == 1
    assert x["missing_origin_count"] == {"parent": 1, "child": 0}
    assert x["total_net_delta_bps"] == -200
    assert x["parent_winner_profit_retained_ratio"] == 0


@pytest.mark.parametrize("origin", [True, -1, TF + 1, 1.5])
def test_noncausal_or_invalid_origins_fail(origin: Any) -> None:
    with pytest.raises(ValueError, match="NONCAUSAL"):
        report.same_opportunity([row(origin=origin)], [], FIELD)


def test_duplicate_exact_fill_keys_fail_before_attribution() -> None:
    p = row()
    with pytest.raises(ValueError, match="DUPLICATE"):
        report.same_opportunity([p, copy.deepcopy(p)], [], FIELD)


def test_winner_damage_saved_losses_reconcile_without_unfilled_profit() -> None:
    p = [row(net=100), row(stamp=4 * TF, origin=3 * TF, net=-40)]
    c = [row(stamp=2 * TF, net=60), row(stamp=7 * TF, origin=6 * TF, net=-5)]
    x = report.same_opportunity(p, c, FIELD)
    assert x["parent_winner_profit_retained_ratio"] == 0.6
    assert x["parent_winner_group_delta_including_unmatched_bps"] == -40
    assert x["parent_loser_observed_loss_saved_bps"] == 40
    assert x["matched_net_delta_bps"] == -40
    assert x["unmatched_parent_observed_contribution_bps"] == 40
    assert x["unmatched_child_observed_net_bps"] == -5
    assert x["total_net_delta_bps"] == -5


def test_unresolved_and_occupancy_are_visible_without_fake_pnl() -> None:
    p = row()
    occupied = row(stamp=4 * TF)
    c = payload([])
    c["unresolved"] = [
        {
            "identity": "fixture",
            "symbol": p["symbol"],
            "entry_ts_ms": p["entry_ts_ms"],
            "window_label": "v",
            "position": {"signal": p["signal"], "cost_bps": 14},
        }
    ]
    x = report.compare(
        payload([p]),
        c,
        [p["signal"]],
        [p["signal"], occupied["signal"]],
        WINDOWS,
        FIELD,
    )["validation"]
    assert x["child"]["cost1x"]["T"] == 0
    assert x["child"]["unresolved_count"] == 1
    assert x["unresolved_unknowns"]["child"][0]["hypothetical_net_bps"] is None
    assert x["occupancy"]["child"]["counts"]["BLOCKED_BY_UNRESOLVED_OCCUPANCY"] == 1
    assert x["unmatched_fill_diagnostics"]["parent"]["counts"] == {
        "SAME_ORIGIN_SIGNAL_INSIDE_WINDOW_NO_UNIQUE_COMPLETED_MATCH": 1
    }


def test_cost_stress_does_not_change_trade_count_or_holding_time() -> None:
    p = [row(net=5), row(stamp=4 * TF, origin=3 * TF, net=-10)]
    x = report.compare(
        payload(p),
        payload(p),
        [r["signal"] for r in p],
        [r["signal"] for r in p],
        WINDOWS,
        FIELD,
    )["validation"]["parent"]
    assert x["cost1x"]["T"] == x["cost2x"]["T"] == 2
    assert x["cost1x"]["Net_bps"] == -5
    assert x["cost2x"]["Net_bps"] == -33
    assert x["cost1x"]["WR_pct"] == 50
    assert x["cost2x"]["WR_pct"] == 0
    assert x["cost1x"]["hold_median_min"] == x["cost2x"]["hold_median_min"] == 15


def test_successors_do_not_cross_symbol_or_window() -> None:
    rows = [
        row(),
        row(stamp=3 * TF),
        row(stamp=4 * TF, symbol="ETH-USDT"),
        row(stamp=11 * TF, window="r"),
    ]
    x = report.successors(rows)
    assert len(x) == 1
    assert x[0]["release_to_next_entry_min"] == 15
    assert x[0]["next_event"]["signal_ts_ms"] == 3 * TF


@pytest.mark.parametrize("path", ["../outside.json", "/tmp/outside.json"])
def test_unsafe_input_paths_are_rejected(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError, match="UNSAFE"):
        report.relative_path(tmp_path, path)


def setup_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aliases: tuple[str, ...]
) -> Path:
    def dump(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def pack(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(json.dumps(value).encode(), mtime=0))

    monkeypatch.setattr(
        report.saved,
        "verified_original",
        lambda _: (
            {"windows": WINDOWS, "cost_sha256": "c" * 64},
            {"BTC-USDT": 14.0},
            {},
        ),
    )
    out = tmp_path / report.REL
    specs = {a: {"identity": a, "tf": 15} for a in ("SQ0", "SQ2", "R15", "R30")}
    dump(out / "BATCH_SELECTION.json", {"scope_key": report.SCOPE, "candidates": specs})
    module = tmp_path / report.MODULE
    module.parent.mkdir(parents=True)
    module.write_text("saved reporter fixture")
    for alias in aliases:
        rows = [row(net=10), row(stamp=11 * TF, origin=10 * TF, window="r", net=10)]
        for r in rows:
            r["identity"] = r["signal"]["identity"] = alias
            if alias.startswith("R"):
                r["signal"]["meta"]["compression_origin_ts_ms"] = r["signal"]["meta"][
                    FIELD
                ]
        data = payload(rows)
        lp, sp, fp = (
            out / "results" / (alias + ".trades.json.gz"),
            out / "results" / (alias + ".signals.json.gz"),
            out / "freezes" / (alias + ".json"),
        )
        pack(lp, data)
        pack(sp, [r["signal"] for r in rows])
        dump(fp, {"windows": WINDOWS, "cost_sha256": "c" * 64, "hashes": {}})
        dump(
            out / "results" / (alias + ".json"),
            {
                "candidate": specs[alias],
                "freeze_path": str(fp.relative_to(tmp_path)),
                "freeze_sha256": report.saved.sha(fp),
                "ledger_path": str(lp.relative_to(tmp_path)),
                "ledger_sha256": report.saved.sha(lp),
                "signal_path": str(sp.relative_to(tmp_path)),
                "signals_sha256": report.saved.sha(sp),
                "unresolved_count": 0,
                "window_receipts": [],
                "summary": report.saved.summaries(data, WINDOWS),
            },
        )
    return out


def test_incremental_build_requires_only_finished_pair_and_is_immutable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = setup_fixture(tmp_path, monkeypatch, ("SQ0", "SQ2"))
    value = report.build_report(tmp_path, "SQUEEZE")
    assert value["loaded_full_identities"] == ["SQ0", "SQ2"]
    assert value["approved_full_run_cap"] == 4
    assert value["state"] == "PARTIAL_SAVED_COMPARISON"
    assert value["G4_complete"] is False
    for path, raw in report.artifacts(value, tmp_path):
        report.saved.immutable_write(path, raw)
    assert report.verify(tmp_path, "SQUEEZE")["comparisons"] == 1
    assert not (out / "ECONOMIC_COMPARISON.json").exists()
    with pytest.raises(FileNotFoundError):
        report.build_report(tmp_path, "ALL")
    (out / "SQUEEZE_REPORT.md").write_text("tamper")
    with pytest.raises(ValueError, match="SAVED_VERIFICATION"):
        report.verify(tmp_path, "SQUEEZE")


def test_full_build_separates_both_comparisons_and_blocks_authorities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_fixture(tmp_path, monkeypatch, ("SQ0", "SQ2", "R15", "R30"))
    value = report.build_report(tmp_path)
    assert set(value["comparisons"]) == {"SQUEEZE", "RIDER"}
    assert value["fresh_T"] == value["A_promotions"] == value["B_promotions"] == 0
    assert value["promotion"] is False
    assert value["live"] == value["order"] == value["fusion"] == "BLOCKED"
    for path, raw in report.artifacts(value, tmp_path):
        report.saved.immutable_write(path, raw)
    assert report.verify(tmp_path)["comparisons"] == 2


def test_window_receipt_tamper_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = setup_fixture(tmp_path, monkeypatch, ("SQ0", "SQ2"))
    path = out / "results" / "SQ0.json"
    receipt = json.loads(path.read_text())
    receipt["window_receipts"] = [{"tampered": True}]
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="WINDOW_RECEIPT_BINDING"):
        report.build_report(tmp_path, "SQUEEZE")


def test_approved_aliases_cannot_expand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = setup_fixture(tmp_path, monkeypatch, ("SQ0", "SQ2"))
    path = out / "BATCH_SELECTION.json"
    selection = json.loads(path.read_text())
    selection["candidates"]["FIFTH"] = {"identity": "extra"}
    path.write_text(json.dumps(selection))
    with pytest.raises(ValueError, match="APPROVED_SCOPE"):
        report.build_report(tmp_path, "SQUEEZE")
