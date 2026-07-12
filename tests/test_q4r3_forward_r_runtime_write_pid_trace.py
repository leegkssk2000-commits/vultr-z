from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_forward_r_runtime_write_pid_trace.py"
    spec = importlib.util.spec_from_file_location("q4r3_runtime_write_pid_trace_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def targets():
    return [{"path": "/home/z/z/runtime/paper_order_ledger_state.json", "basename": "paper_order_ledger_state.json"}]


def test_path_matches_exact_and_atomic_tmp() -> None:
    assert MODULE.path_matches_target("/home/z/z/runtime/paper_order_ledger_state.json", targets()) == "paper_order_ledger_state.json"
    assert MODULE.path_matches_target("/home/z/z/runtime/paper_order_ledger_state.json.tmp", targets()) == "paper_order_ledger_state.json"
    assert MODULE.path_matches_target("/home/z/z/runtime/other.json", targets()) is None


def test_parse_audit_event() -> None:
    text = '''
type=SYSCALL msg=audit(1783840000.123:456): arch=c000003e syscall=openat success=yes exit=3 ppid=100 pid=200 comm="python3" exe="/usr/bin/python3" key="q4r3r_1"
type=PATH msg=audit(1783840000.123:456): item=0 name="/home/z/z/runtime/paper_order_ledger_state.json.tmp" inode=123 nametype=CREATE
'''
    events = MODULE.parse_audit_events(text)
    assert len(events) == 1
    assert events[0]["serial"] == "456"
    assert events[0]["pid"] == "200"
    assert events[0]["paths"] == ["/home/z/z/runtime/paper_order_ledger_state.json.tmp"]


def test_decision_confirmed_audit_owner() -> None:
    trace = {
        "backend": "auditd",
        "events": [
            {
                "owner_identity": "unit:z-worker.service|script:/home/z/z/backend/engine/tv_worker.py",
                "matched_target_basenames": ["paper_order_ledger_state.json"],
            }
        ],
    }
    decision = MODULE.decide(trace, targets(), {"prior_stable_id_join_rate_pct": 82.068})
    assert decision["verdict"] == "RUNTIME_ENTRY_WRITER_OWNER_CONFIRMED"
    assert decision["action"] == "HOLD"


def test_decision_distributed_owner() -> None:
    trace = {
        "backend": "auditd",
        "events": [
            {"owner_identity": "unit:a.service", "matched_target_basenames": ["a.json"]},
            {"owner_identity": "unit:b.service", "matched_target_basenames": ["b.json"]},
        ],
    }
    decision = MODULE.decide(trace, targets(), {})
    assert decision["verdict"] == "RUNTIME_ENTRY_WRITER_DISTRIBUTED"


def test_decision_no_event_is_not_failure() -> None:
    decision = MODULE.decide({"backend": "auditd", "events": []}, targets(), {})
    assert decision["verdict"] == "NO_AUTHORITATIVE_OPEN_WRITE_EVENT_OBSERVED"
    assert decision["action"] == "HOLD"


def test_decision_backend_unavailable_is_hold() -> None:
    decision = MODULE.decide({"backend": "unavailable", "events": []}, targets(), {})
    assert decision["verdict"] == "RUNTIME_WRITE_TRACE_BACKEND_UNAVAILABLE"
    assert decision["action"] == "HOLD"
