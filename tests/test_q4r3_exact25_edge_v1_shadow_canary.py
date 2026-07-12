from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools/q4r3_exact25_edge_v1_shadow_canary.py"
    spec = importlib.util.spec_from_file_location("q4r3_exact25_edge_v1_shadow_canary_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def test_deterministic_row_has_exact_r_formula_and_safe_flags() -> None:
    row = MODULE.deterministic_row("alpha_combo", "a" * 64, 3)
    assert row["epoch_id"] == "EXACT25_EDGE_V1"
    assert row["strategy_id"] == "alpha_combo"
    assert row["owner_sha256"] == "a" * 64
    assert row["initial_risk_usdt"] > 0
    assert row["realized_R"] == row["realized_pnl_usdt"] / row["initial_risk_usdt"]
    assert row["paper_enabled"] is False
    assert row["live_enabled"] is False
    assert row["order_enabled"] is False


def test_append_unique_rows_accepts_once_and_rejects_replay(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    MODULE.LOCK = tmp_path / ".lock"
    rows = [
        MODULE.deterministic_row("alpha_combo", "a" * 64, 0),
        MODULE.deterministic_row("bb_revert", "b" * 64, 1),
    ]
    first = MODULE.append_unique_rows(ledger, rows)
    second = MODULE.append_unique_rows(ledger, rows)
    assert first == {"accepted": 2, "rejected_duplicate": 0}
    assert second == {"accepted": 0, "rejected_duplicate": 2}
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 2


def test_verify_ledger_detects_no_duplicates_or_formula_gaps(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    rows = {
        "alpha_combo": MODULE.deterministic_row("alpha_combo", "a" * 64, 0),
        "bb_revert": MODULE.deterministic_row("bb_revert", "b" * 64, 1),
    }
    ledger.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows.values()) + "\n", encoding="utf-8")
    result = MODULE.verify_ledger(ledger, rows)
    assert result["row_count"] == 2
    assert result["unique_event_count"] == 2
    assert result["duplicate_count"] == 0
    assert result["owner_mismatches"] == []
    assert result["formula_mismatches"] == []
    assert result["unsafe_flags"] == []


def test_assert_safe_binding_rejects_execution_flags(monkeypatch, tmp_path: Path) -> None:
    writer = tmp_path / "tools/q4r3_vwap_mfe_mae_capture_sidecar.py"
    writer.parent.mkdir(parents=True)
    writer.write_text("# writer\n", encoding="utf-8")
    monkeypatch.setattr(MODULE, "ROOT", tmp_path)
    binding = {
        "epoch_id": "EXACT25_EDGE_V1",
        "shadow_enabled": True,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "write_enabled": False,
        "canary_enabled": False,
        "authoritative_lifecycle_writer": MODULE.EXPECTED_WRITER,
        "authoritative_lifecycle_writer_sha256": MODULE.file_sha256(writer),
    }
    MODULE.assert_safe_binding(binding)
    binding["live_enabled"] = True
    try:
        MODULE.assert_safe_binding(binding)
    except ValueError as exc:
        assert "UNSAFE_BINDING_FLAG:live_enabled" in str(exc)
    else:
        raise AssertionError("unsafe live flag was not rejected")
