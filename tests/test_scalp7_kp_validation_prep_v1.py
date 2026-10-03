"""K.P preparation integration: synthetic fixtures only, no source fetch/replay."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_positive_lanes_v2 as parent
from backend.research.rebuild.scalp7_source_clock_v3 import await_native_time

ADAPTER_PATH = Path(__file__).resolve().parents[1] / "research/campaigns/scalp7_20261003/kp_validation_prep_v1/adapter.py"
spec = importlib.util.spec_from_file_location("kp30_validation_preparation_adapter", ADAPTER_PATH)
assert spec is not None and spec.loader is not None
prep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)

TF = prep.TF_MS
BASE = 10 * TF
SYMBOL = "BTC-USDT"


def config(tmp_path: Path) -> dict[str, Any]:
    return prep.build_candidate_config(tmp_path / prep.NAMESPACE, t0_ms=BASE,
        window_end_ms=BASE + 2 * TF, runtime_identity="KP30_PREP_SYNTHETIC_INTEGRATION_V1",
        reference_costs_bps={SYMBOL: 8.0})


def wrapper() -> dict[str, Any]:
    signal = {"identity": prep.CANDIDATE, "lane": "keltner_holygrail", "timeframe_min": 30,
        "symbol": SYMBOL, "side": 1, "signal_open_ts_ms": BASE - TF,
        "signal_ts_ms": BASE + 100, "segment_id": "synthetic",
        "stop_price": 95.0, "max_hold_bars": 25, "take_profit_r": None,
        "exit_policy": "KELTNER_HG_FEE_BE_PARTIAL_RUNNER", "partial_take_profit_r": 2.0,
        "partial_fraction": 0.10, "meta": {"spec_sha256": parent.SPEC_SHA256,
            "regime": "TREND_DISPERSED", "feature_available_ts_ms": BASE + 100,
            "frozen_cost_bps": 8.0, "fallback_stop_atr_mult": 1.2,
            "be_arm_r": 1.0, "entry_cost_gate": {"atr_price": 2.0, "min_ratio": 4.5},
            "atr_at_signal": 2.0, "close_at_signal": 100.0}}
    return {"signal": signal, "observed_at_ms": BASE + 100, "decision_bar_close_ms": BASE,
        "bar_available_ts_ms": BASE + 50, "opportunity_key": "synthetic-signal-one",
        "record_sha256": "a" * 64, "source_bar_sha256": "c" * 64}


def quotes(stamp: int, bid: float = 99.0, ask: float = 100.0) -> dict[str, Any]:
    proof = await_native_time(stamp, stamp, clock_ms=lambda: stamp,
        monotonic_ns=lambda: 0, sleep=lambda _: None)
    return {SYMBOL: {"symbol": SYMBOL, "bid": bid, "ask": ask,
        "requested_at_ms": stamp - 1, "received_at_ms": stamp, "source_ts_ms": stamp,
        "usable_at_ms": stamp, "clock_proof": proof, "quote_id": str(stamp),
        "body_sha256": "b" * 64, "receipt_sha256": "d" * 64}}


def frames() -> dict[int, Any]:
    return {30: {SYMBOL: pd.DataFrame([{"open_ts_ms": BASE - TF, "close_ts_ms": BASE,
        "available_ts_ms": BASE + 50, "segment_id": "synthetic", "open": 100.0,
        "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}])}}


def enter(checkpoint: Any, observe: bool = True) -> None:
    checkpoint.apply_synthetic("admit", now_ms=BASE + 101, wrapper=wrapper(),
        quotes={}, frames=frames(), observe=observe)
    checkpoint.apply_synthetic("entry", now_ms=BASE + 110, quotes=quotes(BASE + 110),
        frames=frames(), observe=observe)


def complete_trade(checkpoint: Any, observe: bool = True) -> dict[str, Any]:
    enter(checkpoint, observe)
    checkpoint.apply_synthetic("partial-trigger", now_ms=BASE + 120,
        quotes=quotes(BASE + 120, 110, 111), frames=frames(), observe=observe)
    checkpoint.apply_synthetic("partial-fill", now_ms=BASE + 130,
        quotes=quotes(BASE + 130, 111, 112), frames=frames(), observe=observe)
    checkpoint.apply_synthetic("stop-trigger", now_ms=BASE + 140,
        quotes=quotes(BASE + 140, 94, 95), frames=frames(), observe=observe)
    checkpoint.apply_synthetic("exit-fill", now_ms=BASE + 150,
        quotes=quotes(BASE + 150, 93, 94), frames=frames(), observe=observe)
    return checkpoint.state["paper_state"]["trades"][0]


def costs() -> dict[str, Any]:
    return {kind: {"symbol": SYMBOL, "fee_bps": 1.0, "spread_bps": 2.0,
        "slippage_bps": 0.5, "spread_semantics": "EMBEDDED_IN_OBSERVED_BID_ASK",
        "slippage_semantics": "ADDITIONAL_MODEL_DEBIT_NOT_EMBEDDED_IN_QUOTED_PRICE",
        "known_at_ms": BASE, "body_sha256": "e" * 64} for kind in ("ENTRY", "PARTIAL", "EXIT")}


def funding(stamp: int, rate: float = 0.001) -> dict[str, Any]:
    return {"symbol": SYMBOL, "settlement_ms": stamp, "received_at_ms": stamp + 1,
        "signed_rate": rate, "mark_price": 100.0, "body_sha256": "f" * 64}


def ledger(row: dict[str, Any], **changes: Any) -> dict[str, Any]:
    args = {"original_qty": 2.0, "quantity_lineage": {"original_qty": 2.0,
        "known_at_ms": BASE, "kind": "PAPER_ORIGINAL_QUANTITY_MODEL", "body_sha256": "1" * 64},
        "pit_costs": costs(), "funding": [], "funding_coverage": {"complete": True,
        "start_ms": row["entry_ts_ms"], "end_ms": row.get("exit_ts_ms"), "body_sha256": "2" * 64}}
    args.update(changes)
    return prep.link_cashflows(row, **args)


def test_exact_candidate_config_parent_pin_and_other_lane_files_preserved(tmp_path: Path) -> None:
    other = tmp_path / "other-lane.json"
    other.write_text('{"candidate":"SR","consumed":2}')
    before = other.read_bytes()
    cfg = config(tmp_path)
    with prep.PrepCheckpoint(cfg) as cp:
        enter(cp)
        assert cp.snapshot()["open_positions"] == 1
    assert other.read_bytes() == before
    assert cfg["parent_module_sha256"] == prep.PARENT_MODULE_SHA
    assert cfg["new_full_credit"] == 0
    assert not cfg["g5b_terminal"]
    with pytest.raises(prep.PrepError, match="OUTPUT_NAMESPACE"):
        prep.build_candidate_config(tmp_path / "shared", t0_ms=BASE, window_end_ms=BASE+TF,
            runtime_identity="KP30_PREP_SYNTHETIC_TEST", reference_costs_bps={SYMBOL: 8})


@pytest.mark.parametrize("field,value", [("partial_fraction", 0.30), ("max_hold_bars", 20),
    ("take_profit_r", 1.0), ("timeframe_min", 15), ("identity", "SR_CONTROL")])
def test_parent_rule_drift_is_rejected(field: str, value: Any) -> None:
    row = wrapper()
    row["signal"][field] = value
    with pytest.raises(prep.PrepError):
        prep.validate_signal_clock(row, BASE + 101)


def test_complete_bar_and_availability_clock_block_pre_signal() -> None:
    row = wrapper()
    row["bar_available_ts_ms"] = BASE + 200
    with pytest.raises(prep.PrepError, match="AVAILABILITY"):
        prep.validate_signal_clock(row, BASE + 101)
    row = wrapper()
    row["signal"]["signal_open_ts_ms"] += 1
    with pytest.raises(prep.PrepError, match="UTC30M"):
        prep.validate_signal_clock(row, BASE + 101)


def test_late_received_quote_does_not_fill_then_new_quote_can_fill(tmp_path: Path) -> None:
    with prep.PrepCheckpoint(config(tmp_path)) as cp:
        cp.apply_synthetic("signal", now_ms=BASE+101, wrapper=wrapper(), quotes={}, frames=frames())
        late = quotes(BASE+6000)
        late[SYMBOL]["requested_at_ms"] = BASE+102
        cp.apply_synthetic("late", now_ms=BASE+6000, quotes=late, frames=frames())
        assert not cp.state["paper_state"]["positions"]
        assert cp.state["paper_state"]["pending"]
        cp.apply_synthetic("new", now_ms=BASE+6010, quotes=quotes(BASE+6010), frames=frames())
        assert cp.snapshot()["open_positions"] == 1


def test_partial_original_quantity_remainder_r_and_no_reserve_double_debit(tmp_path: Path) -> None:
    with prep.PrepCheckpoint(config(tmp_path)) as cp:
        row = complete_trade(cp)
        result = ledger(row)
        entry, partial, final = result["cashflows"]
        assert entry["original_qty"] == 2.0
        assert partial["event_qty"] == pytest.approx(0.2)
        assert partial["remaining_qty"] == pytest.approx(1.8)
        assert final["event_qty"] == pytest.approx(1.8)
        assert final["remaining_qty"] == pytest.approx(0)
        assert result["gross_original_notional_bps"] == pytest.approx(-520)
        assert result["initial_r"]["initial_risk_bps"] == pytest.approx(500)
        assert result["net_pnl_r"] == pytest.approx(result["net_original_notional_bps"] / 500)
        assert result["reference_reserve_bps_reported_separately"] == 8
        assert not result["reference_reserve_subtracted_in_pit_net"]
        assert not result["spread_subtracted_twice"]
        assert row["evidence_kind"] == "SYNTHETIC_PREPARATION_ONLY"
        assert not result["terminal_eligible"]


def test_funding_partial_boundary_before_reduction_and_exit_inclusive(tmp_path: Path) -> None:
    with prep.PrepCheckpoint(config(tmp_path)) as cp:
        row = complete_trade(cp)
        result = ledger(row, funding=[funding(BASE+130), funding(BASE+131), funding(BASE+150)])
        settlements = result["funding_settlements"]
        assert [x["remaining_original_fraction"] for x in settlements] == pytest.approx([1.0, 0.9, 0.9])
        assert result["signed_funding_debit_bps"] == pytest.approx(28)
        assert ledger(row, funding=[funding(BASE+131, -0.001)])["signed_funding_debit_bps"] == pytest.approx(-9)
        with pytest.raises(prep.PrepError, match="OUTSIDE"):
            ledger(row, funding=[funding(row["entry_ts_ms"])])


def test_missing_funding_cost_quantity_stays_null_and_blocked(tmp_path: Path) -> None:
    with prep.PrepCheckpoint(config(tmp_path)) as cp:
        row = complete_trade(cp)
        result = ledger(row, original_qty=None, quantity_lineage=None, pit_costs={}, funding=None, funding_coverage=None)
        assert result["net_pnl_r"] is None
        assert result["signed_funding_debit_bps"] is None
        assert result["fee_r"] is None
        assert result["cashflows"][1]["remaining_qty"] is None
        assert "ORIGINAL_QUANTITY_LINEAGE_MISSING" in result["blockers"]
        result = ledger(row, quantity_lineage=None)
        assert "ORIGINAL_QUANTITY_SOURCE_RECEIPT_MISSING" in result["blockers"]


def test_source_index_seen_first_and_unknown_inventory_never_fresh() -> None:
    item = {"body_sha256": "a"*64, "received_at_ms": BASE+10, "start_ms": BASE,
        "end_exclusive_ms": BASE+TF, "usage_inventory_sha256": "b"*64,
        "usage_inventory_complete": True, "source_id": "public-btc"}
    seen = [{"source_id": "*", "start_ms": BASE-TF, "end_exclusive_ms": BASE+1}]
    assert prep.inspect_source_index(item, seen)["state"] == "BLOCKED_BEFORE_BODY_READ"
    item["usage_inventory_complete"] = False
    assert "USAGE_INVENTORY_INCOMPLETE" in prep.inspect_source_index(item, [])["reasons"]
    item["usage_inventory_complete"] = True
    result = prep.inspect_source_index(item, [])
    assert result["state"] == "NOT_PREVIOUSLY_INSPECTED_METADATA"
    assert not result["genuine_fresh"] and not result["body_opened"]


def test_window_end_keeps_incomplete_and_cannot_fill_pending(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    with prep.PrepCheckpoint(cfg) as cp:
        cp.apply_synthetic("pending", now_ms=BASE+101, wrapper=wrapper(), quotes={}, frames=frames())
        cp.apply_synthetic("end", now_ms=cfg["window_end_ms"], quotes=quotes(cfg["window_end_ms"]), frames=frames())
        assert cp.state["paper_state"]["pending"]
        assert not cp.state["paper_state"]["positions"]
    with prep.PrepCheckpoint(cfg, recover=True) as cp:
        assert cp.snapshot()["attempt_count"] == 1
    other = config(tmp_path / "other")
    with prep.PrepCheckpoint(other) as cp:
        enter(cp)
        cp.apply_synthetic("end-open", now_ms=other["window_end_ms"], quotes={}, frames=frames())
        assert cp.snapshot()["open_positions"] == 1
        assert cp.snapshot()["closed_synthetic_trades"] == 0
        assert cp.state["history"][-2]["kind"] == "WINDOW_END_INCOMPLETE_PRESERVED"


def test_missing_and_returning_quote_preserves_position_and_gap_stays_hold(tmp_path: Path) -> None:
    with prep.PrepCheckpoint(config(tmp_path)) as cp:
        enter(cp)
        cp.apply_synthetic("missing", now_ms=BASE+120, quotes={}, frames=frames())
        assert cp.snapshot()["open_positions"] == 1
        cp.apply_synthetic("return", now_ms=BASE+130, quotes=quotes(BASE+130), frames=frames())
        p = next(iter(cp.state["paper_state"]["positions"].values()))
        assert p["last_quote_ms"] == BASE+130
        cp.apply_synthetic("gap", now_ms=BASE+90200, quotes={}, frames=frames())
        assert p is not next(iter(cp.state["paper_state"]["positions"].values()))
        held = next(iter(cp.state["paper_state"]["positions"].values()))
        assert held["status"] == "HOLD_UNRESOLVED_QUOTE_GAP"
        cp.apply_synthetic("later", now_ms=BASE+90210, quotes=quotes(BASE+90210), frames=frames())
        assert cp.snapshot()["open_positions"] == 1
        assert not cp.state["paper_state"]["trades"]


def test_event_and_signal_duplicate_payload_integrity(tmp_path: Path) -> None:
    with prep.PrepCheckpoint(config(tmp_path)) as cp:
        enter(cp)
        before = cp.snapshot()
        assert cp.apply_synthetic("entry", now_ms=BASE+110, quotes=quotes(BASE+110), frames=frames()) == before
        with pytest.raises(prep.PrepError, match="EVENT_PAYLOAD_CHANGED"):
            cp.apply_synthetic("entry", now_ms=BASE+111, quotes=quotes(BASE+111), frames=frames())
        changed = wrapper()
        changed["record_sha256"] = "f"*64
        with pytest.raises(prep.PrepError, match="SIGNAL_PAYLOAD"):
            cp.apply_synthetic("new-id", now_ms=BASE+111, wrapper=changed, quotes={}, frames=frames())


@pytest.mark.parametrize("failed", [False, True])
def test_interrupt_explicit_resume_preserves_attempt_failures_and_position(tmp_path: Path, failed: bool) -> None:
    cfg = config(tmp_path)
    cp = prep.PrepCheckpoint(cfg)
    enter(cp)
    original = cp.state["paper_state"]
    cp.interrupt("synthetic crash", failed=failed)
    cp.close()
    with pytest.raises(prep.PrepError, match="EXPLICIT_RECOVERY"):
        prep.PrepCheckpoint(cfg)
    with prep.PrepCheckpoint(cfg, recover=True) as resumed:
        assert resumed.state["paper_state"] == original
        assert resumed.snapshot()["attempt_count"] == 1
        assert resumed.snapshot()["consumed_full_credit"] == 0
        assert any(x["kind"] == ("FAILED" if failed else "INTERRUPTED") for x in resumed.state["history"])
        assert resumed.state["history"][-1]["kind"] == "EXPLICIT_RECOVERY"


def test_saved_started_requires_recovery_and_single_writer(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    cp = prep.PrepCheckpoint(cfg)
    with pytest.raises(prep.PrepError, match="SINGLE_WRITER"):
        prep.PrepCheckpoint(cfg)
    enter(cp)
    cp.close()
    with pytest.raises(prep.PrepError, match="EXPLICIT_RECOVERY"):
        prep.PrepCheckpoint(cfg)
    with prep.PrepCheckpoint(cfg, recover=True) as resumed:
        assert resumed.snapshot()["open_positions"] == 1
        assert resumed.state["history"][-1]["prior_status"] == "STARTED"


def test_supplied_quote_mutation_cannot_rewrite_checkpoint_provenance(tmp_path: Path) -> None:
    with prep.PrepCheckpoint(config(tmp_path)) as cp:
        cp.apply_synthetic("admit", now_ms=BASE+101, wrapper=wrapper(), quotes={}, frames=frames())
        supplied = quotes(BASE+110)
        cp.apply_synthetic("entry", now_ms=BASE+110, quotes=supplied, frames=frames())
        before = copy.deepcopy(cp.state)
        supplied[SYMBOL]["body_sha256"] = "0"*64
        supplied[SYMBOL]["bid"] = 1
        assert cp.state == before


def test_checkpoint_tamper_and_write_failure_never_advance(tmp_path: Path, monkeypatch: Any) -> None:
    cfg = config(tmp_path)
    with prep.PrepCheckpoint(cfg) as cp:
        enter(cp)
        previous = copy.deepcopy(cp.state)
        raw = (cp.out / "STATE.json").read_bytes()
        def fail(*args: Any) -> None:
            raise OSError("synthetic disk failure")
        monkeypatch.setattr(prep, "atomic_json", fail)
        with pytest.raises(OSError, match="disk failure"):
            cp.apply_synthetic("new", now_ms=BASE+120, quotes={}, frames=frames())
        assert cp.state == previous
        assert (cp.out / "STATE.json").read_bytes() == raw
        monkeypatch.undo()
    state = json.loads(raw)
    state["paper_state"]["trades"].append({"tampered": True})
    (Path(cfg["output_root"]) / "STATE.json").write_text(json.dumps(state))
    with pytest.raises(prep.PrepError, match="HASH_OR_CONFIGURATION"):
        prep.PrepCheckpoint(cfg, recover=True)


def test_observation_toggle_preserves_every_decision_and_cashflow(tmp_path: Path) -> None:
    results = []
    for enabled in (False, True):
        cfg = config(tmp_path / str(enabled))
        with prep.PrepCheckpoint(cfg) as cp:
            row = complete_trade(cp, enabled)
            decision = copy.deepcopy(cp.state["paper_state"])
            decision.pop("freeze_sha256")  # isolated paths differ, decisions do not
            results.append((decision, ledger(row), len(cp.state["observations"])))
    assert results[0][0] == results[1][0]
    assert results[0][1] == results[1][1]
    assert results[0][2] == 0 < results[1][2]


@pytest.mark.parametrize("observed_bid,expected_stop", [(105.0, 100.1), (115.0, 108.75)])
def test_real_parent_closed_bar_be_and_runner_observation_invariance(
    tmp_path: Path, observed_bid: float, expected_stop: float,
) -> None:
    decisions = []
    for enabled in (False, True):
        cfg = config(tmp_path / str(enabled))
        # Future candles supplied here are synthetic and filtered by availability.
        # Extreme OHLC high may make a partial hint, never quote-MFE or a fill.
        candles = frames()
        df = candles[30][SYMBOL]
        candles[30][SYMBOL] = pd.concat([df, pd.DataFrame([
            {"open_ts_ms": opened, "close_ts_ms": opened + TF,
             "available_ts_ms": opened + TF + 5, "segment_id": "synthetic",
             "open": 100.0, "high": 1000.0, "low": 90.0, "close": 100.0, "volume": 1.0}
            for opened in (BASE, BASE + TF)])], ignore_index=True)
        with prep.PrepCheckpoint(cfg) as cp:
            enter(cp, enabled)
            for index in range(1, 61):
                now = BASE + 110 + index * 60_000
                cp.apply_synthetic("causal-quote-" + str(index), now_ms=now,
                    quotes=quotes(now, observed_bid, observed_bid + 1),
                    frames=candles, observe=enabled)
                position = next(iter(cp.state["paper_state"]["positions"].values()))
                if index < 60:
                    assert position["stop_price"] == 95.0
            assert position["status"] == "OPEN_OBSERVED_PAPER"
            assert position["stop_price"] == pytest.approx(expected_stop)
            assert position["mfe_R"] == pytest.approx((observed_bid - 100) / 5)
            assert position["next_lifecycle_open_ms"] == BASE + 2 * TF
            assert any(x["kind"] == "STOP_ACTIVATED_AFTER_BAR_AVAILABILITY"
                for x in cp.state["paper_state"]["events"])
            assert len(position["partials"]) == (0 if observed_bid == 105 else 1)
            if enabled:
                moved = [x for x in cp.state["observations"] if x["observation_kind"] == "STOP_ACTIVATED"]
                assert len(moved) == 1
                assert moved[0]["stop_before"] == 95.0
                assert moved[0]["mfe_r_so_far"] == pytest.approx((observed_bid-100)/5)
                assert moved[0]["reason_code"] == "FROZEN_PARENT_STOP_ACTIVATION"
                assert not moved[0]["feature_used_for_decision"]
            state = copy.deepcopy(cp.state["paper_state"])
            state.pop("freeze_sha256")
            decisions.append(state)
    assert decisions[0] == decisions[1]


def test_initial_r_reuses_effective_fallback_and_is_not_be_r() -> None:
    signal = wrapper()["signal"]
    signal["stop_price"] = 110.0
    initial = prep.proposed_initial_r(signal, 100.0)
    assert initial["effective_initial_stop"] == pytest.approx(97.6)
    assert initial["initial_risk_bps"] == pytest.approx(240)
    assert not initial["changes_with_be_or_trailing"]


def test_lineage_rejects_other_symbol_quote_price_and_embedded_ambiguity(tmp_path: Path) -> None:
    with prep.PrepCheckpoint(config(tmp_path)) as cp:
        row = complete_trade(cp)
        wrong = funding(BASE+131)
        wrong["symbol"] = "ETH-USDT"
        with pytest.raises(prep.PrepError, match="FUNDING_SYMBOL"):
            ledger(row, funding=[wrong])
        bad_costs = costs()
        bad_costs["PARTIAL"].pop("spread_semantics")
        with pytest.raises(prep.PrepError, match="AMBIGUOUS"):
            ledger(row, pit_costs=bad_costs)
        drift = copy.deepcopy(row)
        drift["partials"][0]["prices"][SYMBOL] += 1
        with pytest.raises(prep.PrepError, match="QUOTE_MISMATCH"):
            ledger(drift)


def test_preflight_synthetic_pass_does_not_unlock_execution() -> None:
    result = prep.prepared_preflight({"synthetic_integration_pass": True,
        "protocol_approved": True, "evidence_kind": "SYNTHETIC_ONLY"})
    assert result["synthetic_integration_reported_pass"]
    assert result["state"] == "EXECUTION_BLOCKED"
    assert not result["execution_ready"]
    assert result["new_full_authorized_here"] == 0
    codes = {x["code"] for x in result["blockers"]}
    assert "SYNTHETIC_IS_NOT_REAL_SOURCE_EVIDENCE" in codes
    assert "PREPARATION_BRIDGE_HAS_NO_MARKET_RUNNER" in codes
