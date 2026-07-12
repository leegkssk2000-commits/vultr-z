from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_strategy_canonical_completeness_audit.py"
    spec = importlib.util.spec_from_file_location("q4r3_strategy_canonical_completeness_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def test_path_exclusion_rejects_dependencies_and_trash(tmp_path: Path) -> None:
    assert MODULE.path_is_excluded(tmp_path / ".venv" / "lib" / "x.py", tmp_path)
    assert MODULE.path_is_excluded(tmp_path / "_TRASH_ZEL_2026" / "x.py", tmp_path)
    assert MODULE.path_is_excluded(tmp_path / "backend" / "archive_old" / "x.py", tmp_path)
    assert not MODULE.path_is_excluded(tmp_path / "backend" / "strategies" / "trend_rider.py", tmp_path)


def test_resolve_exact_25_universe(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage.json"
    coverage.write_text(json.dumps({"expected_strategies": [f"strategy_{i:02d}" for i in range(25)]}), encoding="utf-8")
    result = MODULE.resolve_expected_universe([coverage])
    assert result["resolved_exact_25"] is True
    assert result["selected"]["count"] == 25
    assert result["selected"]["names"][0] == "strategy_00"


def test_missing_list_is_penalized_against_expected_list(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage.json"
    coverage.write_text(
        json.dumps(
            {
                "missing_expected_strategies": [f"missing_{i:02d}" for i in range(11)],
                "expected_strategy_universe": [f"strategy_{i:02d}" for i in range(25)],
            }
        ),
        encoding="utf-8",
    )
    result = MODULE.resolve_expected_universe([coverage])
    assert result["selected"]["count"] == 25
    assert result["selected"]["key_path"] == "expected_strategy_universe"


def test_strategy_pattern_matches_separator_variants() -> None:
    pattern = MODULE.strategy_pattern("support_resistance")
    assert pattern.search("support_resistance")
    assert pattern.search("support-resistance")
    assert pattern.search("support resistance")
    assert not pattern.search("supportresistanceextra")


def test_pollution_bucket_classification() -> None:
    assert MODULE.pollution_bucket("./.venv/lib/site-packages/a.py:3") == "dependency"
    assert MODULE.pollution_bucket("./_TRASH_ZEL/a.json:2") == "trash_quarantine"
    assert MODULE.pollution_bucket("./frontend/index.html:1") == "frontend_display"
    assert MODULE.pollution_bucket("./runtime/latest.json:1") == "runtime_generated"
    assert MODULE.pollution_bucket("./backend/strategies/a.py:1") == "active_candidate"


def test_complete_strategy_candidate(tmp_path: Path) -> None:
    implementation = tmp_path / "backend" / "strategies" / "trend_rider.py"
    implementation.parent.mkdir(parents=True)
    implementation.write_text(
        "strategy_id='trend_rider'\nentry_price=1\nentry_ts=1\ninitial_stop=0.9\n"
        "initial_risk_usdt=10\nrealized_r=1\njson.dumps({'ledger': 1})\n"
        "walk_forward=True\nsource='https://arxiv.org/abs/1'\nscale_in=True\n",
        encoding="utf-8",
    )
    registry = tmp_path / "config" / "strategy_registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text('{"strategy_id":"trend_rider"}', encoding="utf-8")
    test_file = tmp_path / "tests" / "test_trend_rider.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_trend_rider(): assert True", encoding="utf-8")

    records = []
    for path in (implementation, registry, test_file):
        record = MODULE.load_file_record(path, tmp_path)
        assert record is not None
        records.append(record)

    result = MODULE.analyze_strategy("trend_rider", records)
    assert result["verdict"] == "COMPLETE_CANDIDATE_PENDING_ABLATION"
    assert result["score_100"] == 100
    assert result["missing_required"] == []


def test_registry_only_strategy_is_not_complete(tmp_path: Path) -> None:
    registry = tmp_path / "config" / "strategy_registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text('{"strategy_id":"vwap_revert"}', encoding="utf-8")
    record = MODULE.load_file_record(registry, tmp_path)
    assert record is not None
    result = MODULE.analyze_strategy("vwap_revert", [record])
    assert result["verdict"] == "REGISTRY_ONLY"
    assert "implementation" in result["missing_required"]


def test_parse_location_path_handles_timestamp_listing() -> None:
    line = "2026-07-12 18:00:00 | 100 B | ./backend/strategies/a.py"
    assert MODULE.parse_location_path(line) == "./backend/strategies/a.py"
    assert MODULE.parse_location_path("./backend/a.py:42") == "./backend/a.py"
