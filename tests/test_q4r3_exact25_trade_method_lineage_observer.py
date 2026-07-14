from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/q4r3_exact25_trade_method_lineage_observer.py"
spec = importlib.util.spec_from_file_location("q4r3_trade_method_observer", MODULE_PATH)
assert spec and spec.loader
observer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = observer
spec.loader.exec_module(observer)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def setup_case(tmp_path: Path, *, runtime_second: bool = True, conflict: bool = False) -> argparse.Namespace:
    root = tmp_path / "root"
    (root / "backend/trade_methods").mkdir(parents=True)
    (root / "backend/config").mkdir(parents=True)
    resolver = root / "backend/trade_methods/resolver.py"
    resolver.write_text(
        'PROFILES={"scalp_first":{"hold_horizon":"3-15m"},"intraday":{"hold_horizon":"10-45m"}}\n'
        "def resolve_trade_method(strategy_id):\n    return PROFILES.get(strategy_id)\n",
        encoding="utf-8",
    )
    producer = root / "backend/producer.py"
    producer.write_text("from backend.trade_methods.resolver import resolve_trade_method\n", encoding="utf-8")
    write_json(
        root / "backend/config/registry.json",
        {
            "alpha": {"method_hint": "scalp_first", "method_subtype": "continuation"},
            "beta": {"method_hint": "intraday", "method_subtype": "breakout_probe"},
        },
    )
    manifest = root / "backend/config/manifest.json"
    write_json(manifest, {"strategies": [{"strategy_id": "alpha"}, {"strategy_id": "beta"}]})
    ledger = root / "runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {
                    "event_id": "e1",
                    "strategy_id": "alpha",
                    "symbol": "BTCUSDT",
                    "trade_method": "scalp_first",
                    "method_subtype": "continuation",
                    "pnl_r": 0.5,
                },
                {"event_id": "e2", "strategy_id": "beta", "symbol": "ETHUSDT", "pnl_r": -0.2},
            )
        )
        + "\n",
        encoding="utf-8",
    )
    if runtime_second:
        records = [
            {
                "event_id": "e2",
                "strategy_id": "beta",
                "method": "intraday",
                "method_subtype": "breakout_probe",
            }
        ]
        if conflict:
            records.append({"event_id": "e2", "strategy_id": "beta", "method": "scalp_first"})
        write_json(root / "runtime/exact25_edge_v1/dedicated_shadow_producer/method_latest.json", {"records": records})
    ssot = root / "backend/config/ssot.json"
    write_json(
        ssot,
        {
            "expected_strategy_count": 2,
            "scan_roots": ["backend"],
            "runtime_scan_root": "runtime/exact25_edge_v1",
            "runtime_scan_max_files": 50,
            "runtime_scan_max_age_hours": 72,
            "max_source_file_bytes": 1000000,
            "source_suffixes": [".py", ".json"],
            "excluded_path_parts": [".git", ".venv", "__pycache__"],
            "discovery_tokens": [
                "trade_method",
                "method_hint",
                "scalp_first",
                "intraday",
                "entry_style",
                "hold_horizon",
                "resolver_trace_id",
            ],
            "strategy_key_aliases": ["strategy_id", "strategy", "strategy_name", "name", "id"],
            "method_key_aliases": ["method", "trade_method", "method_hint", "method_family", "execution_method"],
            "subtype_key_aliases": ["method_subtype", "trade_method_subtype", "subtype", "method_variant"],
            "lineage_field_aliases": {
                "event_id": ["event_id"],
                "position_id": ["position_id"],
                "signal_id": ["signal_id"],
                "strategy_id": ["strategy_id"],
                "symbol": ["symbol"],
                "entry_ts": ["entry_ts"],
                "method": ["method", "trade_method"],
                "method_subtype": ["method_subtype"],
                "profile_version": ["profile_version"],
                "profile_sha256": ["profile_sha256"],
                "entry_style": ["entry_style"],
                "hold_horizon": ["hold_horizon"],
                "risk_mode": ["risk_mode"],
                "target_r": ["target_R", "target_r"],
                "size_multiplier": ["size_multiplier"],
                "execution_overlays": ["execution_overlays"],
                "resolver_trace_id": ["resolver_trace_id"],
                "realized_r": ["realized_R", "pnl_r"],
            },
            "coverage_thresholds": {"preview_bucket_min": 30, "final_bucket_min": 50},
            "service_units": {"producer": "does-not-exist.service"},
            "applied_proof_requirements": {
                "formal_row_direct_method": True,
                "runtime_exact_identifier_match": True,
                "static_registry_mapping": False,
            },
        },
    )
    output = root / "runtime/exact25_edge_v1/trade_method_lineage_observer"
    return argparse.Namespace(
        root=root,
        ledger=ledger,
        manifest=manifest,
        ssot=ssot,
        output_root=output,
        inventory=output / "inventory_latest.json",
        resolver_audit=output / "resolver_audit_latest.json",
        lineage=output / "lineage_latest.jsonl",
        coverage=output / "coverage_latest.json",
        matrix=output / "strategy_method_matrix_latest.json",
        violations=output / "violations_latest.json",
        status=output / "status_latest.json",
        producer_entrypoint=producer,
    )


def test_exact_runtime_lineage_and_resolver_import_are_proven(tmp_path: Path) -> None:
    args = setup_case(tmp_path)
    assert observer.run(args) == 0
    status = json.loads(args.status.read_text(encoding="utf-8"))
    coverage = json.loads(args.coverage.read_text(encoding="utf-8"))
    resolver = json.loads(args.resolver_audit.read_text(encoding="utf-8"))
    violations = json.loads(args.violations.read_text(encoding="utf-8"))
    assert status["state"] == "CLEAR"
    assert coverage["applied_proof_count"] == 2
    assert coverage["applied_proof_coverage_pct"] == 100.0
    assert resolver["consumption_state"] == "PROVEN_RUNTIME_IMPORT"
    assert violations["count"] == 0


def test_static_mapping_is_not_applied_proof(tmp_path: Path) -> None:
    args = setup_case(tmp_path, runtime_second=False)
    assert observer.run(args) == 0
    coverage = json.loads(args.coverage.read_text(encoding="utf-8"))
    violations = json.loads(args.violations.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in args.lineage.read_text(encoding="utf-8").splitlines()]
    beta = next(row for row in rows if row["strategy_id"] == "beta")
    assert beta["lineage_source"] == "STATIC_MAPPING_ONLY"
    assert beta["applied_proof"] is False
    assert coverage["applied_proof_count"] == 1
    assert "APPLIED_TRADE_METHOD_LINEAGE_INCOMPLETE" in {item["code"] for item in violations["violations"]}


def test_conflicting_runtime_method_for_same_identifier_is_critical(tmp_path: Path) -> None:
    args = setup_case(tmp_path, runtime_second=True, conflict=True)
    assert observer.run(args) == 0
    violations = json.loads(args.violations.read_text(encoding="utf-8"))
    assert violations["severity"] == "C"
    assert "RUNTIME_IDENTIFIER_METHOD_CONFLICT" in {item["code"] for item in violations["violations"]}
