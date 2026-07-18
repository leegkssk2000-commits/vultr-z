from __future__ import annotations

import importlib.util
import json
from pathlib import Path

TARGET = Path(__file__).parents[1] / "tools/q4r3_exact25_r73b4s2_alimi_endpoint_origin_resolver.py"
SPEC = importlib.util.spec_from_file_location("r73b4s2", TARGET)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_canonical_json_hash_ignores_formatting() -> None:
    left = {"closed_count": 68, "nested": {"pnl_r": 53.613052}}
    right = json.loads('{"nested":{"pnl_r":53.613052},"closed_count":68}')
    assert module.canonical_json_sha(left) == module.canonical_json_sha(right)


def test_nested_metrics_are_resolved() -> None:
    payload = {"summary": {"closed": 68, "wr": 37.209, "pnl_r": 53.613052}, "trace": {"position_id": "x"}}
    result = module.metrics(payload)
    assert result["closed_count"] == 68
    assert result["pnl_r"] == 53.613052
    assert result["winrate_pct"] == 37.209
    assert result["latest_trace_id"] == "x"


def test_file_inventory_matches_endpoint_payload(tmp_path: Path) -> None:
    root = tmp_path / "api"
    root.mkdir()
    payload = {"summary": {"closed_count": 0, "net_r": 0.0}}
    (root / "view_contract_authoritative_latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    matches, preferred, scanned = module.file_inventory(
        [root], module.canonical_json_sha(payload), 100000, 100,
        ["view_contract_authoritative_latest.json"],
    )
    assert scanned == 1
    assert len(matches) == 1
    assert len(preferred) == 1
