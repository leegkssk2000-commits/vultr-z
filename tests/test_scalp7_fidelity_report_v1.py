"""Saved-report logic fixtures; no source data, signal generation or replay."""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from backend.research.rebuild import scalp7_fidelity_report_v1 as report

TF = 900_000
WINDOWS = [
    {"label": "v", "partition": "validation", "start_ms": 0, "end_ms": 10 * TF},
    {"label": "r", "partition": "rolling", "start_ms": 10 * TF, "end_ms": 20 * TF},
]


def row(
    symbol: str = "BTC-USDT",
    stamp: int = TF,
    net: float = 100,
    *,
    side: int = 1,
    window: str = "v",
    reason: str = "STRUCTURAL_CLOSE",
) -> dict[str, Any]:
    gross = net + 14
    signal = {
        "symbol": symbol,
        "side": side,
        "signal_ts_ms": stamp,
        "identity": "synthetic",
        "timeframe_min": 15,
    }
    return {
        **signal,
        "window_label": window,
        "entry_ts_ms": stamp,
        "exit_ts_ms": stamp + TF,
        "outcome_available_ts_ms": stamp + TF,
        "entry_prices": {symbol: 100.0},
        "exit_prices": {symbol: 100 * (1 + side * gross / 10000)},
        "gross_bps": gross,
        "cost_bps": 14.0,
        "net_bps": net,
        "signal": signal,
        "reason": reason,
    }


def data(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"trades": rows, "unresolved": [], "window_receipts": []}


def empty_occupancy() -> dict[str, Any]:
    return {"events": []}


def test_event_attribution_reconciles_winner_cap_and_missing_loser() -> None:
    p = [
        row("BTC-USDT", net=100),
        row("ETH-USDT", net=50),
        row("SOL-USDT", net=-40),
        row("XRP-USDT", net=-10),
    ]
    c = [
        row("BTC-USDT", net=150),
        row("ETH-USDT", net=-20),
        row("SOL-USDT", net=-10),
        row("LINK-USDT", net=30),
        row("DOGE-USDT", net=-5),
    ]
    got = report.attribution(p, c, empty_occupancy(), empty_occupancy())
    assert got["common_count"] == 3
    assert got["missed_parent_count"] == 1
    assert got["added_child_count"] == 2
    assert got["common_net_delta_bps"] == 10
    assert got["missed_parent_net_bps"] == -10
    assert got["missed_parent_contribution_bps"] == 10
    assert got["added_child_net_bps"] == 25
    assert got["total_net_delta_bps"] == 45
    assert got["parent_winner_profit_retained_ratio"] == pytest.approx(2 / 3)
    assert got["parent_winner_group_delta_including_missed_bps"] == -20
    assert got["parent_loser_observed_loss_saved_bps"] == 40
    assert got["parent_loser_common_delta_bps"] == 30
    assert got["parent_loser_missed_loss_removed_bps"] == 10
    assert got["largest_child_winner_excluded"]["delta_vs_unchanged_parent_bps"] == -105
    assert (
        got["largest_added_child_winner_excluded"]["delta_vs_unchanged_parent_bps"]
        == 15
    )
    missed = [e for e in got["events"] if e["category"] == "MISSED_PARENT"][0]
    assert missed["child_net_bps"] is None
    assert missed["opposite_potential_status"] == "NO_OPPOSITE_EMITTED_EVENT"


def test_all_missed_parent_winners_remain_in_retention_denominator() -> None:
    got = report.attribution(
        [row(net=80), row("ETH-USDT", net=20)],
        [row(net=160)],
        empty_occupancy(),
        empty_occupancy(),
    )
    assert got["parent_winner_profit_retained_ratio"] == 0.8
    assert got["parent_winner_group_delta_including_missed_bps"] == 60


