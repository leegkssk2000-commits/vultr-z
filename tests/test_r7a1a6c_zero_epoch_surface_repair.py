from pathlib import Path
import importlib.util


HERE = Path(__file__).resolve().parents[1]
MODULE_PATH = HERE / "tools" / "r7a1a6c_zero_epoch_surface_repair.py"
SPEC = importlib.util.spec_from_file_location("r7a1a6c", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def valid_http_payload():
    return {
        "summary": {"closed": 0, "pnl_r": 0, "recent_rows": 0},
        "writers7": {"configured_writer_count": 7, "active_writer_count": 0},
        "safety": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
        },
    }


def test_safety_accepts_zero_epoch_contract():
    ok, blockers = MODULE.safety_ok(valid_http_payload())
    assert ok is True
    assert blockers == []


def test_safety_rejects_any_live_authority():
    payload = valid_http_payload()
    payload["safety"]["execution_authority"] = "live"
    ok, blockers = MODULE.safety_ok(payload)
    assert ok is False
    assert "EXECUTION_AUTHORITY_NOT_NONE" in blockers


def test_zero_epoch_accepts_zero_metrics():
    ok, blockers = MODULE.zero_epoch_ok(valid_http_payload())
    assert ok is True
    assert blockers == []


def test_zero_epoch_rejects_stale_rows():
    payload = valid_http_payload()
    payload["summary"]["recent_rows"] = 43
    ok, blockers = MODULE.zero_epoch_ok(payload)
    assert ok is False
    assert "HTTP_RECENT_ROWS_NOT_ZERO_43" in blockers


def test_clean_projection_contracts_have_no_rows():
    ledger = MODULE.clean_ledger("q4r3.pending")
    trace = MODULE.clean_trace("q4r3.pending")
    assert ledger["closed"] == 0
    assert ledger["pnl_r"] == 0.0
    assert ledger["rows"] == []
    assert ledger["recent_rows"] == 0
    assert trace["rows"] == []
    assert trace["recent_rows"] == 0
    assert trace["last12_r"] == 0.0
    assert trace["wr_pct"] == 0.0
    assert trace["ev_r"] == 0.0


def test_backup_and_restore_roundtrip(tmp_path, monkeypatch):
    files = tuple(tmp_path / name for name in ("view.json", "ledger.json", "trace.json"))
    for index, path in enumerate(files):
        path.write_text(f"original-{index}", encoding="utf-8")
    monkeypatch.setattr(MODULE, "REPAIRABLE", files)
    backup_dir = tmp_path / "backup"
    MODULE.backup_files(backup_dir)
    for path in files:
        path.write_text("changed", encoding="utf-8")
    errors = MODULE.restore_manifest(backup_dir / "manifest.json")
    assert errors == []
    for index, path in enumerate(files):
        assert path.read_text(encoding="utf-8") == f"original-{index}"
