"""Observed paper execution contract tests; deterministic fixtures, no market runs."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest  # type: ignore[import-not-found]

from backend.research.rebuild import scalp7_observed_paper_v2 as paper

TF = 15 * 60_000
BASE = 10 * TF
SYMBOL = "BTC-USDT"


def signal(**changes: Any) -> dict[str, Any]:
    result = {
        "identity": "fixture",
        "lane": "fixture",
        "timeframe_min": 15,
        "symbol": SYMBOL,
        "side": 1,
        "signal_open_ts_ms": BASE - TF,
        "signal_ts_ms": BASE + 100,
        "stop_price": 95.0,
        "max_hold_bars": 4,
        "segment_id": "observed",
    }
    result.update(changes)
    return result


def wrapper(**changes: Any) -> dict[str, Any]:
    sig = signal(**changes)
    return {
        "signal": sig,
        "observed_at_ms": sig["signal_ts_ms"],
        "opportunity_key": "one",
        "record_sha256": "a" * 64,
    }


def quote(
    stamp: int, bid: float = 99, ask: float = 100, symbol: str = SYMBOL
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "bid": bid,
        "ask": ask,
        "requested_at_ms": stamp - 1,
        "received_at_ms": stamp,
        "source_ts_ms": stamp - 1,
        "quote_id": str(stamp) + symbol,
        "receipt_sha256": "b" * 64,
    }


def frame(*opens: int, high: float = 102, low: float = 98) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "open_ts_ms": x,
                "close_ts_ms": x + TF,
                "available_ts_ms": x + TF,
                "segment_id": "observed",
                "open": 100,
                "high": high,
                "low": low,
                "close": 100,
                "volume": 1,
            }
            for x in opens
        ]
    )


def contexts(*opens: int, high: float = 102) -> dict[int, dict[str, pd.DataFrame]]:
    return {15: {SYMBOL: frame(*(opens or (BASE - TF,)), high=high)}}


def machine(module: Any = None, **config: Any) -> paper.ObservedPaper:
    cfg = {
        "fresh_start_ms": BASE,
        "max_quote_request_ms": 100,
        "max_pair_skew_ms": 10,
        "max_quote_gap_ms": TF * 10,
    }
    cfg.update(config)
    return paper.ObservedPaper(
        paper.empty_state("f" * 64),
        cfg,
        {SYMBOL: 8, "ETH-USDT": 12},
        {"fixture": module or SimpleNamespace()},
    )


def enter(m: paper.ObservedPaper, row: dict[str, Any] | None = None) -> dict[str, Any]:
    m.admit(row or wrapper(), BASE + 101)
    m.step({SYMBOL: quote(BASE + 110)}, contexts(), BASE + 110)
    return next(iter(m.state["positions"].values()))


def test_first_new_quote_enters_without_extra_timeframe_wait() -> None:
    m = machine()
    p = enter(m)
    assert p["entry_ts_ms"] == BASE + 110
    assert p["entry_price"] == 100
    assert p["actual_entry_delay_ms"] == 10
    assert p["mfe_R"] == p["mae_R"] == 0


def test_predecision_request_cannot_enter_even_received_later() -> None:
    m = machine()
    m.admit(wrapper(), BASE + 101)
    q = quote(BASE + 110)
    q["requested_at_ms"] = BASE + 99
    m.step({SYMBOL: q}, contexts(), BASE + 110)
    assert not m.state["positions"]
    assert m.state["pending"]


def test_short_entry_and_exit_cross_correct_spread_sides() -> None:
    m = machine()
    p = enter(m, wrapper(side=-1, stop_price=105))
    assert p["entry_price"] == 99
    m.step({SYMBOL: quote(BASE + 120, 106, 107)}, contexts(), BASE + 120)
    assert p["pending_exit"]["reason"] == "OBSERVED_HARD_STOP"
    m.step({SYMBOL: quote(BASE + 130, 108, 109)}, contexts(), BASE + 130)
    row = m.state["trades"][0]
    assert row["exit_prices"][SYMBOL] == 109
    assert row["gross_bps"] == pytest.approx((1 - 109 / 99) * 10_000)


def test_stop_triggers_then_later_quote_fills_not_trigger_or_ohlc_price() -> None:
    m = machine()
    p = enter(m)
    m.step({SYMBOL: quote(BASE + 120, 94, 95)}, contexts(), BASE + 120)
    assert p["pending_exit"]["decision_ms"] == BASE + 120
    assert not m.state["trades"]
    m.step({SYMBOL: quote(BASE + 130, 92, 93)}, contexts(), BASE + 130)
    row = m.state["trades"][0]
    assert row["exit_prices"][SYMBOL] == 92
    assert row["gross_bps"] == pytest.approx(-800)
    assert row["net_bps"] == pytest.approx(-808)
    assert row["stress2x_net_bps"] == pytest.approx(-816)
    assert row["exit_ts_ms"] > row["trigger"]["decision_ms"]
    assert row["order_authority"] == "BLOCKED"
    assert not row["account_or_exchange_fill"]


def test_take_profit_is_observed_trigger_and_later_executable_price() -> None:
    m = machine()
    enter(m, wrapper(take_profit_r=1))
    m.step({SYMBOL: quote(BASE + 120, 105, 106)}, contexts(), BASE + 120)
    assert not m.state["trades"]
    m.step({SYMBOL: quote(BASE + 130, 104, 105)}, contexts(), BASE + 130)
    assert m.state["trades"][0]["exit_prices"][SYMBOL] == 104


def test_partial_observed_touch_later_quote_realization_and_one_cost_reserve() -> None:
    m = machine()
    p = enter(m, wrapper(partial_take_profit_r=1, partial_fraction=0.1))
    m.step({SYMBOL: quote(BASE + 120, 106, 107)}, contexts(), BASE + 120)
    assert p["remaining"] == 1
    m.step({SYMBOL: quote(BASE + 130, 104, 105)}, contexts(), BASE + 130)
    assert p["remaining"] == pytest.approx(0.9)
    assert p["realized_parts_bps"] == pytest.approx(40)
    m.step({SYMBOL: quote(BASE + 140, 94, 95)}, contexts(), BASE + 140)
    m.step({SYMBOL: quote(BASE + 150, 90, 91)}, contexts(), BASE + 150)
    row = m.state["trades"][0]
    assert row["gross_bps"] == pytest.approx(40 - 900)
    assert row["net_bps"] == pytest.approx(40 - 900 - 8)
    assert len(row["partials"]) == 1


def test_partial_entry_bar_ohlc_high_does_not_grant_mfe_or_partial() -> None:
    called: list[Any] = []

    def callback(*args: Any) -> dict[str, Any]:
        called.append(args)
        return {"partial_fraction": 0.1}

    mod = SimpleNamespace(exit_update=callback)
    m = machine(mod)
    p = enter(m, wrapper(partial_take_profit_r=1, partial_fraction=0.1))
    m.step(
        {SYMBOL: quote(BASE + TF + 5)},
        contexts(BASE - TF, BASE, high=1000),
        BASE + TF + 5,
    )
    assert not called
    assert p["mfe_R"] == 0
    assert p["remaining"] == 1
    assert not p["pending_partial"]


def test_lifecycle_only_closed_prefix_full_post_entry_and_new_stop_after_processing() -> (
    None
):
    calls = []

    def callback(position: Any, bar: Any, history: Any) -> dict[str, Any]:
        calls.append((copy.deepcopy(position), bar, history.copy()))
        return {"next_stop": 99.5, "partial_fraction": 0.1}

    m = machine(SimpleNamespace(exit_update=callback))
    p = enter(m)
    now = BASE + 2 * TF + 10
    ctx = contexts(BASE - TF, BASE, BASE + TF, BASE + 2 * TF, high=1000)
    m.step({SYMBOL: quote(now, 99, 100)}, ctx, now)
    assert len(calls) == 1
    assert calls[0][1]["open_ts_ms"] == BASE + TF
    assert calls[0][1]["available_ts_ms"] == now
    assert calls[0][2].close_ts_ms.max() <= now
    assert p["stop_price"] == 99.5
    assert p["mfe_R"] == 0
    assert p["pending_exit"] is None
    assert not p["pending_partial"]
    m.step({SYMBOL: quote(now + 10, 99, 100)}, ctx, now + 10)
    pending: Any = p["pending_exit"]
    assert pending["reason"] == "OBSERVED_HARD_STOP"
    assert not m.state["trades"]


def test_lifecycle_exit_uses_later_quote_and_does_not_backfill_bar_open() -> None:
    m = machine(
        SimpleNamespace(
            exit_update=lambda *args: {"exit_next_open": True, "reason": "fixture_exit"}
        )
    )
    enter(m)
    now = BASE + 2 * TF + 10
    m.step({SYMBOL: quote(now, 101, 102)}, contexts(BASE - TF, BASE, BASE + TF), now)
    assert not m.state["trades"]
    m.step({SYMBOL: quote(now + 10, 103, 104)}, contexts(), now + 10)
    assert m.state["trades"][0]["exit_prices"][SYMBOL] == 103
    assert m.state["trades"][0]["reason"] == "fixture_exit"


def test_quote_gap_holds_open_without_fabricated_close() -> None:
    m = machine(max_quote_gap_ms=50)
    p = enter(m)
    m.step({SYMBOL: quote(BASE + 200, 90, 91)}, contexts(), BASE + 200)
    assert p["status"] == "HOLD_UNRESOLVED_QUOTE_GAP"
    assert not m.state["trades"]
    m.step({SYMBOL: quote(BASE + 210, 80, 81)}, contexts(), BASE + 210)
    assert p["entry_price"] == 100
    assert not m.state["trades"]


def test_missing_lifecycle_candle_holds_open() -> None:
    m = machine(SimpleNamespace(exit_update=lambda *args: {}))
    p = enter(m)
    now = BASE + 3 * TF + 10
    m.step({SYMBOL: quote(now)}, contexts(BASE - TF, BASE, BASE + 2 * TF), now)
    assert p["status"] == "HOLD_UNRESOLVED_CANDLE_GAP"
    assert not m.state["trades"]


def test_max_hold_is_actual_elapsed_time_trigger_then_next_quote() -> None:
    m = machine()
    p = enter(m, wrapper(max_hold_bars=1))
    now = p["max_hold_due_ms"]
    m.step({SYMBOL: quote(now, 101, 102)}, contexts(), now)
    assert p["pending_exit"]["reason"] == "OBSERVED_MAX_HOLD"
    assert not m.state["trades"]
    m.step({SYMBOL: quote(now + 10, 102, 103)}, contexts(), now + 10)
    assert m.state["trades"][0]["exit_ts_ms"] == now + 10


def test_pair_both_quotes_after_decision_skew_and_weighted_cost_once() -> None:
    m = machine()
    row = wrapper(
        symbol="BTC-USDT|ETH-USDT",
        side=0,
        stop_price=None,
        legs=[
            {"symbol": SYMBOL, "side": 1, "weight": 0.6},
            {"symbol": "ETH-USDT", "side": -1, "weight": 0.4},
        ],
    )
    m.admit(row, BASE + 101)
    qs = {
        SYMBOL: quote(BASE + 110),
        "ETH-USDT": quote(BASE + 125, 200, 201, "ETH-USDT"),
    }
    m.step(qs, contexts(), BASE + 125)
    assert not m.state["positions"]
    qs[SYMBOL] = quote(BASE + 124)
    m.step(qs, contexts(), BASE + 125)
    p = next(iter(m.state["positions"].values()))
    assert p["entry_prices"] == {SYMBOL: 100, "ETH-USDT": 200}
    assert p["cost_bps"] == pytest.approx(9.6)
    m._trigger(p, "fixture_pair_exit", BASE + 126)
    later = {
        SYMBOL: quote(BASE + 140, 110, 111),
        "ETH-USDT": quote(BASE + 141, 179, 180, "ETH-USDT"),
    }
    m.step(later, contexts(), BASE + 141)
    assert m.state["trades"][0]["gross_bps"] == pytest.approx(1000)
    assert m.state["trades"][0]["net_bps"] == pytest.approx(990.4)


def test_entry_update_rebinds_actual_quote_geometry_and_can_reject() -> None:
    m = machine(
        SimpleNamespace(entry_update=lambda sig, price: {"stop_price": price + 1})
    )
    m.admit(wrapper(), BASE + 101)
    m.step({SYMBOL: quote(BASE + 110)}, contexts(), BASE + 110)
    assert not m.state["positions"]
    assert m.state["events"][-1]["reason"] == "OBSERVED_FILL_INVALIDATES_STOP"


def test_superseded_wrapper_and_new_available_decision_bar_block_entry() -> None:
    m = machine()
    row = wrapper()
    row["execution_eligibility"] = "MISSED_SUPERSEDED_DECISION_OBSERVATION_ONLY"
    m.admit(row, BASE + 101)
    assert not m.state["pending"]
    m = machine()
    m.admit(wrapper(), BASE + 101)
    m.step({SYMBOL: quote(BASE + TF + 10)}, contexts(BASE - TF, BASE), BASE + TF + 10)
    assert not m.state["positions"]
    assert not m.state["pending"]


def test_restart_dedup_and_ownership_do_not_add_entry_or_close() -> None:
    m = machine()
    enter(m)
    restored = machine()
    restored.state = json.loads(json.dumps(m.state))
    restored.admit(wrapper(), BASE + 120)
    restored.step({SYMBOL: quote(BASE + 130)}, contexts(), BASE + 130)
    assert len(restored.state["positions"]) == 1
    assert not restored.state["pending"]
    assert len([x for x in restored.state["events"] if x["kind"] == "PAPER_ENTRY"]) == 1


def test_future_availability_and_old_quotes_cannot_change_stop() -> None:
    calls: list[Any] = []

    def callback(*args: Any) -> dict[str, Any]:
        calls.append(args)
        return {"next_stop": 99.5}

    m = machine(SimpleNamespace(exit_update=callback))
    p = enter(m)
    now = BASE + 2 * TF + 10
    ctx = contexts(BASE - TF, BASE, BASE + TF)
    ctx[15][SYMBOL].loc[2, "available_ts_ms"] = now + 20
    m.step({SYMBOL: quote(now)}, ctx, now)
    assert not calls
    assert p["stop_price"] == 95


def test_signal_projection_prefix_hash_restart_and_torn_suffix(tmp_path: Path) -> None:
    path = tmp_path / "signals.jsonl"
    first = {"previous_sha256": "0" * 64, "signal": signal()}
    first["record_sha256"] = paper.digest(first)
    raw = paper.json_bytes(first)
    path.write_bytes(raw + b'{"incomplete":')
    rows, cursor = paper.read_signal_projection(path, {})
    assert rows == [first]
    assert cursor["offset"] == len(raw)
    assert paper.read_signal_projection(path, cursor)[0] == []
    second = {"previous_sha256": first["record_sha256"], "signal": signal(side=-1)}
    second["record_sha256"] = paper.digest(second)
    path.write_bytes(raw + paper.json_bytes(second))
    rows, next_cursor = paper.read_signal_projection(path, cursor)
    assert rows == [second]
    assert next_cursor["last_record_sha256"] == second["record_sha256"]
    path.write_bytes(b" " + path.read_bytes()[1:])
    with pytest.raises(paper.PaperError, match="PREFIX_CHANGED"):
        paper.read_signal_projection(path, next_cursor)


def test_signal_hash_chain_mutation_rejected(tmp_path: Path) -> None:
    path = tmp_path / "signals.jsonl"
    path.write_bytes(
        paper.json_bytes(
            {"previous_sha256": "0" * 64, "record_sha256": "bad", "signal": signal()}
        )
    )
    with pytest.raises(paper.PaperError, match="HASH_CHAIN"):
        paper.read_signal_projection(path, {})


def test_normalize_public_quote_strict_identity_nonzero_prices_and_provenance() -> None:
    raw = json.dumps(
        {
            "code": 0,
            "data": {
                "symbol": SYMBOL,
                "T": BASE + 1,
                "bids": [["100", "0"], ["99", "1"]],
                "asks": [["101", "1"], ["102", "2"]],
            },
        }
    ).encode()
    q = paper.normalize_quote(raw, SYMBOL, BASE, BASE + 2)
    assert (q["bid"], q["ask"]) == (99, 101)
    assert q["body_sha256"] == hashlib.sha256(raw).hexdigest()
    assert q["quantity_unit_used"] is False
    assert not q["capacity_proven"]


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"symbol": "ETH-USDT", "bids": [[99, 1]], "asks": [[100, 1]]},
        {"bids": [[101, 1]], "asks": [[100, 1]]},
        {"bids": [[99, 0]], "asks": [[100, 1]]},
        {"bids": [[99, -1]], "asks": [[100, 1]]},
        {"bids": [[99, 1]], "asks": [[100, 1]], "T": BASE + 3},
    ],
)
def test_malformed_quotes_fail_without_fills(data: Any) -> None:
    with pytest.raises(paper.PaperError):
        paper.normalize_quote(
            json.dumps({"code": 0, "data": data}).encode(), SYMBOL, BASE, BASE + 2
        )


def runtime_fixture(tmp_path: Path, monkeypatch: Any) -> tuple[Path, Path]:
    forward_path = tmp_path / "forward_config.json"
    forward_path.write_text("{}")
    producer = tmp_path / "producer"
    producer.mkdir()
    freeze = {
        "schema": "scalp7.fresh_forward.freeze.v2",
        "config_sha256": paper.sha_file(forward_path),
    }
    freeze_path = producer / "FREEZE.json"
    freeze_path.write_bytes(paper.json_bytes(freeze))
    cfg = {
        "execution_profile": paper.PROFILE,
        "order_authority": "BLOCKED",
        "code_pins": [
            {
                "path": str(Path(paper.__file__).resolve()),
                "sha256": paper.sha_file(Path(paper.__file__)),
            }
        ],
        "fresh_config": {
            "path": str(forward_path),
            "sha256": paper.sha_file(forward_path),
        },
        "signal_sources": [
            {
                "path": str(producer / "fresh_signals.jsonl"),
                "kind": "FRESH_FORWARD",
                "freeze": {
                    "path": str(freeze_path),
                    "sha256": paper.sha_file(freeze_path),
                },
            }
        ],
        "fresh_start_ms": BASE,
        "max_quote_request_ms": 100,
        "max_pair_skew_ms": 10,
        "max_quote_gap_ms": TF * 10,
    }
    path = tmp_path / "paper_config.json"
    path.write_bytes(paper.json_bytes(cfg))
    forward = SimpleNamespace(
        read_config=lambda p: (
            {"fresh_start_ms": BASE},
            {"candidates": [{"identity": "fixture", "module": "fixture_module"}]},
            {SYMBOL: 8},
        ),
        build_current_frames=lambda *args, **kwargs: (
            contexts(),
            contexts(),
            {"fixture_receipt": True},
        ),
    )

    def import_module(name: str) -> Any:
        if name.endswith("scalp7_fresh_forward_v2"):
            return forward
        if name.endswith("scalp7_micro_decision_v2"):
            return SimpleNamespace(IDENTITY="micro_fixture")
        if name.endswith("fixture_module"):
            return SimpleNamespace()
        raise AssertionError("Unexpected import " + name)

    monkeypatch.setattr(paper.importlib, "import_module", import_module)
    return path, producer


def test_atomic_poll_restart_close_once_with_pinned_signal_chain(
    tmp_path: Path, monkeypatch: Any
) -> None:
    cfg, producer = runtime_fixture(tmp_path, monkeypatch)
    out = tmp_path / "paper"
    paper.initialize(out, cfg, BASE - 1)
    row = wrapper()
    row.update(
        previous_sha256="0" * 64, freeze_sha256=paper.sha_file(producer / "FREEZE.json")
    )
    row.pop("record_sha256")
    row["record_sha256"] = paper.digest(row)
    (producer / "fresh_signals.jsonl").write_bytes(paper.json_bytes(row))
    observations = iter(
        [quote(BASE + 110), quote(BASE + 120, 94, 95), quote(BASE + 130, 93, 94)]
    )
    monkeypatch.setattr(paper, "quote_request", lambda *args: next(observations))
    assert paper.poll(out, cfg, now_ms=BASE + 101)["open_positions"] == 1
    assert paper.poll(out, cfg, now_ms=BASE + 115)["fresh_closed_trades"] == 0
    assert paper.poll(out, cfg, now_ms=BASE + 125)["fresh_closed_trades"] == 1
    assert paper.poll(out, cfg, now_ms=BASE + 140)["fresh_closed_trades"] == 1
    persisted = paper._load_state(out, paper.sha_file(out / "FREEZE.json"))
    assert len(persisted["trades"]) == 1
    assert len(persisted["seen"]) == 1
    lines = (out / "paper_trades.jsonl").read_bytes().splitlines()
    assert len(lines) == 1
    projected = json.loads(lines[0])
    assert projected["record_sha256"] == paper.digest(
        {k: v for k, v in projected.items() if k != "record_sha256"}
    )
    assert projected["payload"]["exit_prices"][SYMBOL] == 93


def test_poll_rejects_signal_wrapper_from_different_freeze(
    tmp_path: Path, monkeypatch: Any
) -> None:
    cfg, producer = runtime_fixture(tmp_path, monkeypatch)
    out = tmp_path / "paper"
    paper.initialize(out, cfg, BASE - 1)
    row = wrapper()
    row.update(previous_sha256="0" * 64, freeze_sha256="wrong")
    row.pop("record_sha256")
    row["record_sha256"] = paper.digest(row)
    (producer / "fresh_signals.jsonl").write_bytes(paper.json_bytes(row))
    with pytest.raises(paper.PaperError, match="WRAPPER_FREEZE_MISMATCH"):
        paper.poll(out, cfg, now_ms=BASE + 101)
    assert not (out / "STATE.json").exists()


def test_runtime_requires_exact_self_path_and_matching_forward_config(
    tmp_path: Path, monkeypatch: Any
) -> None:
    cfg, producer = runtime_fixture(tmp_path, monkeypatch)
    data = json.loads(cfg.read_bytes())
    fake = tmp_path / Path(paper.__file__).name
    fake.write_text("unrelated")
    data["code_pins"] = [{"path": str(fake), "sha256": paper.sha_file(fake)}]
    cfg.write_bytes(paper.json_bytes(data))
    with pytest.raises(paper.PaperError, match="SELF_CODE_PIN_REQUIRED"):
        paper.runtime_config(cfg)


def test_state_hash_mutation_stops_restart(tmp_path: Path) -> None:
    state = paper.empty_state("f" * 64)
    state["state_sha256"] = paper.digest(state)
    state["last_poll_ms"] = 123
    (tmp_path / "STATE.json").write_bytes(paper.json_bytes(state))
    with pytest.raises(paper.PaperError, match="STATE_HASH_OR_FREEZE"):
        paper._load_state(tmp_path, "f" * 64)


def test_declared_segment_reset_holds_lifecycle_without_close() -> None:
    m = machine(SimpleNamespace(exit_update=lambda *args: {}))
    p = enter(m)
    now = BASE + 2 * TF + 10
    ctx = contexts(BASE - TF, BASE, BASE + TF)
    ctx[15][SYMBOL].loc[2, "segment_id"] = "reset"
    m.step({SYMBOL: quote(now)}, ctx, now)
    assert p["status"] == "HOLD_UNRESOLVED_CANDLE_SEGMENT"
    assert not m.state["trades"]


def test_actual_frozen_supertrend_state_bridges_partial_entry_bar_features_only() -> (
    None
):
    from backend.research.rebuild import scalp7_supertrend_architecture_v2 as st

    prices: list[tuple[float, float, float, float]] = [
        (99.8 + i, 100.4 + i, 99.4 + i, 100 + i) for i in range(10)
    ]
    prices += [
        (109.2, 111.5, 109.2, 111),
        (111, 111.4, 110, 110.8),
        (110.8, 112.4, 110.7, 112),
        (112, 113.4, 112, 113),
        (113, 113.1, 112.4, 112.8),
    ]
    rows = [
        {
            "open_ts_ms": i * st.TIMEFRAME_MS,
            "close_ts_ms": (i + 1) * st.TIMEFRAME_MS,
            "available_ts_ms": (i + 1) * st.TIMEFRAME_MS,
            "segment_id": "st_fixture",
            "open": op,
            "high": high,
            "low": low,
            "close": close,
        }
        for i, (op, high, low, close) in enumerate(prices)
    ]
    candles = pd.DataFrame(rows)
    sig = st.generate_signals({SYMBOL: candles.iloc[:13]})[0]
    decision = int(sig["signal_ts_ms"]) + 100
    sig["signal_ts_ms"] = decision
    row = {
        "signal": sig,
        "observed_at_ms": decision,
        "record_sha256": "a" * 64,
        "opportunity_key": "st",
    }
    m = machine(max_quote_gap_ms=10 * st.TIMEFRAME_MS)
    m.modules = {st.IDENTITY: st}
    m.admit(row, decision + 1)
    m.step(
        {SYMBOL: quote(decision + 10, 111.9, 112)},
        {30: {SYMBOL: candles.iloc[:13]}},
        decision + 10,
    )
    p = next(iter(m.state["positions"].values()))
    entry_ts = p["entry_ts_ms"]
    now = 15 * st.TIMEFRAME_MS + 10
    m.step({SYMBOL: quote(now, 112.7, 112.8)}, {30: {SYMBOL: candles}}, now)
    assert p["status"] == "OPEN_OBSERVED_PAPER"
    assert p["pending_exit"] is None
    assert p["entry_ts_ms"] == entry_ts
    expected = st.indicator_rows(candles)[-1]["native_state"]
    expected["available_ts_ms"] = now
    assert p["_scalp7_supertrend_state"] == expected
    assert p["mfe_R"] == pytest.approx((112.7 - 112) / (112 - sig["stop_price"]))
    assert any(
        x["kind"] == "PARTIAL_ENTRY_BAR_NATIVE_FEATURE_ONLY" for x in m.state["events"]
    )
    assert not m.state["trades"]


def test_exit_quote_included_in_mae_and_outcome_availability_is_processing_clock() -> (
    None
):
    m = machine()
    enter(m)
    m.step({SYMBOL: quote(BASE + 120, 94, 95)}, contexts(), BASE + 120)
    m.step({SYMBOL: quote(BASE + 130, 90, 91)}, contexts(), BASE + 140)
    row = m.state["trades"][0]
    assert row["mae_R"] == 2
    assert row["exit_ts_ms"] == BASE + 130
    assert row["outcome_available_ts_ms"] == BASE + 140


def test_parent_control_partial_bridge_keeps_causal_atr_and_quote_only_peak() -> None:
    from backend.research.rebuild import scalp7_parent_controls_v2 as control

    bound = control._freeze()["lanes"]["trend_rider"]
    row = wrapper(
        identity=control.IDENTITIES["trend_rider"],
        take_profit_r=None,
        partial_take_profit_r=bound["partial_take_profit_r"],
        partial_fraction=bound["partial_fraction"],
        meta={
            "atr_at_signal": 2.0,
            "close_at_signal": 100.0,
            "source_spec": copy.deepcopy(bound["source_spec"]),
        },
    )
    m = machine()
    m.modules = {control.IDENTITIES["trend_rider"]: control}
    p = enter(m, row)
    assert p["entry_price"] == 100
    candles = contexts(BASE - TF, BASE, BASE + TF)
    candles[15][SYMBOL].loc[1, "high"] = 1000
    now = BASE + 2 * TF + 10
    m.step({SYMBOL: quote(now, 110, 111)}, candles, now)
    assert p["status"] == "OPEN_OBSERVED_PAPER"
    assert p["pending_exit"] is None
    native = p["_parent_control_state"]
    partial_atr = (13 * 2.0 + (1000 - 98)) / 14
    assert native["atr"] == pytest.approx((13 * partial_atr + 4) / 14)
    assert native["open_ts_ms"] == BASE + TF
    assert native["peak"] == pytest.approx(110)
    assert p["mfe_R"] == pytest.approx(10 / p["initial_risk"])
    assert p["remaining"] == 1
    assert p["entry_ts_ms"] == BASE + 110
    assert not m.state["trades"]
    assert any(
        x["kind"] == "PARTIAL_ENTRY_BAR_PARENT_FEATURE_ONLY" for x in m.state["events"]
    )


def test_real_micro_producer_hash_profile_round_trip(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from backend.research.rebuild import scalp7_micro_producer_v2 as producer

    sig = signal(setup_id="micro_fixture", available_ts_ms=BASE + 100)
    monkeypatch.setattr(producer.time, "time", lambda: (BASE + 101) / 1000)
    producer.append_signal(tmp_path, sig)
    path = tmp_path / "signals.jsonl"
    rows, cursor = paper.read_signal_projection(path, {}, "MICRO")
    assert len(rows) == 1
    assert rows[0]["signal"]["setup_id"] == "micro_fixture"
    assert cursor["hash_profile"] == "MICRO"
    assert paper.read_signal_projection(path, cursor, "MICRO")[0] == []
    with pytest.raises(paper.PaperError, match="HASH_CHAIN"):
        paper.read_signal_projection(path, {})
    with pytest.raises(paper.PaperError, match="HASH_PROFILE_CHANGED"):
        paper.read_signal_projection(path, cursor, "FRESH_FORWARD")


def test_native_data_gap_request_is_unresolved_hold_never_economic_exit() -> None:
    m = machine(
        SimpleNamespace(
            exit_update=lambda *args: {
                "exit_next_open": True,
                "reason": "DATA_GAP_HOLD",
            }
        )
    )
    p = enter(m)
    now = BASE + 2 * TF + 10
    m.step({SYMBOL: quote(now)}, contexts(BASE - TF, BASE, BASE + TF), now)
    assert p["status"] == "HOLD_UNRESOLVED_NATIVE_STATE_GAP"
    assert p["pending_exit"] is None
    assert not m.state["trades"]