def test_no_parent_winners_or_child_winners_is_explicit() -> None:
    got = report.attribution([row(net=-10)], [], empty_occupancy(), empty_occupancy())
    assert got["parent_winner_profit_retained_ratio"] is None
    assert got["largest_child_winner_excluded"]["removed_event"] is None
    assert got["largest_child_winner_excluded"]["delta_vs_unchanged_parent_bps"] == 10


def test_event_key_separates_side_and_independent_window() -> None:
    p = row()
    opposite = row(side=-1)
    later = dict(p, window_label="r")
    got = report.attribution(
        [p], [opposite, later], empty_occupancy(), empty_occupancy()
    )
    assert got["common_count"] == 0
    assert got["added_child_count"] == 2
    with pytest.raises(ValueError, match="DUPLICATE"):
        report.indexed([p, dict(p)])


def test_occupancy_uses_unresolved_and_stop_bar_ownership() -> None:
    first = row(reason="OPEN_GAP_STOP")
    boundary = row("ETH-USDT", stamp=9 * TF)
    unresolved_signal = dict(row(stamp=5 * TF)["signal"])
    payload = data([first, boundary])
    payload["unresolved"] = [
        {
            "entry_ts_ms": 5 * TF,
            "window_label": "v",
            "position": {"signal": unresolved_signal},
        }
    ]
    signals = [
        first["signal"],
        boundary["signal"],
        dict(first["signal"], signal_ts_ms=2 * TF, side=-1),
        dict(first["signal"], signal_ts_ms=3 * TF),
        unresolved_signal,
        dict(unresolved_signal, signal_ts_ms=8 * TF),
    ]
    result = report.occupancy(payload, signals, WINDOWS, "validation")
    by_stamp = {(e["symbol"], e["signal_ts_ms"]): e for e in result["events"]}
    assert (
        by_stamp[("BTC-USDT", 2 * TF)]["status"]
        == "BLOCKED_BY_COMPLETED_POSITION_OCCUPANCY"
    )
    assert (
        by_stamp[("BTC-USDT", 3 * TF)]["status"]
        == "EMITTED_WITHOUT_SAVED_FILL_OR_OCCUPANCY_BLOCKER"
    )
    assert (
        by_stamp[("BTC-USDT", 5 * TF)]["status"] == "ENTERED_UNRESOLVED_NO_REALIZED_PNL"
    )
    assert by_stamp[("BTC-USDT", 8 * TF)]["status"] == "BLOCKED_BY_UNRESOLVED_OCCUPANCY"
    assert by_stamp[("ETH-USDT", 9 * TF)]["status"] == "COMPLETED_OUTSIDE_STRICT_WINDOW"
    assert result["counterfactual_pnl"] is None


def test_missed_signal_status_links_actual_occupancy_witness() -> None:
    p = row(stamp=2 * TF)
    occupant = row(stamp=TF, reason="OPEN_GAP_STOP")
    co = report.occupancy(
        data([occupant]), [occupant["signal"], p["signal"]], WINDOWS, "validation"
    )
    got = report.attribution([p], [occupant], empty_occupancy(), co)
    missing = next(e for e in got["events"] if e["category"] == "MISSED_PARENT")
    assert (
        missing["opposite_potential_status"]
        == "BLOCKED_BY_COMPLETED_POSITION_OCCUPANCY"
    )
    assert missing["blockers"][0]["signal_ts_ms"] == TF


def test_loss_clusters_require_exact_time_direction_and_multiple_symbols() -> None:
    rows = [
        row(net=-10),
        row("ETH-USDT", net=-20),
        row("SOL-USDT", net=-30, side=-1),
        row("XRP-USDT", stamp=2 * TF, net=-40),
        row("LINK-USDT", net=50),
    ]
    got = report.loss_clusters(rows)
    assert got["count"] == 1
    assert got["net_bps"] == got["worst_cluster_bps"] == -30
    assert got["clusters"][0]["symbols"] == ["BTC-USDT", "ETH-USDT"]


