"""Source-first synthetic logic fixtures; no historical data or economic replay."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import types
from typing import Any

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_break_architecture_v2 as parent
from backend.research.rebuild import scalp7_fidelity_break_v1 as child


def bar(
    i: int,
    o: float = 100,
    h: float = 101,
    low: float = 99,
    c: float = 100,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "open_ts_ms": i * child.TIMEFRAME_MS,
        "close_ts_ms": (i + 1) * child.TIMEFRAME_MS,
        "available_ts_ms": (i + 1) * child.TIMEFRAME_MS,
        "segment_id": "A",
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        **extra,
    }


def shallow_rows() -> list[dict[str, Any]]:
    return [bar(i) for i in range(20)] + [
        bar(20, 100, 106, 100, 105),
        bar(21, 105, 108, 103, 107),
        bar(22, 107, 107.5, 102, 105),
        bar(23, 105, 109, 102.5, 108),
    ]


def run(rows: list[dict[str, Any]], module: Any = child) -> list[dict[str, Any]]:
    return module.generate_signals({"BTC-USDT": pd.DataFrame(rows)})


def shallow(rows: list[dict[str, Any]], module: Any = child) -> list[dict[str, Any]]:
    return [s for s in run(rows, module) if s["meta"]["fidelity"]["path"] == "SHALLOW"]


def assert_valid(module: Any = child) -> None:
    rows = shallow_rows()
    result = shallow(rows, module)
    assert len(result) == 1
    signal = result[0]
    assert signal["signal_open_ts_ms"] == 23 * child.TIMEFRAME_MS
    assert signal["signal_ts_ms"] == 24 * child.TIMEFRAME_MS
    assert signal["stop_price"] == 102
    assert signal["invalidation_price"] == 101
    assert signal["max_hold_bars"] == 24
    assert signal["take_profit_r"] is None
    assert "entry_price" not in signal


def assert_no_countertrend(module: Any = child) -> None:
    rows = shallow_rows()[:22] + [
        bar(22, 107, 109, 104, 108),
        bar(23, 108, 110, 105, 109),
    ]
    assert shallow(rows, module) == []


def assert_close_conjunction(module: Any = child) -> None:
    rows = shallow_rows()
    rows[22] = bar(22, 107, 108, 102, 107.2)
    rows[23] = bar(23, 107.2, 110, 102.5, 109)
    assert shallow(rows, module) == []


def assert_adverse(module: Any = child) -> None:
    rows = shallow_rows()
    rows[23]["low"] = 101.9
    assert shallow(rows, module) == []


def assert_ttl(module: Any = child) -> None:
    rows = shallow_rows()[:22]
    rows.extend(bar(i, 107, 108, 103, 107) for i in range(22, 29))
    rows.extend(
        [
            bar(29, 107, 107.5, 102, 105),
            bar(30, 105, 107, 102.5, 105),
            bar(31, 105, 109, 102.5, 108),
        ]
    )
    assert shallow(rows, module) == []


def test_source_shallow_case_and_parent_nonentry() -> None:
    assert_valid()
    assert parent.generate_signals({"BTC-USDT": pd.DataFrame(shallow_rows())}) == []


@pytest.mark.parametrize(
    "witness",
    [
        assert_no_countertrend,
        assert_close_conjunction,
        assert_adverse,
        assert_ttl,
    ],
)
def test_source_negative_witnesses(witness: Any) -> None:
    witness()


def test_source_sequence_requires_distinct_completed_bars() -> None:
    rows = shallow_rows()
    assert run(rows[:22]) == []
    assert run(rows[:23]) == []
    assert_valid()


def test_literal_signals_preserved_even_after_shallow_emission() -> None:
    rows = shallow_rows() + [
        bar(24, 108, 109, 100.5, 102),
        bar(25, 102, 111, 101.5, 110),
    ]
    original = parent.generate_signals({"BTC-USDT": pd.DataFrame(rows)})
    assert len(original) == 1
    result = run(rows)
    assert [s["meta"]["fidelity"]["path"] for s in result] == [
        "SHALLOW",
        "LITERAL_PARENT",
    ]
    literal = deepcopy(result[1])
    literal["identity"] = parent.IDENTITY
    literal["meta"].pop("fidelity")
    assert literal == original[0]


def test_parent_literal_only_case_exact_projection() -> None:
    rows = [bar(i) for i in range(20)] + [
        bar(20, 100, 103, 100, 102),
        bar(21, 102, 102.5, 100.5, 102),
        bar(22, 102, 104, 101.5, 103),
    ]
    original = parent.generate_signals({"BTC-USDT": pd.DataFrame(rows)})
    result = run(rows)
    assert len(result) == len(original) == 1
    result[0]["identity"] = parent.IDENTITY
    result[0]["meta"].pop("fidelity")
    assert result == original


@pytest.mark.parametrize("kind", ["gap", "segment"])
def test_gap_or_segment_cancels_shadow(kind: str) -> None:
    rows = shallow_rows()
    if kind == "segment":
        rows[23]["segment_id"] = "B"
    else:
        rows[23] = bar(24, 105, 109, 102.5, 108)
    assert run(rows) == []


def test_short_reflection_preserves_geometry() -> None:
    rows = shallow_rows()
    mirrored = deepcopy(rows)
    for old, new in zip(rows, mirrored):
        new.update(
            open=250 - old["open"],
            close=250 - old["close"],
            high=250 - old["low"],
            low=250 - old["high"],
        )
    signal = shallow(mirrored)[0]
    assert signal["side"] == -1
    assert signal["stop_price"] == 148
    assert signal["invalidation_price"] == 149


def test_available_features_are_not_backdated() -> None:
    rows = shallow_rows()
    rows[21]["available_ts_ms"] = 29 * child.TIMEFRAME_MS
    result = shallow(rows)[0]
    assert result["signal_ts_ms"] == 29 * child.TIMEFRAME_MS


def test_future_or_outcome_fields_never_change_prefix() -> None:
    rows = shallow_rows()
    expected = run(rows)
    extra = rows + [bar(24, 108, 250, 1, 150)]
    assert [
        s for s in run(extra) if s["signal_open_ts_ms"] <= rows[-1]["open_ts_ms"]
    ] == expected
    for row in rows:
        row.update(winner=True, future_profit=1e15, mfe_r=1000)
    assert run(rows) == expected


def test_one_shallow_emission_per_parent_origin() -> None:
    rows = shallow_rows() + [
        bar(24, 108, 109, 103, 106),
        bar(25, 106, 111, 104, 110),
        bar(26, 110, 112, 105, 111),
    ]
    assert len(shallow(rows)) == 1


def test_same_origin_timestamp_collision_prefers_literal() -> None:
    first = shallow(shallow_rows())[0]
    literal = deepcopy(first)
    literal["meta"]["fidelity"]["path"] = "LITERAL_PARENT"
    literal["stop_price"] = 100.5
    assert child._deduplicate([first, literal]) == [literal]
    assert child._deduplicate([literal, first]) == [literal]


def test_inside_rail_close_and_overshoot_do_not_extend_setup() -> None:
    rows = shallow_rows()
    rows[22] = bar(22, 107, 108, 100, 100.5)
    rows[23] = bar(23, 100.5, 109, 100, 108)
    assert run(rows) == []


def test_exit_translation_matches_parent_without_mutating_position() -> None:
    signal = shallow(shallow_rows())[0]
    p = {"signal": signal, "side": 1, "entry_ts_ms": 24 * child.TIMEFRAME_MS}
    snapshot = deepcopy(p)
    translated = {**p, "signal": {**signal, "identity": parent.IDENTITY}}
    closed = bar(24, 108, 109, 100, 101)
    assert child.exit_update(p, closed, pd.DataFrame()) == parent.exit_update(
        translated, closed, pd.DataFrame()
    )
    assert p == snapshot
    assert child.exit_update(p, closed, pd.DataFrame())["exit_next_open"]


def test_root_runner_signature_and_identity_guards() -> None:
    frames = {"BTC-USDT": pd.DataFrame(shallow_rows())}
    assert child.generate_signals(
        frames, costs={"BTC-USDT": 14}, identity=child.IDENTITY
    )
    with pytest.raises(ValueError, match="IDENTITY"):
        child.generate_signals(frames, identity="wrong")
    p = {"signal": {"identity": parent.IDENTITY}, "side": 1}
    with pytest.raises(ValueError, match="IDENTITY"):
        child.exit_update(p, bar(24), pd.DataFrame())


MUTATIONS = [
    (
        "if _is_shallow(state, bar, previous):",
        "if True:  # removed countertrend event",
        assert_no_countertrend,
    ),
    (
        'and bar["close"] < previous["close"]',
        "and True",
        assert_close_conjunction,
    ),
    (
        "if adverse:",
        "if False:  # removed adverse-extreme invalidation",
        assert_adverse,
    ),
    (
        'elapsed > int(parent.SPEC["setup_max_bars_from_break"])',
        "elapsed > 10000",
        assert_ttl,
    ),
    (
        "        return True, None\n    assert state.retest_low",
        '        return (True, _shallow_signal(symbol, state, bar)) if state.stage == "AWAIT_RECLAIM" else (True, None)\n    assert state.retest_low',
        assert_valid,
    ),
]


@pytest.mark.parametrize("old,new,witness", MUTATIONS)
def test_source_witness_kills_essential_rule_mutation(
    old: str,
    new: str,
    witness: Any,
) -> None:
    source_path = Path(str(child.__file__))
    original = source_path.read_text()
    assert original.count(old) == 1, "Mutation must match exactly one actual code site"
    mutated = types.ModuleType("break_source_mutant")
    mutated.__file__ = str(source_path)
    exec(
        compile(original.replace(old, new), str(source_path), "exec"), mutated.__dict__
    )
    with pytest.raises(AssertionError):
        witness(mutated)


# Independent post-implementation review cases preserve the original case file.
def review_boundary_rows(kind: str, side: int) -> list[dict[str, Any]]:
    rows = shallow_rows()
    if kind == "rail_equal":
        # A prior literal has already emitted; dedup cannot hide shallow misclassification.
        rows = [bar(i) for i in range(20)] + [
            bar(20, 100, 106, 100, 105),
            bar(21, 105, 110, 100.5, 106),
            bar(22, 106, 111, 104, 110.5),
            bar(23, 110.5, 111, 101, 106),
            bar(24, 106, 113, 102, 112),
        ]
    elif kind == "countertrend_equal":
        rows[22]["low"] = 103
        rows[23]["low"] = 103.5
    elif kind == "close_equal":
        rows[22]["close"] = 107
    elif kind == "reclaim_equal":
        rows[23]["close"] = 107.5
    elif kind == "adverse_equal":
        rows[23]["low"] = 102
    elif kind == "ttl_exact":
        rows = shallow_rows()[:22]
        rows.extend(bar(i, 107, 108, 103, 107) for i in range(22, 29))
        rows.extend([bar(29, 107, 107.5, 102, 105), bar(30, 105, 109, 102.5, 108)])
    elif kind == "inside_equal_before_arm":
        rows = shallow_rows()[:22] + [
            bar(22, 107, 108, 101, 101),
            bar(23, 101, 108, 101, 107),
            bar(24, 107, 108, 104, 107),
            bar(25, 107, 107.5, 102, 105),
            bar(26, 105, 109, 102.5, 108),
        ]
    else:
        raise AssertionError("Unknown independent review case")
    if side == -1:
        rows = [
            dict(
                row,
                open=250 - row["open"],
                close=250 - row["close"],
                high=250 - row["low"],
                low=250 - row["high"],
            )
            for row in rows
        ]
    return rows


def assert_review_boundary(kind: str, side: int, module: Any = child) -> None:
    signals = shallow(review_boundary_rows(kind, side), module)
    if kind in ("adverse_equal", "ttl_exact"):
        assert len(signals) == 1
        assert signals[0]["side"] == side
        expected_index = 30 if kind == "ttl_exact" else 23
        assert signals[0]["signal_open_ts_ms"] == expected_index * child.TIMEFRAME_MS
    else:
        assert signals == []


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize(
    "kind",
    [
        "rail_equal",
        "countertrend_equal",
        "close_equal",
        "reclaim_equal",
        "adverse_equal",
        "ttl_exact",
        "inside_equal_before_arm",
    ],
)
def test_independent_review_boundary(kind: str, side: int) -> None:
    assert_review_boundary(kind, side)


REVIEW_BOUNDARY_MUTATIONS = [
    ('bar["low"] > setup.reference', 'bar["low"] >= setup.reference', "rail_equal", 1),
    (
        'bar["high"] < setup.reference',
        'bar["high"] <= setup.reference',
        "rail_equal",
        -1,
    ),
    (
        'bar["low"] < previous["low"]',
        'bar["low"] <= previous["low"]',
        "countertrend_equal",
        1,
    ),
    (
        'bar["high"] > previous["high"]',
        'bar["high"] >= previous["high"]',
        "countertrend_equal",
        -1,
    ),
    (
        'bar["close"] < previous["close"]',
        'bar["close"] <= previous["close"]',
        "close_equal",
        1,
    ),
    (
        'bar["close"] > previous["close"]',
        'bar["close"] >= previous["close"]',
        "close_equal",
        -1,
    ),
    (
        'bar["close"] > state.retest_high',
        'bar["close"] >= state.retest_high',
        "reclaim_equal",
        1,
    ),
    (
        'bar["close"] < state.retest_low',
        'bar["close"] <= state.retest_low',
        "reclaim_equal",
        -1,
    ),
    (
        'bar["low"] < state.retest_low',
        'bar["low"] <= state.retest_low',
        "adverse_equal",
        1,
    ),
    (
        'bar["high"] > state.retest_high',
        'bar["high"] >= state.retest_high',
        "adverse_equal",
        -1,
    ),
    (
        'elapsed > int(parent.SPEC["setup_max_bars_from_break"])',
        'elapsed >= int(parent.SPEC["setup_max_bars_from_break"])',
        "ttl_exact",
        1,
    ),
    (
        'state.side * (bar["close"] - state.reference) <= 0',
        'state.side * (bar["close"] - state.reference) < 0',
        "inside_equal_before_arm",
        1,
    ),
    ('and bar["low"] < previous["low"]', "and True", "countertrend_equal", 1),
    ('and bar["high"] > previous["high"]', "and True", "countertrend_equal", -1),
    ('and bar["close"] > previous["close"]', "and True", "close_equal", -1),
    ("or inside:", "or False:", "inside_equal_before_arm", 1),
]


@pytest.mark.parametrize("old,new,kind,side", REVIEW_BOUNDARY_MUTATIONS)
def test_independent_review_kills_boundary_mutant(
    old: str, new: str, kind: str, side: int
) -> None:
    source_path = Path(str(child.__file__))
    original = source_path.read_text()
    assert original.count(old) == 1
    mutant = types.ModuleType("break_independent_boundary_mutant")
    mutant.__file__ = str(source_path)
    exec(compile(original.replace(old, new), str(source_path), "exec"), mutant.__dict__)
    with pytest.raises(AssertionError):
        assert_review_boundary(kind, side, mutant)
