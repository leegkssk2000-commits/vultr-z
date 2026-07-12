from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_forward_r_persistent_write_watch_state.py"
    spec = importlib.util.spec_from_file_location("q4r3_persistent_write_watch_state_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def test_no_event_continues() -> None:
    assert MODULE.classify_decision({"verdict": "NO_AUTHORITATIVE_OPEN_WRITE_EVENT_OBSERVED"}) == "CONTINUE"


def test_confirmed_owner_stops_with_evidence() -> None:
    assert MODULE.classify_decision({"verdict": "RUNTIME_ENTRY_WRITER_OWNER_CONFIRMED"}) == "EVIDENCE"


def test_distributed_owner_stops_with_evidence() -> None:
    assert MODULE.classify_decision({"verdict": "RUNTIME_ENTRY_WRITER_DISTRIBUTED"}) == "EVIDENCE"


def test_unresolved_event_still_stops_for_followup() -> None:
    assert MODULE.classify_decision({"verdict": "AUTHORITATIVE_WRITE_EVENT_SEEN_OWNER_UNRESOLVED"}) == "EVIDENCE"


def test_backend_unavailable_blocks() -> None:
    assert MODULE.classify_decision({"verdict": "RUNTIME_WRITE_TRACE_BACKEND_UNAVAILABLE"}) == "BLOCKED"


def test_unknown_verdict_does_not_guess() -> None:
    assert MODULE.classify_decision({"verdict": "SOMETHING_NEW"}) == "UNKNOWN"