def test_half_open_partitions_no_validation_rolling_leakage() -> None:
    a = row()
    end = row(stamp=9 * TF)
    r = row(stamp=11 * TF, net=-10, window="r")
    summary = report.summaries(data([a, end, r]), WINDOWS)
    assert summary["validation"]["cost1x"]["T"] == 1
    assert summary["validation"]["closed_outside_strict_window_count"] == 1
    assert summary["rolling"]["cost1x"]["T"] == 1
    assert summary["rolling"]["cost1x"]["Net_bps"] == -10
    assert summary["validation"]["cost2x"]["Net_bps"] == 86
    assert summary["validation"]["cost2x"]["Cost_bps_T"] == 28


def test_strict_improvement_count_does_not_treat_equal_dd_as_gain() -> None:
    p, c = [row(net=10)], [row(net=20), row("ETH-USDT", net=30)]
    got = report.compare(
        data(p), data(c), [r["signal"] for r in p], [r["signal"] for r in c], WINDOWS
    )
    assert got["validation"]["strict_improvement_count"] == 2
    assert got["validation"]["strict_improvements"] == {
        "T": True,
        "WR": False,
        "Net": True,
        "DD": False,
    }
    assert got["validation"]["all_T_WR_Net_DD_strictly_improve"] is False


@pytest.mark.parametrize("side", [1, -1])
def test_independent_saved_partial_arithmetic_uses_original_entry(side: int) -> None:
    r = row(net=636, side=side)
    r["exit_prices"]["BTC-USDT"] = 105 if side == 1 else 95
    r["terminal_fraction_original_notional"] = 0.7
    r["partial_cashflows"] = [
        {
            "fraction_original_notional": 0.3,
            "fill_price": 110 if side == 1 else 90,
            "fill_interval_start_ms": TF,
            "fill_interval_end_ms": 2 * TF,
            "observed_at_ms": 2 * TF,
        }
    ]
    assert report.verify_arithmetic([r])["full_cashflow_verified"] == 1
    if side == -1:
        r["gross_bps"] = (100 / 90 - 1) * 3000 + (100 / 95 - 1) * 7000
        r["net_bps"] = r["gross_bps"] - 14
        with pytest.raises(ValueError, match="GROSS"):
            report.verify_arithmetic([r])


def test_legacy_partial_limitation_is_counted_not_invented() -> None:
    r = row()
    r["signal"]["partial_fraction"] = 0.1
    got = report.verify_arithmetic([r])
    assert got["legacy_partial_gross_not_independently_reconstructable"] == 1
    assert got["net_cost_verified"] == 1


@pytest.mark.parametrize("field", ["cost_bps", "gross_bps", "net_bps"])
def test_nonfinite_economics_cannot_enter_report(field: str) -> None:
    r = row()
    r[field] = float("nan")
    with pytest.raises(ValueError, match="NONFINITE"):
        report.verify_arithmetic([r])


def test_immutable_report_cannot_be_silently_replaced(tmp_path: Path) -> None:
    p = tmp_path / "report.json"
    report.immutable_write(p, "first")
    report.immutable_write(p, "first")
    with pytest.raises(ValueError, match="IMMUTABLE"):
        report.immutable_write(p, "second")
    assert p.read_text() == "first"


def test_saved_payload_hash_checked_before_arithmetic(tmp_path: Path) -> None:
    p = tmp_path / "trades.json.gz"
    p.write_bytes(gzip.compress(json.dumps(data([row()])).encode(), mtime=0))
    info = {"ledger_path": p.name, "ledger_sha256": "0" * 64, "unresolved_count": 0}
    with pytest.raises(ValueError, match="HASH_DRIFT"):
        report.checked_payload(tmp_path, info)


