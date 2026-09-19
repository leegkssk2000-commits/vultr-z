"""Independent source-first HG logic cases; fixtures are not author trades."""

from __future__ import annotations

import copy
import inspect
from typing import Any, Callable

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_fidelity_hg_v1 as hg

Event = Callable[..., tuple[int, float] | None]


def row(i: int, adx: float = 31, side: int = 1, **changes: Any) -> dict[str, Any]:
    r: dict[str, Any] = {
        "open_ts_ms": i * 1_800_000,
        "close_ts_ms": (i + 1) * 1_800_000,
        "available_ts_ms": (i + 1) * 1_800_000,
        "feature_available_ts_ms": (i + 1) * 1_800_000,
        "segment_id": "A",
        "open": 112.0,
        "high": 114.0,
        "low": 111.0,
        "close": 113.0,
        "g20": 110 + i * 0.001,
        "adx14": adx,
        "hi20": 120.0,
        "lo20": 90.0,
        "atr": 2.0,
        "regime": "TREND_DISPERSED",
        "regime_available_ts_ms": (i + 1) * 1_800_000,
        "regime_fit_end_ts_ms": -1,
        "regime_spec_sha256": "a" * 64,
    }
    for j, n in enumerate(hg.parent.LONG_GMMA):
        r[f"g{n}"] = 106 - j + i * 0.001
    r.update(changes)
    if side == -1:
        for key in ("open", "close", "g20") + tuple(
            f"g{n}" for n in hg.parent.LONG_GMMA
        ):
            r[key] = 400 - r[key]
        r["high"], r["low"] = 400 - r["low"], 400 - r["high"]
        r["hi20"], r["lo20"] = 400 - r["lo20"], 400 - r["hi20"]
    return r


def sequence(fn: Event = hg.event, adx: float = 29, side: int = 1) -> tuple[Any, Any]:
    state = hg.QualificationState()
    bars = [
        row(0, 29, side),
        row(1, 32, side),
        row(2, adx, side, low=110.0),
        row(3, adx - 1, side, low=111.0, high=116.0, close=115.0),
    ]
    outputs = [fn(state, bars[i], bars[i - 1]) for i in range(1, 4)]
    return state, outputs


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("adx", [31, 29, 24])
def test_src04_05_06_qualified_pullback_may_have_declining_adx(
    adx: float, side: int
) -> None:
    state, outputs = sequence(adx=adx, side=side)
    assert outputs[:2] == [None, None]
    assert outputs[2] == (side, 110.0 if side == 1 else 290.0)
    assert state.episode_traded
    assert state.qualified_at_ms == 2 * 1_800_000


@pytest.mark.parametrize("previous,current", [(32, 31), (29, 30), (28, 29), (31, 31)])
def test_src02_03_initial_requires_above30_and_rising(
    previous: float, current: float
) -> None:
    state = hg.QualificationState()
    assert hg.event(state, row(1, current), row(0, previous)) is None
    assert not state.qualified
    assert state.stage == 0


def test_src01_07_08_qualifier_cannot_retroactively_count_touch() -> None:
    state = hg.QualificationState()
    before = row(0, 29, low=109.0)
    touching = row(1, 32, low=109.0)
    assert hg.event(state, touching, before) is None
    assert state.qualified and state.stage == 0
    away = row(2, 31, low=111.0)
    assert hg.event(state, away, touching) is None
    assert state.stage == 0
    assert hg.event(state, row(3, 30, high=117.0, close=116.0), away) is None
    assert not state.episode_traded


def test_src10_consumed_episode_reentry_gates_and_renewal_bar_preserved() -> None:
    state, _ = sequence()
    before = row(3, 29)
    blocked = row(4, 29, high=121)
    assert hg.event(state, blocked, before) is None
    assert state.episode_traded
    renewed = row(5, 31, high=121)
    assert hg.event(state, renewed, blocked) is None
    assert not state.episode_traded and not state.qualified
    assert state.stage == 0
    assert hg.event(state, row(6, 32), renewed) is None
    assert state.qualified and state.stage == 0


def test_consumed_below25_resets_but_unconsumed_below25_does_not() -> None:
    state, _ = sequence()
    assert hg.event(state, row(4, 24), row(3, 29)) is None
    assert not state.episode_traded and not state.qualified and state.side == 0
    state, outputs = sequence(adx=24)
    assert outputs[-1] is not None


def test_direction_flip_after_unfavorable_slope_pause_preserved() -> None:
    state = hg.QualificationState(side=1, qualified=True, stage=1)
    previous = row(0, 29, side=-1)
    paused = row(1, 31, side=-1)
    paused["g20"] = previous["g20"] + 1
    assert hg.event(state, paused, previous) is None
    assert state.side == 1 and state.qualified and state.stage == 1
    opposite = row(2, 32, side=-1)
    assert hg.event(state, opposite, paused) is None
    assert state.side == -1 and state.qualified and state.stage == 0


def prepared() -> pd.DataFrame:
    bars = [row(i, 29) for i in range(126)]
    bars[121] = row(121, 32)
    bars[122] = row(122, 29, low=110.0)
    bars[123] = row(123, 28, high=116.0, close=115.0)
    return pd.DataFrame(bars)


