from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from backend.research.rebuild import scalp7_mr_formation_v2 as parent_rules
from backend.research.rebuild.scalp7_mr_cost2_child_v1 import (
    COST_COVERED_IDENTITY,
    exit_update,
    generate_signals,
)
from backend.research.rebuild.scalp7_mr_formation_v2 import PAIR, PARENT_IDENTITY

ROOT = Path(__file__).resolve().parents[1]


def control_frames():
    spec = importlib.util.spec_from_file_location(
        "mr_parent_fixtures", ROOT / "tests/test_scalp7_mr_formation_v2.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.control_frames()


def test_issue1377_cost_covered_child_requires_complete_frozen_costs() -> None:
    bars = control_frames()
    with pytest.raises(ValueError, match="FROZEN_COST_AUTHORITY_REQUIRED"):
        generate_signals(bars, COST_COVERED_IDENTITY)
    with pytest.raises(ValueError, match="FROZEN_COST_AUTHORITY_REQUIRED"):
        generate_signals(bars, COST_COVERED_IDENTITY, {PAIR[0]: 15.0})


def test_issue1377_gate_uses_only_observed_contraction_and_exact_cost2() -> None:
    from backend.research.rebuild.scalp7_mr_formation_v2 import PARENT_SYMBOLS

    bars = control_frames()
    parent = parent_rules.generate_signals(bars, PARENT_IDENTITY)
    assert parent
    cheap = {symbol: 15.0 for symbol in PARENT_SYMBOLS}
    child = generate_signals(bars, COST_COVERED_IDENTITY, cheap)
    assert child
    signal = child[0]
    assert signal["signal_open_ts_ms"] == parent[0]["signal_open_ts_ms"]
    assert signal["max_hold_bars"] == parent[0]["max_hold_bars"] == 8
    assert signal["meta"]["observed_contraction_bps"] == pytest.approx(50.0)
    assert signal["meta"]["frozen_pair_cost_1x_bps"] == pytest.approx(15.0)
    assert signal["meta"]["cost2_hurdle_bps"] == pytest.approx(30.0)
    assert signal["meta"]["issue1377_gate"] == (
        "OBSERVED_FIRST_CONTRACTION_GTE_EXACT_FROZEN_PAIR_COST2"
    )

    expensive = {symbol: 30.0 for symbol in PARENT_SYMBOLS}
    assert generate_signals(bars, COST_COVERED_IDENTITY, expensive) == []
    assert parent_rules.generate_signals(bars, PARENT_IDENTITY) == parent


def test_issue1377_child_exit_and_occupancy_are_parent_exact() -> None:
    from backend.research.rebuild.scalp7_mr_formation_v2 import PARENT_SYMBOLS

    bars = control_frames()
    costs = {symbol: 15.0 for symbol in PARENT_SYMBOLS}
    child = generate_signals(bars, COST_COVERED_IDENTITY, costs)[0]
    current = {symbol: frame.iloc[24].to_dict() for symbol, frame in bars.items()}
    assert exit_update({"signal": child, "hold_bars": 4}, current, {}) == {
        "exit_next_open": False,
        "reason": None,
        "current_spread6h": None,
    }
    assert exit_update({"signal": child, "hold_bars": 8}, current, {})["reason"] == (
        "TIME_8BAR"
    )


@pytest.mark.parametrize("case", ["base", "late", "gap", "segment", "gate_occupancy"])
@pytest.mark.parametrize("cost", [0.0, 15.0, 30.0])
def test_child_signals_match_pr1378_before_separation(case, cost) -> None:
    # Captured from PR1378's unchanged blob 63ca72bd3bddd5a883cdde20637df285893a8f1f
    # before restoration. These are synthetic signals, never economic evidence.
    expected = json.loads(
        (
            ROOT / "tests/fixtures/scalp7_mr_cost2_child_v1/pr1378_signal_digests.json"
        ).read_text()
    )[case + ":" + str(cost)]
    bars = control_frames()
    if case == "late":
        for frame in bars.values():
            frame["available_at_ms"] += 1000
    elif case == "gap":
        bars["SOL-USDT"] = bars["SOL-USDT"].drop(index=22).reset_index(drop=True)
    elif case == "segment":
        bars["ETH-USDT"].loc[22:, "segment_id"] = 1
    elif case == "gate_occupancy":
        bars["BTC-USDT"].loc[19:21, "close"] = [104.0, 103.9, 103.0]
    signals = generate_signals(
        bars, costs_bps={s: cost for s in parent_rules.PARENT_SYMBOLS}
    )
    actual = hashlib.sha256(
        json.dumps(
            signals, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    assert {"T": len(signals), "sha256": actual} == expected


def test_parent_is_the_original_preregistered_source() -> None:
    name = "backend/research/rebuild/scalp7_mr_formation_v2.py"
    contract = json.loads(
        (
            ROOT
            / "research/campaigns/scalp7_20260915/broad_rebuild_v2/CAMPAIGN_PREREGISTERED_V2.json"
        ).read_text()
    )
    expected = "1674f245d57ed8b6d2b7ddd1984c1dade37af49172ef8fdd4341b8bbb873e6e5"
    assert contract["code_hashes"][name] == expected
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    assert not hasattr(parent_rules, "COST_COVERED_IDENTITY")


def test_rejected_parent_entry_does_not_consume_child_occupancy() -> None:
    bars = control_frames()
    bars["BTC-USDT"].loc[19:21, "close"] = [104.0, 103.9, 103.0]
    costs = {s: 15.0 for s in parent_rules.PARENT_SYMBOLS}
    parent = parent_rules.generate_signals(bars, PARENT_IDENTITY)
    child = generate_signals(bars, costs_bps=costs)
    assert parent[0]["signal_open_ts_ms"] == int(bars["BTC-USDT"].iloc[20].ts_ms)
    assert child[0]["signal_open_ts_ms"] == int(bars["BTC-USDT"].iloc[21].ts_ms)
    assert all(
        row["signal_open_ts_ms"] != child[0]["signal_open_ts_ms"] for row in parent
    )
    prefix = {s: frame.iloc[:22] for s, frame in bars.items()}
    assert generate_signals(prefix, costs_bps=costs) == child[:1]


@pytest.mark.parametrize("bad", [-1.0, float("inf"), float("nan")])
def test_child_rejects_invalid_frozen_costs(bad) -> None:
    costs = {s: 15.0 for s in parent_rules.PARENT_SYMBOLS}
    costs["SOL-USDT"] = bad
    with pytest.raises(ValueError, match="ISSUE1377_INVALID_FROZEN_COST"):
        generate_signals(control_frames(), costs_bps=costs)


def test_child_exact_asymmetric_cost_and_exit_do_not_mutate_identity() -> None:
    costs = {s: 15.0 for s in parent_rules.PARENT_SYMBOLS}
    costs["BTC-USDT"], costs["ETH-USDT"] = 10.0, 20.0
    child = generate_signals(control_frames(), costs_bps=costs)[0]
    assert child["meta"]["frozen_pair_cost_1x_bps"] == 15.0
    for held in range(11):
        result = exit_update({"signal": child, "hold_bars": held}, {}, {})
        assert result == {
            "exit_next_open": held >= 8,
            "reason": "TIME_8BAR" if held >= 8 else None,
            "current_spread6h": None,
        }
        assert child["identity"] == COST_COVERED_IDENTITY


def test_child_never_reenters_on_exit_decision_close() -> None:
    bars = control_frames()
    costs = {s: 0.0 for s in parent_rules.PARENT_SYMBOLS}
    signals = generate_signals(bars, costs_bps=costs)
    first_exit = signals[0]["signal_open_ts_ms"] + 8 * parent_rules.TF_MS
    assert all(row["signal_open_ts_ms"] != first_exit for row in signals)


def test_batch_dispatches_parent_and_child_to_their_own_lifecycle(monkeypatch) -> None:
    from ops import issue1377_mr_batch_v1 as batch

    calls = []

    def replay(signals, frames, costs, *, identity, exit_update):
        calls.append((identity, exit_update))
        assert signals == []
        return {"trades": [], "unresolved": [], "rejections": {}}

    monkeypatch.setattr(batch.binding, "replay", replay)
    market: dict[str, Any] = {"frames": {}, "costs": {}}
    batch._run_identity(batch.PARENT, market)
    batch._run_identity(batch.CANDIDATE, market)
    assert calls == [
        (batch.PARENT, parent_rules.exit_update),
        (batch.CANDIDATE, batch.child_rules.exit_update),
    ]