def test_saved_metric_mutation_is_detected() -> None:
    summary = report.summaries(data([row()]), WINDOWS)
    info = {"summary": copy.deepcopy(summary)}
    info["summary"]["validation"]["cost1x"]["Net_bps"] += 1
    with pytest.raises(ValueError, match="SUMMARY_DRIFT"):
        report.assert_saved_summary(info, summary)


@pytest.mark.parametrize(
    "target", ["trade", "trade_signal", "unresolved", "unresolved_signal"]
)
def test_saved_ledger_identity_is_bound_to_candidate(
    tmp_path: Path, target: str
) -> None:
    payload = data([row()])
    r = row(stamp=4 * TF)
    payload["unresolved"] = [
        {
            "identity": "synthetic",
            "symbol": r["symbol"],
            "entry_ts_ms": r["entry_ts_ms"],
            "window_label": "v",
            "position": {"signal": r["signal"], "cost_bps": 14.0},
        }
    ]
    if target == "trade":
        payload["trades"][0]["identity"] = "different"
    elif target == "trade_signal":
        payload["trades"][0]["signal"]["identity"] = "different"
    elif target == "unresolved":
        payload["unresolved"][0]["identity"] = "different"
    else:
        payload["unresolved"][0]["position"]["signal"]["identity"] = "different"
    p = tmp_path / "identity.json.gz"
    p.write_bytes(gzip.compress(json.dumps(payload).encode(), mtime=0))
    info = {
        "ledger_path": p.name,
        "ledger_sha256": report.sha(p),
        "unresolved_count": 1,
        "candidate": {"identity": "synthetic"},
    }
    with pytest.raises(ValueError, match="IDENTITY"):
        report.checked_payload(tmp_path, info)


def test_parent_or_child_potential_identity_cannot_be_relabelled() -> None:
    with pytest.raises(ValueError, match="SIGNAL_IDENTITY"):
        report.verify_signal_identity([row()["signal"]], "another_parent")


def test_snapshot_cost_binding_cannot_be_changed_with_matching_net() -> None:
    r = row()
    r["cost_bps"] = 15
    r["net_bps"] -= 1
    with pytest.raises(ValueError, match="COST_BINDING"):
        report.verify_costs(data([r]), {"BTC-USDT": 14})


def test_positive_negative_and_empty_windows_are_separate() -> None:
    got = report.summaries(data([row(net=-1)]), WINDOWS)
    assert got["validation"]["window_sign_counts"]["cost1x"] == {
        "positive": 0,
        "negative": 1,
        "nonempty_zero": 0,
        "empty": 0,
    }
    assert got["rolling"]["window_sign_counts"]["cost1x"]["empty"] == 1
    assert got["rolling"]["window_sign_counts"]["cost1x"]["negative"] == 0


def test_observed_loss_saved_can_include_common_turning_profitable() -> None:
    got = report.attribution(
        [row(net=-10)],
        [row(net=40)],
        empty_occupancy(),
        empty_occupancy(),
    )
    assert got["parent_loser_observed_loss_saved_bps"] == 50
    assert got["parent_loser_common_delta_bps"] == 50


