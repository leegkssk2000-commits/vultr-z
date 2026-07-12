from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


LOADER = load_module(
    "q4r3_shadow_loader_test_module",
    ROOT / "artifacts/q4r3_exact25_shadow_binding/backend/engine/q4r3_exact25_shadow_manifest_loader.py",
)
BINDER = load_module(
    "q4r3_shadow_binder_test_module",
    ROOT / "tools/q4r3_exact25_shadow_only_sidecar_staged_bind.py",
)


def safe_binding() -> dict:
    return {
        "schema": "q4r3_exact25_shadow_binding_v1",
        "epoch_id": "EXACT25_EDGE_V1",
        "preexisting_data_label": "PRE_EXACT25",
        "forward_rows_only": True,
        "historical_r_backfill_allowed": False,
        "shadow_enabled": True,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "write_enabled": False,
        "canary_enabled": False,
        "dynamic_fallback_allowed": False,
        "authoritative_lifecycle_writer": "tools/q4r3_vwap_mfe_mae_capture_sidecar.py",
        "secondary_close_writer_mode": "OBSERVER_ONLY_NOT_BOUND",
    }


def test_binding_config_is_shadow_only_and_dryrun_only() -> None:
    LOADER.validate_binding_config(safe_binding())
    for key in ("paper_enabled", "live_enabled", "order_enabled", "write_enabled", "canary_enabled"):
        unsafe = safe_binding()
        unsafe[key] = True
        with pytest.raises(ValueError, match="UNSAFE_BINDING_FLAG"):
            LOADER.validate_binding_config(unsafe)


def test_dynamic_fallback_and_wrong_writer_are_rejected() -> None:
    fallback = safe_binding()
    fallback["dynamic_fallback_allowed"] = True
    with pytest.raises(ValueError, match="DYNAMIC_FALLBACK_FORBIDDEN"):
        LOADER.validate_binding_config(fallback)
    writer = safe_binding()
    writer["authoritative_lifecycle_writer"] = "tools/other.py"
    with pytest.raises(ValueError, match="AUTHORITATIVE_WRITER_MISMATCH"):
        LOADER.validate_binding_config(writer)


def test_closed_measurement_row_requires_exact_realized_r_formula() -> None:
    row = {field: 0 for field in LOADER.REQUIRED_MEASUREMENT_FIELDS}
    row.update(
        {
            "strategy_id": "alpha_combo",
            "owner_sha256": "a" * 64,
            "symbol": "BTCUSDT",
            "side": "long",
            "regime": "trend",
            "entry_ts": "2026-01-01T00:00:00Z",
            "exit_ts": "2026-01-01T00:10:00Z",
            "entry_price": 100.0,
            "stop_price": 99.0,
            "initial_risk_usdt": 10.0,
            "realized_pnl_usdt": 15.0,
            "realized_R": 1.5,
            "fee": 0.1,
            "slippage": 0.02,
            "latency_ms": 30.0,
            "MFE_R": 2.0,
            "MAE_R": -0.3,
            "time_exposure_min": 10.0,
            "epoch_id": "EXACT25_EDGE_V1",
        }
    )
    LOADER.validate_closed_measurement_row(row)
    row["realized_R"] = 1.4
    with pytest.raises(ValueError, match="REALIZED_R_FORMULA_MISMATCH"):
        LOADER.validate_closed_measurement_row(row)


def test_surface_audit_requires_single_lifecycle_writer_and_observer_secondary(tmp_path: Path) -> None:
    path = tmp_path / "runtime_results/q4r3/exact25_shadow_binding_surface_audit"
    path.mkdir(parents=True)
    payload = {
        "status": "PASS_Q4R3_EXACT25_SHADOW_BINDING_SURFACE_AUDIT",
        "verdict": "EXACT25_SHADOW_BINDING_SURFACE_READY",
        "manifest_gate": True,
        "gaps": [],
        "source_surfaces": {
            "open_writer": [
                {"path": BINDER.EXPECTED_PRIMARY_WRITER, "strong": True},
                {"path": "tools/noise.py", "strong": False},
            ],
            "close_r_writer": [
                {"path": BINDER.EXPECTED_PRIMARY_WRITER, "strong": True},
                {"path": BINDER.EXPECTED_SECONDARY_WRITER, "strong": True},
            ],
        },
    }
    target = path / "q4r3_exact25_shadow_binding_surface_audit_latest.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    result = BINDER.verify_surface_audit(tmp_path)
    assert result["manifest_gate"] is True


def test_build_binding_never_enables_writes_or_execution() -> None:
    manifest = {"schema": "q4r3_canonical_strategy_owner_manifest_v1", "strategies": []}
    writer = {
        "authoritative_lifecycle_writer": BINDER.EXPECTED_PRIMARY_WRITER,
        "authoritative_lifecycle_writer_sha256": BINDER.EXPECTED_PRIMARY_WRITER_SHA,
        "secondary_close_writer": BINDER.EXPECTED_SECONDARY_WRITER,
        "secondary_close_writer_sha256": BINDER.EXPECTED_SECONDARY_WRITER_SHA,
        "secondary_close_writer_mode": "OBSERVER_ONLY_NOT_BOUND",
    }
    binding = BINDER.build_binding(manifest, writer, "txn")
    assert binding["shadow_enabled"] is True
    assert binding["binding_state"] == "SHADOW_BOUND_DRYRUN_ONLY"
    assert binding["epoch_id"] == "EXACT25_EDGE_V1"
    assert binding["preexisting_data_label"] == "PRE_EXACT25"
    assert binding["forward_rows_only"] is True
    assert binding["historical_r_backfill_allowed"] is False
    assert binding["write_enabled"] is False
    assert binding["canary_enabled"] is False
    assert binding["paper_enabled"] is False
    assert binding["live_enabled"] is False
    assert binding["order_enabled"] is False


def test_backup_restore_handles_new_and_existing_files(tmp_path: Path) -> None:
    root = tmp_path / "root"
    existing = root / "backend/existing.txt"
    existing.parent.mkdir(parents=True)
    existing.write_text("before", encoding="utf-8")
    backup = tmp_path / "backup"
    BINDER.make_backup(root, backup, ["backend/existing.txt", "backend/new.txt"])
    existing.write_text("after", encoding="utf-8")
    new = root / "backend/new.txt"
    new.write_text("new", encoding="utf-8")
    BINDER.restore_backup(root, backup)
    assert existing.read_text(encoding="utf-8") == "before"
    assert not new.exists()


def test_artifact_scripts_compile() -> None:
    for path in (
        ROOT / "artifacts/q4r3_exact25_shadow_binding/backend/engine/q4r3_exact25_shadow_manifest_loader.py",
        ROOT / "artifacts/q4r3_exact25_shadow_binding/tools/q4r3_exact25_edge_v1_shadow_sidecar.py",
        ROOT / "tools/q4r3_exact25_shadow_only_sidecar_staged_bind.py",
    ):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