def test_src09_event_consumed_before_regime_and_cost_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    x = prepared()
    x.loc[123, "regime"] = "RANGE_MIXED"
    x.loc[124, ["high", "close"]] = [118, 117]
    states: list[hg.QualificationState] = []
    cls = hg.QualificationState

    def factory() -> hg.QualificationState:
        s = cls()
        states.append(s)
        return s

    monkeypatch.setattr(hg, "QualificationState", factory)
    monkeypatch.setattr(hg.parent, "enriched_segments", lambda frame: [frame])
    assert hg.generate_signals({"BTC-USDT": x}, {"BTC-USDT": 14}) == []
    assert states[-1].episode_traded
    x.loc[123, "regime"] = "TREND_DISPERSED"
    signals = hg.generate_signals({"BTC-USDT": x}, {"BTC-USDT": 14})
    assert len(signals) == 1
    signal = signals[0]
    assert signal["signal_open_ts_ms"] == 123 * 1_800_000
    assert signal["meta"]["qualified_at_ms"] < signal["signal_ts_ms"]
    assert hg.entry_update(signal, 10000)["reject"] is True


def test_src11_generator_resets_each_real_gap_segment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    x = prepared()
    x.loc[123:, "segment_id"] = "B"
    seen: list[int] = []
    cls = hg.QualificationState

    def factory() -> hg.QualificationState:
        s = cls()
        seen.append(id(s))
        return s

    monkeypatch.setattr(hg, "QualificationState", factory)
    assert hg.generate_signals({"BTC-USDT": x}, {"BTC-USDT": 14}) == []
    assert len(seen) == 2 and len(set(seen)) == 2


def test_src12_future_rows_do_not_change_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hg.parent, "enriched_segments", lambda frame: [frame])
    x = prepared()
    expected = hg.generate_signals({"BTC-USDT": x.iloc[:124]}, {"BTC-USDT": 14})
    assert len(expected) == 1
    x.loc[124:, ["open", "high", "low", "close"]] = [100, 10000, 1, 9999]
    actual = hg.generate_signals({"BTC-USDT": x}, {"BTC-USDT": 14})
    assert [s for s in actual if s["signal_open_ts_ms"] <= 123 * 1_800_000] == expected


def test_entry_and_lifecycle_delegate_exactly_to_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hg.parent, "enriched_segments", lambda frame: [frame])
    signal = hg.generate_signals({"BTC-USDT": prepared()}, {"BTC-USDT": 14})[0]
    bound = {**signal, "identity": hg.PARENT}
    for price in (100, 10000):
        assert hg.entry_update(signal, price) == hg.parent.entry_update(bound, price)
    assert signal["identity"] == hg.IDENTITY
    history = prepared().iloc[:3].copy()
    history[["open", "high", "low", "close"]] = [100, 103.5, 100, 101]
    for mfe, held, remaining in [
        (0.39, 5, 1.0),
        (1.0, 2, 1.0),
        (3.5, 3, 1.0),
        (4.0, 5, 0.9),
    ]:
        pos = {
            "signal": signal,
            "entry_ts_ms": 0,
            "entry_price": 100,
            "initial_risk": 1,
            "side": 1,
            "stop_price": 99,
            "mfe_R": mfe,
            "hold_bars": held,
            "remaining": remaining,
        }
        original = copy.deepcopy(pos)
        bar = history.iloc[-1].to_dict()
        expected = hg.parent.exit_update({**pos, "signal": bound}, bar, history)
        assert hg.exit_update(pos, bar, history) == expected
        assert pos == original


def test_identity_guard_cannot_route_squeeze_or_td075() -> None:
    for identity in (hg.parent.KELTNER_TD075, hg.parent.SQUEEZE_PARENT):
        with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
            hg.entry_update({"identity": identity}, 100)


def mutant(old: str, new: str) -> Event:
    source = inspect.getsource(hg.event)
    assert source.count(old) == 1
    namespace = dict(vars(hg))
    exec(
        compile(source.replace(old, new), "<HG_LOGIC_MUTATION_ONLY>", "exec"), namespace
    )
    return namespace["event"]


@pytest.mark.parametrize(
    "old,new,previous,current",
    [
        (' and row["adx14"] > previous["adx14"]', "", 32, 31),
        ('if row["adx14"] > 30 and', 'if row["adx14"] >= 30 and', 29, 30),
    ],
)
def test_mutations_initial_predicate_are_killed(
    old: str, new: str, previous: float, current: float
) -> None:
    fn = mutant(old, new)
    state = hg.QualificationState()
    fn(state, row(1, current), row(0, previous))
    with pytest.raises(AssertionError):
        assert not state.qualified


def test_mutation_later30_gate_is_killed() -> None:
    fn = mutant(
        "    if not state.qualified:",
        '    if state.qualified and row["adx14"] < 30:\n        return None\n'
        "    if not state.qualified:",
    )
    _, outputs = sequence(fn=fn)
    with pytest.raises(AssertionError):
        assert outputs[-1] == (1, 110.0)


def test_mutation_qualifier_touch_time_collapse_is_killed() -> None:
    fn = mutant(
        '            state.qualified_at_ms = int(row.get("available_ts_ms", 0))\n'
        "        return None\n    if state.stage == 0:",
        '            state.qualified_at_ms = int(row.get("available_ts_ms", 0))\n'
        "    if state.stage == 0:",
    )
    state = hg.QualificationState()
    fn(state, row(1, 32, low=109.0), row(0, 29))
    with pytest.raises(AssertionError):
        assert state.stage == 0