def test_build_and_verify_four_saved_comparisons_without_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def dump(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def pack(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(json.dumps(value).encode(), mtime=0))

    def trades(identity: str, net: float) -> dict[str, Any]:
        rows = [row(net=net), row(stamp=11 * TF, net=net, window="r")]
        for r in rows:
            r["identity"] = identity
            r["signal"]["identity"] = identity
        return data(rows)

    out = tmp_path / report.REL
    specs: dict[str, dict[str, Any]] = {}
    for alias in ("HG", "RSI", "BREAK", "SRP", "SRC"):
        specs[alias] = {
            "identity": alias,
            "parent": "SRP" if alias == "SRC" else "parent_" + alias,
            "tf": 15,
        }
        if alias in ("HG", "RSI", "BREAK"):
            specs[alias]["cached_parent"] = f"parents/{alias}.json"
    monkeypatch.setattr(
        report,
        "verified_original",
        lambda _root: (
            {"windows": WINDOWS, "cost_sha256": "c" * 64},
            {"BTC-USDT": 14.0},
            {},
        ),
    )
    dump(out / "BATCH_SELECTION.json", {"scope_key": "SYNTHETIC", "candidates": specs})
    module = tmp_path / "backend/research/rebuild/scalp7_fidelity_report_v1.py"
    module.parent.mkdir(parents=True)
    module.write_text("synthetic saved-report fixture")
    for alias, spec in specs.items():
        payload = trades(alias, 20)
        lp = out / "results" / (alias + ".trades.json.gz")
        sp = out / "results" / (alias + ".signals.json.gz")
        fp = out / "freezes" / (alias + ".json")
        pack(lp, payload)
        pack(sp, [r["signal"] for r in payload["trades"]])
        dump(fp, {"windows": WINDOWS, "cost_sha256": "c" * 64, "hashes": {}})
        info = {
            "candidate": spec,
            "freeze_path": str(fp.relative_to(tmp_path)),
            "freeze_sha256": report.sha(fp),
            "ledger_path": str(lp.relative_to(tmp_path)),
            "ledger_sha256": report.sha(lp),
            "signal_path": str(sp.relative_to(tmp_path)),
            "signals_sha256": report.sha(sp),
            "unresolved_count": 0,
            "summary": report.summaries(payload, WINDOWS),
        }
        if "cached_parent" in spec:
            parent = trades(spec["parent"], 10)
            pp = tmp_path / ("parents/" + alias + ".json.gz")
            psp = out / "results" / (alias + ".parent_signals.json.gz")
            pack(pp, parent)
            pack(psp, [r["signal"] for r in parent["trades"]])
            dump(
                tmp_path / spec["cached_parent"],
                {
                    "candidate": {"identity": spec["parent"]},
                    "ledger_path": str(pp.relative_to(tmp_path)),
                    "ledger_sha256": report.sha(pp),
                    "unresolved_count": 0,
                },
            )
            info.update(
                parent_signals_path=str(psp.relative_to(tmp_path)),
                parent_signals_sha256=report.sha(psp),
            )
        dump(out / "results" / (alias + ".json"), info)
    value = report.build_report(tmp_path)
    assert value["new_full_identities"] == 5
    assert value["cached_parent_replays"] == 0
    assert value["comparison_count"] == 4
    assert set(value["comparisons"]) == {"HG", "RSI", "BREAK", "SR"}
    assert value["comparisons"]["HG"]["partitions"]["rolling"]["delta"]["Net_bps"] == 10
    for path, text in report.artifacts(value, tmp_path):
        report.immutable_write(path, text)
    assert (
        report.verify(tmp_path)["state"] == "PASS_SAVED_COMPARISON_NO_ECONOMIC_REPLAY"
    )
    md = out / "ECONOMIC_REPORT.md"
    md.write_text(md.read_text() + "tamper")
    with pytest.raises(ValueError, match="SAVED_VERIFICATION_DRIFT"):
        report.verify(tmp_path)


def test_all_duplicate_emissions_are_reported_without_double_counting_pnl() -> None:
    trade = row(side=-1)
    signals = [
        dict(trade["signal"], side=1),
        trade["signal"],
        copy.deepcopy(trade["signal"]),
    ]
    got = report.occupancy(data([trade]), signals, WINDOWS, "validation")
    assert got["potential_count"] == 3
    assert got["unique_engine_event_count"] == 1
    assert got["counts"] == {"COMPLETED_INCLUDED": 1, "DUPLICATE_SIGNAL_REJECTED": 2}
    completed = next(e for e in got["events"] if e["status"] == "COMPLETED_INCLUDED")
    assert completed["side"] == -1
    assert completed["source_signal_index"] == 1
    a = report.attribution([trade], [trade], got, got)
    assert a["common_count"] == 1
    assert a["total_net_delta_bps"] == 0
