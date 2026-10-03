"""Synthetic fault injection for checkpoint exception priority and writer release."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest


ADAPTER_PATH = Path(__file__).resolve().parents[1] / "research/campaigns/scalp7_20261003/kp_validation_prep_v1/adapter.py"
spec = importlib.util.spec_from_file_location("kp30_checkpoint_exit_adapter", ADAPTER_PATH)
assert spec is not None and spec.loader is not None
prep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)

BASE = 10 * prep.TF_MS


def config(tmp_path: Path) -> dict[str, Any]:
    return prep.build_candidate_config(tmp_path / prep.NAMESPACE, t0_ms=BASE,
        window_end_ms=BASE + 2 * prep.TF_MS,
        runtime_identity="KP30_PREP_SYNTHETIC_CHECKPOINT_EXIT_V1",
        reference_costs_bps={"BTC-USDT": 8.0})


def raise_from_body(cp: Any, original: BaseException) -> tuple[BaseException, TracebackType]:
    body_traceback = None
    try:
        with cp:
            try:
                raise original
            except BaseException:
                body_traceback = original.__traceback__
                raise
    except BaseException as propagated:
        assert body_traceback is not None
        return propagated, body_traceback
    raise AssertionError("checkpoint suppressed the body exception")


@pytest.mark.parametrize("exception_type", [RuntimeError, KeyboardInterrupt, SystemExit])
def test_interrupt_save_failure_preserves_original_and_releases_retained_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exception_type: type[BaseException],
) -> None:
    cfg = config(tmp_path)
    cp = prep.PrepCheckpoint(cfg)
    previous = copy.deepcopy(cp.state)
    raw = (cp.out / "STATE.json").read_bytes()
    original = exception_type("original processing failure")

    def fail_write(*args: Any, **kwargs: Any) -> None:
        raise OSError("synthetic disk write failure")

    with monkeypatch.context() as patch:
        patch.setattr(prep, "atomic_json", fail_write)
        propagated, body_traceback = raise_from_body(cp, original)

    assert propagated is original
    assert propagated.__traceback__ is body_traceback
    assert propagated.__notes__ == ["CHECKPOINT_INTERRUPT_SAVE_FAILED: OSError: synthetic disk write failure"]
    assert cp.lock.closed
    assert (cp.out / "STATE.json").read_bytes() == raw
    assert cp.state["paper_state"] == previous["paper_state"]
    assert cp.state["processed_events"] == previous["processed_events"]
    with pytest.raises(prep.PrepError, match="EXPLICIT_RECOVERY_REQUIRED"):
        prep.PrepCheckpoint(cfg)
    # cp remains referenced in this process: reacquisition must not rely on GC.
    with prep.PrepCheckpoint(cfg, recover=True) as resumed:
        assert cp.lock.closed
        assert resumed.state["history"][-1] == {"kind": "EXPLICIT_RECOVERY", "prior_status": "STARTED"}
        assert resumed.state["paper_state"] == previous["paper_state"]
        assert resumed.state["processed_events"] == previous["processed_events"]
        assert resumed.snapshot()["attempt_count"] == 1
        assert resumed.snapshot()["consumed_full_credit"] == 0


@pytest.mark.parametrize("exception_type,status", [
    (RuntimeError, "FAILED"), (KeyboardInterrupt, "INTERRUPTED"), (SystemExit, "FAILED"),
])
def test_durable_failure_receipt_and_explicit_recovery_keep_original_exception(
    tmp_path: Path, exception_type: type[BaseException], status: str,
) -> None:
    cfg = config(tmp_path)
    cp = prep.PrepCheckpoint(cfg)
    cp.apply_synthetic("committed-before-failure", now_ms=BASE + 1, quotes={}, frames={})
    previous = copy.deepcopy(cp.state)
    original = exception_type("original processing failure")
    propagated, body_traceback = raise_from_body(cp, original)
    assert propagated is original
    assert propagated.__traceback__ is body_traceback
    assert not getattr(propagated, "__notes__", [])
    assert cp.lock.closed
    durable = json.loads((cp.out / "STATE.json").read_bytes())
    assert durable["attempt_status"] == status
    assert durable["history"][-1] == {"kind": status, "reason": str(original)}
    assert durable["paper_state"] == previous["paper_state"]
    assert durable["processed_events"] == previous["processed_events"]
    with pytest.raises(prep.PrepError, match="EXPLICIT_RECOVERY_REQUIRED"):
        prep.PrepCheckpoint(cfg)
    with prep.PrepCheckpoint(cfg, recover=True) as resumed:
        assert resumed.state["history"][-1] == {"kind": "EXPLICIT_RECOVERY", "prior_status": status}
        assert resumed.state["history"][-2] == durable["history"][-1]
        assert resumed.state["paper_state"] == previous["paper_state"]
        assert resumed.state["processed_events"] == previous["processed_events"]
        assert resumed.snapshot()["attempt_count"] == 1
        assert resumed.snapshot()["consumed_full_credit"] == 0


def test_normal_exit_releases_writer_without_creating_failure_receipt(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    with prep.PrepCheckpoint(cfg) as cp:
        cp.apply_synthetic("committed", now_ms=BASE + 1, quotes={}, frames={})
        raw = (cp.out / "STATE.json").read_bytes()
        with pytest.raises(prep.PrepError, match="KP_SINGLE_WRITER_LOCK_CONFLICT"):
            prep.PrepCheckpoint(cfg, recover=True)
    assert cp.lock.closed
    assert (cp.out / "STATE.json").read_bytes() == raw
    cp.close()  # idempotent cleanup with the original reference retained
    with prep.PrepCheckpoint(cfg, recover=True) as resumed:
        assert resumed.state["processed_events"] == cp.state["processed_events"]
        assert resumed.state["history"][-1]["prior_status"] == "STARTED"


def test_event_and_interrupt_write_failures_do_not_advance_durable_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = config(tmp_path)
    cp = prep.PrepCheckpoint(cfg)
    cp.apply_synthetic("committed", now_ms=BASE + 1, quotes={}, frames={})
    previous = copy.deepcopy(cp.state)
    raw = (cp.out / "STATE.json").read_bytes()
    write_errors: list[BaseException] = []
    original_traceback = None

    def fail_write(*args: Any, **kwargs: Any) -> None:
        error = OSError("synthetic disk write failure")
        write_errors.append(error)
        raise error

    with monkeypatch.context() as patch:
        patch.setattr(prep, "atomic_json", fail_write)
        try:
            with cp:
                try:
                    cp.apply_synthetic("must-not-commit", now_ms=BASE + 2, quotes={}, frames={})
                except OSError as error:
                    original_traceback = error.__traceback__
                    raise
        except OSError as propagated:
            assert propagated is write_errors[0]
            assert propagated.__traceback__ is original_traceback
            assert propagated.__notes__ == ["CHECKPOINT_INTERRUPT_SAVE_FAILED: OSError: synthetic disk write failure"]
        else:
            raise AssertionError("write failure was suppressed")

    assert len(write_errors) == 2
    assert cp.lock.closed
    assert cp.state["processed_events"] == previous["processed_events"]
    assert cp.state["paper_state"] == previous["paper_state"]
    assert (cp.out / "STATE.json").read_bytes() == raw
    with prep.PrepCheckpoint(cfg, recover=True) as resumed:
        assert resumed.state["processed_events"] == previous["processed_events"]
        assert resumed.state["paper_state"]["last_poll_ms"] == BASE + 1
        assert "must-not-commit" not in resumed.state["processed_events"]
        assert resumed.snapshot()["consumed_full_credit"] == 0


@pytest.mark.parametrize("body_failure", [False, True])
def test_unlock_failure_closes_descriptor_and_preserves_primary_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body_failure: bool,
) -> None:
    cfg = config(tmp_path)
    cp = prep.PrepCheckpoint(cfg)
    real_flock = prep.fcntl.flock

    def fail_unlock(fd: int, operation: int) -> None:
        if operation == prep.fcntl.LOCK_UN:
            raise OSError("synthetic unlock failure")
        real_flock(fd, operation)

    with monkeypatch.context() as patch:
        patch.setattr(prep.fcntl, "flock", fail_unlock)
        if body_failure:
            original = RuntimeError("original processing failure")
            propagated, body_traceback = raise_from_body(cp, original)
            assert propagated is original
            assert propagated.__traceback__ is body_traceback
            assert propagated.__notes__ == ["CHECKPOINT_CLOSE_FAILED: OSError: synthetic unlock failure"]
        else:
            with pytest.raises(OSError, match="synthetic unlock failure"):
                with cp:
                    pass
    assert cp.lock.closed
    with prep.PrepCheckpoint(cfg, recover=True) as resumed:
        assert resumed.snapshot()["attempt_count"] == 1
        assert resumed.snapshot()["consumed_full_credit"] == 0


def test_simultaneous_save_and_unlock_failures_keep_original_and_both_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = config(tmp_path)
    cp = prep.PrepCheckpoint(cfg)
    raw = (cp.out / "STATE.json").read_bytes()
    real_flock = prep.fcntl.flock

    def fail_write(*args: Any, **kwargs: Any) -> None:
        raise OSError("synthetic disk write failure")

    def fail_unlock(fd: int, operation: int) -> None:
        if operation == prep.fcntl.LOCK_UN:
            raise OSError("synthetic unlock failure")
        real_flock(fd, operation)

    original = KeyboardInterrupt("original processing failure")
    with monkeypatch.context() as patch:
        patch.setattr(prep, "atomic_json", fail_write)
        patch.setattr(prep.fcntl, "flock", fail_unlock)
        propagated, body_traceback = raise_from_body(cp, original)
    assert propagated is original
    assert propagated.__traceback__ is body_traceback
    assert propagated.__notes__ == [
        "CHECKPOINT_INTERRUPT_SAVE_FAILED: OSError: synthetic disk write failure",
        "CHECKPOINT_CLOSE_FAILED: OSError: synthetic unlock failure",
    ]
    assert cp.lock.closed
    assert (cp.out / "STATE.json").read_bytes() == raw
    with prep.PrepCheckpoint(cfg, recover=True) as resumed:
        assert resumed.state["history"][-1]["prior_status"] == "STARTED"
