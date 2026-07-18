from __future__ import annotations

import importlib.util
import json
from pathlib import Path

TARGET = Path(__file__).parents[1] / "tools/q4r3_exact25_r73b4s1_alimi_surface_resolver.py"
SPEC = importlib.util.spec_from_file_location("r73b4s1", TARGET)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def contract(root: Path) -> dict[str, object]:
    return {
        "target_names": ["view_contract_latest.json", "q4r3_shadow_closed_ledger_latest.json", "telegram_pos_status_latest.json"],
        "scan_roots": [str(root)],
        "excluded_names": [".git", "node_modules", "__pycache__"],
        "limits": {"max_files": 100, "max_file_bytes": 100000, "max_matches": 20},
        "next_stage": "R7.3B4S2_ALIMI_ACTUAL_SURFACE_BINDING_PLAN",
    }


def test_scan_finds_target_and_writer(tmp_path: Path) -> None:
    target = tmp_path / "public/api/view_contract_latest.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"closed": 68}), encoding="utf-8")
    writer = tmp_path / "writer.py"
    writer.write_text('Path("/x/view_contract_latest.json").write_text("{}")', encoding="utf-8")
    records, meta = module.scan(contract(tmp_path))
    assert meta["scan_truncated"] == 0
    assert any(row["kind"] == "EXACT_TARGET_FILE" for row in records)
    assert any(row["kind"] == "WRITER_CANDIDATE" for row in records)


def test_line_hits_are_exactly_reported() -> None:
    hits = module.line_hits("a\nview_contract_latest.json\nb", ["view_contract_latest.json"])
    assert hits["view_contract_latest.json"] == [2]


def test_reference_without_write_marker_is_not_writer(tmp_path: Path) -> None:
    reader = tmp_path / "reader.js"
    reader.write_text('fetch("/api/view_contract_latest.json")', encoding="utf-8")
    records, _ = module.scan(contract(tmp_path))
    assert records[0]["kind"] == "REFERENCE"
