"""Source cases are artificial logic fixtures, never author trades or economics."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from backend.research.rebuild import scalp7_fidelity_rsi_v1 as r
from backend.research.rebuild import scalp7_materials_program_v2 as parent

CASES_PATH = (
    Path(__file__).resolve().parents[1]
    / "research/campaigns/scalp7_20260917/source_fidelity_v1"
    / "audits/SOURCE_EXPECTED_CASES_RSI.json"
)
CASES = json.loads(CASES_PATH.read_text())


def observed(values: Sequence[float]) -> list[dict[str, Any]]:
    state = r.OscillatorState()
    output = []
    for index, value in enumerate(values):
        event = r.oscillator_step(state, value, index)
        if event is not None:
            output.append(
                {
                    "index": index,
                    "side": event["side"],
                    "pivots": [pivot["rsi"] for pivot in event["pivots"]],
                }
            )
    return output


@pytest.mark.parametrize("case", CASES["cases"], ids=lambda case: case["id"])
def test_source_expected_case(case: dict[str, Any]) -> None:
    assert observed(case["rsi"]) == case["expected"]


def test_cases_were_frozen_and_source_is_explicit() -> None:
    assert hashlib.sha256(CASES_PATH.read_bytes()).hexdigest() == r.SOURCE_CASE_SHA256
    assert CASES["identity"] == r.IDENTITY
    assert CASES["parent_identity"] == r.PARENT_IDENTITY
    assert CASES["fixture_type"].startswith("ARTIFICIAL_LOGIC_ONLY")


def test_stage_expiry() -> None:
    values = [45, 38, 42] + [42] * 9 + [47, 43, 41, 44, 48]
    assert observed(values) == []


def test_pattern_consumed_once_and_nonfinite_resets() -> None:
    values = [45, 38, 42, 47, 43, 41, 44, 48, 49, 50, 51]
    assert len(observed(values)) == 1
    assert observed([45, 38, 42, 47, float("nan"), 41, 44, 48]) == []


def prepared_fixture() -> pd.DataFrame:
    """Inject named RSI values only to test adapter wiring, not RSI economics."""
    count = 112
    times = np.arange(count, dtype=np.int64) * r.TF_MS
    rsi = [50.0] * 101 + [45, 38, 42, 47, 43, 41, 44, 48, 49, 50, 51]
    return pd.DataFrame(
        {
            "open_ts_ms": times,
            "close_ts_ms": times + r.TF_MS,
            "available_ts_ms": times + r.TF_MS,
            "_feature_available_ts_ms": times + r.TF_MS,
            "segment_id": "A",
            "_local_segment": 1,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "atr": 2.0,
            "ema21": 100.0,
            "ema55": 100.0,
            "ema100": 100.0,
            "rsi": rsi,
            "macd_hist": 0.0,
            "hi20": 102.0,
            "lo20": 98.0,
        }
    )


def test_adapter_uses_later_regime_bar_and_parent_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = prepared_fixture()
    monkeypatch.setattr(parent, "_prepare", lambda data: data.copy())
    signals = r.generate_signals({"BTC-USDT": frame}, identity=r.IDENTITY)
    assert len(signals) == 1
    signal = signals[0]
    assert signal["signal_open_ts_ms"] == 109 * r.TF_MS
    assert signal["signal_ts_ms"] == 110 * r.TF_MS
    assert signal["meta"]["oscillator_event"]["oscillator_break_index"] == 108
    assert signal["stop_price"] == 98.2
    assert signal["take_profit_r"] == parent.PARAMS["rsi_swing_fail"]["target_r"]
    assert signal["max_hold_bars"] == parent.PARAMS["rsi_swing_fail"]["max_hold"]
    assert signal["meta"]["order"] == signal["meta"]["live"] == "BLOCKED"
    frame.loc[109, "ema21"] = 103.0
    delayed = r.generate_signals({"BTC-USDT": frame})[0]
    assert delayed["signal_open_ts_ms"] == 110 * r.TF_MS


def test_pending_regime_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = prepared_fixture()
    # Extend the pending period with valid completed bars, retaining no new signal.
    extension = pd.concat([frame, pd.concat([frame.iloc[-1:]] * 12)]).reset_index(
        drop=True
    )
    extension["open_ts_ms"] = np.arange(len(extension), dtype=np.int64) * r.TF_MS
    extension["close_ts_ms"] = extension.open_ts_ms + r.TF_MS
    extension["_feature_available_ts_ms"] = extension.close_ts_ms
    extension.loc[109:117, "ema21"] = 103.0
    monkeypatch.setattr(parent, "_prepare", lambda data: data.copy())
    assert r.generate_signals({"BTC-USDT": extension}) == []


def real_feature_fixture(count: int = 450) -> pd.DataFrame:
    rng = np.random.default_rng(20260917)
    close = 100 + np.cumsum(rng.normal(0, 0.28, count))
    opening = np.r_[close[0], close[:-1]]
    times = np.arange(count, dtype=np.int64) * r.TF_MS
    return pd.DataFrame(
        {
            "open_ts_ms": times,
            "close_ts_ms": times + r.TF_MS,
            "available_ts_ms": times + r.TF_MS,
            "segment_id": "A",
            "open": opening,
            "high": np.maximum(opening, close) + 0.15,
            "low": np.minimum(opening, close) - 0.15,
            "close": close,
        }
    )


def test_actual_prepare_prefix_future_and_availability() -> None:
    frame = real_feature_fixture()
    original = r.generate_signals({"BTC-USDT": frame})
    assert original
    prefix = r.generate_signals({"BTC-USDT": frame.iloc[:300]})
    assert prefix == [s for s in original if s["signal_open_ts_ms"] < 300 * r.TF_MS]
    frame.loc[300:, ["open", "high", "low", "close"]] *= 2
    altered = r.generate_signals({"BTC-USDT": frame})
    assert prefix == [s for s in altered if s["signal_open_ts_ms"] < 300 * r.TF_MS]
    assert all(
        signal["signal_ts_ms"] >= signal["signal_open_ts_ms"] + r.TF_MS
        for signal in original
    )
    assert all(
        signal["meta"]["oscillator_event"]["oscillator_break_available_ts_ms"]
        <= signal["signal_ts_ms"]
        for signal in original
    )


@pytest.mark.parametrize("declared_segment", [False, True])
def test_gap_and_segment_reset(declared_segment: bool) -> None:
    frame = real_feature_fixture()
    if declared_segment:
        frame.loc[225:, "segment_id"] = "B"
    else:
        for column in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
            frame.loc[225:, column] += r.TF_MS
    signals = r.generate_signals({"BTC-USDT": frame})
    gap = int(frame.iloc[225].open_ts_ms)
    assert not [
        signal
        for signal in signals
        if gap <= signal["signal_open_ts_ms"] < gap + 101 * r.TF_MS
    ]


@pytest.mark.parametrize("hold,mfe", [(4, 0.2), (5, 0.2), (5, 0.6), (18, 1.1)])
def test_lifecycle_delegates_control_without_mutation(hold: int, mfe: float) -> None:
    position: dict[str, Any] = {
        "signal": {
            "identity": r.IDENTITY,
            "invalidation_price": 100.0,
            "meta": {"entry_atr": 2.0},
        },
        "side": 1,
        "hold_bars": hold,
        "mfe_R": mfe,
        "stop_price": 98.2,
    }
    original = copy.deepcopy(position)
    control = copy.deepcopy(position)
    control["signal"]["identity"] = r.PARENT_IDENTITY
    assert r.exit_update(
        position, {"close": 99.0}, pd.DataFrame()
    ) == parent.exit_update(control, {"close": 99.0}, pd.DataFrame())
    assert position == original


def test_unknown_identity_rejected() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_RSI"):
        r.generate_signals({}, identity=r.PARENT_IDENTITY)
    with pytest.raises(ValueError, match="UNKNOWN_RSI"):
        r.exit_update({"signal": {"identity": r.PARENT_IDENTITY}}, {}, pd.DataFrame())


@pytest.mark.parametrize(
    "old,new",
    [
        ("third.value > first.value", "True"),
        ("third.value < first.value", "True"),
        ("value > middle.value", "value >= middle.value"),
        ("third.value > first.value", "third.value >= first.value"),
        ("value < middle.value", "value <= middle.value"),
        ("third.value < first.value", "third.value <= first.value"),
        ('kinds == ("LOW", "HIGH", "LOW")', 'kinds == ("HIGH", "LOW", "HIGH")'),
    ],
)
def test_source_case_suite_kills_condition_mutants(
    old: str, new: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = inspect.getsource(r._failure_side)
    assert old in source
    namespace: dict[str, Any] = dict(vars(r))
    exec(compile(source.replace(old, new), "<logic-only-mutant>", "exec"), namespace)
    monkeypatch.setattr(r, "_failure_side", namespace["_failure_side"])
    failures = [
        case["id"]
        for case in CASES["cases"]
        if observed(case["rsi"]) != case["expected"]
    ]
    assert failures, "Source oracle failed to kill essential-condition mutation"


def test_source_case_suite_kills_slope_only_mutant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def slope_only(state: r.OscillatorState, value: float, index: int) -> Any:
        last = state.last_rsi
        state.last_rsi = value
        if math_isfinite(last) and value > last:
            return {"side": 1, "pivots": [], "oscillator_break_index": index}
        return None

    monkeypatch.setattr(r, "oscillator_step", slope_only)
    case = next(c for c in CASES["cases"] if c["id"] == "RSI_SOURCE_SLOPE_ONLY_REJECT")
    assert observed(case["rsi"]) != case["expected"]


def math_isfinite(value: float) -> bool:
    return bool(np.isfinite(value))


def test_stage_expiry_mutant_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    source = inspect.getsource(r.oscillator_step)
    needle = "index - state.since > STAGE_TTL"
    assert needle in source
    namespace: dict[str, Any] = dict(vars(r))
    exec(compile(source.replace(needle, "False"), "<expiry-mutant>", "exec"), namespace)
    monkeypatch.setattr(r, "oscillator_step", namespace["oscillator_step"])
    values = [45, 38, 42] + [42] * 9 + [47, 43, 41, 44, 48]
    assert observed(
        values
    ), "Removing expiry must violate the no-event source adapter case"


def test_gap_state_reset_mutant_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    first = prepared_fixture().iloc[:106].copy()
    second = prepared_fixture().iloc[:107].copy()
    second.loc[101:106, "rsi"] = [43, 41, 44, 48, 49, 50]
    second["_local_segment"] = 2
    second["segment_id"] = "B"
    for column in (
        "open_ts_ms",
        "close_ts_ms",
        "available_ts_ms",
        "_feature_available_ts_ms",
    ):
        second[column] += 107 * r.TF_MS
    frame = pd.concat([first, second]).reset_index(drop=True)
    monkeypatch.setattr(parent, "_prepare", lambda data: data.copy())
    assert r.generate_signals({"BTC-USDT": frame}) == []
    source = inspect.getsource(r.generate_signals)
    needle = "state = OscillatorState()"
    assert needle in source
    namespace: dict[str, Any] = dict(vars(r), shared_state=r.OscillatorState())
    exec(
        compile(source.replace(needle, "state = shared_state"), "<gap-mutant>", "exec"),
        namespace,
    )
    assert namespace["generate_signals"](
        {"BTC-USDT": frame}
    ), "A state shared across gaps must violate this no-event oracle"


# Independently derived adapter boundary cases; never economic samples.
def assert_review_adapter_boundary(kind: str) -> None:
    if kind == "oscillator_ttl":
        prefix = [45, 38, 42, 47, 43, 41, 44]
        assert observed(prefix + [44] * 7 + [48]) == [
            {"index": 14, "side": 1, "pivots": [38, 47, 41]}
        ]
        assert observed(prefix + [44] * 8 + [48]) == []
        return
    frame = prepared_fixture()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(parent, "_prepare", lambda data: data.copy())
        if kind == "regime_equal":
            frame.loc[109, "ema21"] = 103.0
            frame.loc[109, "atr"] = 2.5
            signal = r.generate_signals({"BTC-USDT": frame})[0]
            assert signal["signal_open_ts_ms"] == 109 * r.TF_MS
        elif kind == "pending_ttl":
            frame = pd.concat([frame, pd.concat([frame.iloc[-1:]] * 12)]).reset_index(
                drop=True
            )
            frame["open_ts_ms"] = np.arange(len(frame), dtype=np.int64) * r.TF_MS
            for column in (
                "close_ts_ms",
                "available_ts_ms",
                "_feature_available_ts_ms",
            ):
                frame[column] = frame.open_ts_ms + r.TF_MS
            frame.loc[109:115, "ema21"] = 103.0
            signals = r.generate_signals({"BTC-USDT": frame})
            assert len(signals) == 1
            assert signals[0]["signal_open_ts_ms"] == 116 * r.TF_MS
            frame.loc[116, "ema21"] = 103.0
            assert r.generate_signals({"BTC-USDT": frame}) == []
        elif kind == "pending_gap":
            first = frame.iloc[:109].copy()
            second = frame.iloc[:104].copy()
            second["rsi"] = 50.0
            second["_local_segment"] = 2
            second["segment_id"] = "B"
            for column in (
                "open_ts_ms",
                "close_ts_ms",
                "available_ts_ms",
                "_feature_available_ts_ms",
            ):
                second[column] += 110 * r.TF_MS
            joined = pd.concat([first, second]).reset_index(drop=True)
            assert r.generate_signals({"BTC-USDT": joined}) == []
        else:
            raise AssertionError("Unknown independent review case")


@pytest.mark.parametrize(
    "kind", ["oscillator_ttl", "pending_ttl", "regime_equal", "pending_gap"]
)
def test_independent_review_adapter_boundary(kind: str) -> None:
    assert_review_adapter_boundary(kind)


@pytest.mark.parametrize(
    "kind", ["oscillator_ttl", "pending_ttl", "regime_equal", "pending_gap"]
)
def test_independent_review_kills_adapter_boundary_mutant(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    function: Any = (
        r.oscillator_step if kind == "oscillator_ttl" else r.generate_signals
    )
    source = inspect.getsource(function)
    if kind == "oscillator_ttl":
        old, new = "index - state.since > STAGE_TTL", "index - state.since >= STAGE_TTL"
    elif kind == "pending_ttl":
        old = 'index - int(pending["oscillator_break_index"]) > STAGE_TTL'
        new = 'index - int(pending["oscillator_break_index"]) >= STAGE_TTL'
    elif kind == "regime_equal":
        old, new = "flat <= 1.2", "flat < 1.2"
    else:
        old = '        for _, group in prepared.groupby("_local_segment", sort=False):'
        new = "        pending: dict[str, Any] | None = None\n" + old
        inner = "            pending: dict[str, Any] | None = None\n"
        assert source.count(inner) == 1
        source = source.replace(inner, "")
    assert source.count(old) == 1
    namespace: dict[str, Any] = dict(vars(r))
    exec(
        compile(source.replace(old, new), "<review-boundary-mutant>", "exec"), namespace
    )
    monkeypatch.setattr(r, function.__name__, namespace[function.__name__])
    with pytest.raises(AssertionError):
        assert_review_adapter_boundary(kind)
