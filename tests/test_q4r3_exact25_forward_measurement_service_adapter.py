from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_exact25_forward_measurement_service_adapter.py"
    spec = importlib.util.spec_from_file_location("q4r3_exact25_forward_measurement_service_adapter_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def valid_gate() -> dict:
    return {
        "schema": "q4r3_exact25_forward_measurement_writer_gate_v1",
        "epoch_id": "EXACT25_EDGE_V1",
        "measurement_namespace": "EXACT25_EDGE_V1",
        "shadow_only": True,
        "write_enabled": False,
        "canary_enabled": False,
        "activation_allowed": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "historical_backfill_allowed": False,
    }


def set_valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "Q4R3_EPOCH_ID": "EXACT25_EDGE_V1",
        "Q4R3_MEASUREMENT_NAMESPACE": "EXACT25_EDGE_V1",
        "Q4R3_SHADOW_ONLY": "1",
        "Q4R3_PAPER_ENABLED": "0",
        "Q4R3_LIVE_ENABLED": "0",
        "Q4R3_ORDER_ENABLED": "0",
        "Q4R3_HISTORICAL_BACKFILL_ALLOWED": "0",
        "Q4R3_SERVICE_STAGE": "DRYRUN_ONLY",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_validate_environment_accepts_only_shadow_dryrun(monkeypatch: pytest.MonkeyPatch) -> None:
    set_valid_env(monkeypatch)
    MODULE.validate_environment()
    monkeypatch.setenv("Q4R3_LIVE_ENABLED", "1")
    with pytest.raises(RuntimeError, match="Q4R3_LIVE_ENABLED"):
        MODULE.validate_environment()


def test_validate_gate_rejects_any_write_enable() -> None:
    gate = valid_gate()
    MODULE.validate_gate(gate)
    gate["write_enabled"] = True
    with pytest.raises(RuntimeError, match="write_enabled"):
        MODULE.validate_gate(gate)


def test_validate_gate_rejects_historical_backfill() -> None:
    gate = valid_gate()
    gate["historical_backfill_allowed"] = True
    with pytest.raises(RuntimeError, match="historical_backfill_allowed"):
        MODULE.validate_gate(gate)


def test_validate_writer_pins_sha(tmp_path: Path) -> None:
    writer = tmp_path / "writer.py"
    writer.write_text("print('safe')\n", encoding="utf-8")
    expected = hashlib.sha256(writer.read_bytes()).hexdigest()
    assert MODULE.validate_writer(writer, expected) == expected
    with pytest.raises(RuntimeError, match="WRITER_SHA_MISMATCH"):
        MODULE.validate_writer(writer, "0" * 64)


def test_atomic_json_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "status.json"
    MODULE.atomic_json(path, {"state": "RUNNING_DRYRUN", "count": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "state": "RUNNING_DRYRUN",
        "count": 2,
    }


def test_status_payload_has_no_write_authority(tmp_path: Path) -> None:
    payload = MODULE.status_payload(
        state="RUNNING_DRYRUN",
        gate_path=tmp_path / "gate.json",
        writer_path=tmp_path / "writer.py",
        writer_sha256="a" * 64,
        heartbeat_count=3,
        started_at="2026-07-13T00:00:00+00:00",
    )
    assert payload["shadow_only"] is True
    assert payload["write_enabled"] is False
    assert payload["canary_enabled"] is False
    assert payload["activation_allowed"] is False
    assert payload["paper_enabled"] is False
    assert payload["live_enabled"] is False
    assert payload["order_enabled"] is False
    assert payload["historical_backfill_allowed"] is False
    assert payload["writer_invocation_count"] == 0
