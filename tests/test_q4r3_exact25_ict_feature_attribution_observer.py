from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from tools import q4r3_exact25_ict_feature_attribution_observer as observer


def ssot() -> dict:
    return {
        "expected_epoch": "EXACT25_EDGE_V1",
        "expected_namespace": "EXACT25_EDGE_V1",
        "expected_source": "q4r3_exact25_dedicated_shadow_producer",
        "expected_measurement_source": "q4r3_exact25_single_event_measurement_adapter",
        "required_feature_fields": [
            "observer_only",
            "htf_bias",
            "swing_sequence",
            "dealing_range_position",
            "premium_discount_side",
            "ote_depth",
            "ote_0_5_0_79",
            "ltf_reversal_confirm",
            "session_window",
            "invalidation_swing_price",
            "invalidation_swing_distance_pct",
        ],
        "categorical_attribution_fields": [
            "htf_bias",
            "swing_sequence",
            "premium_discount_side",
            "ote_0_5_0_79",
            "ltf_reversal_confirm",
            "session_window",
        ],
        "numeric_attribution_bins": {
            "dealing_range_position": [0.0, 0.2, 0.5, 0.8, 1.0],
            "ote_depth": [0.0, 0.5, 0.79, 1.0],
            "invalidation_swing_distance_pct": [0.0, 0.25, 0.5, 1.0, 2.0, 5.0, 1000000.0],
        },
        "allowed_values": {
            "htf_bias": ["long", "short", "neutral"],
            "swing_sequence": ["HH_HL", "LH_LL", "MIXED", "UNRESOLVED"],
            "premium_discount_side": ["discount", "premium"],
            "session_window": ["asia", "london", "london_newyork_overlap", "newyork", "off_session"],
        },
        "minimum_bucket_sample": 30,
        "feature_filter_must_remain_disabled": True,
    }


def feature(*, position: float = 0.3, depth: float | None = 0.7) -> dict:
    return {
        "observer_only": True,
        "htf_bias": "long",
        "swing_sequence": "HH_HL",
        "dealing_range_position": position,
        "premium_discount_side": "discount" if position < 0.5 else "premium",
        "ote_depth": depth,
        "ote_0_5_0_79": depth is not None and 0.5 <= depth <= 0.79,
        "ltf_reversal_confirm": True,
        "session_window": "london",
        "invalidation_swing_price": 99.0,
        "invalidation_swing_distance_pct": 1.0,
    }


def row(event_id: str, realized_r: float = 1.0) -> dict:
    return {
        "event_id": event_id,
        "position_id": event_id.removesuffix(":close"),
        "strategy_id": "trend_following",
        "owner_sha256": "a" * 64,
        "symbol": "BTCUSDT",
        "side": "long",
        "epoch_id": "EXACT25_EDGE_V1",
        "measurement_namespace": "EXACT25_EDGE_V1",
        "source": "q4r3_exact25_dedicated_shadow_producer",
        "measurement_source": "q4r3_exact25_single_event_measurement_adapter",
        "mode": "shadow",
        "shadow": True,
        "status": "CLOSED",
        "closed": True,
        "feature_observer_only": True,
        "entry_features": feature(),
        "exit_features": feature(position=0.6, depth=0.4),
        "realized_R": realized_r,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
    }


def execute(tmp_path: Path, rows: list[dict], *, feature_filter_enabled: bool = False) -> tuple[dict, dict, bytes, bytes]:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("".join(json.dumps(value, sort_keys=True) + "\n" for value in rows), encoding="utf-8")
    ssot_path = tmp_path / "ssot.json"
    ssot_path.write_text(json.dumps(ssot()), encoding="utf-8")
    producer = tmp_path / "producer.json"
    producer.write_text(json.dumps({"state": "RUNNING", "feature_filter_enabled": feature_filter_enabled}), encoding="utf-8")
    report = tmp_path / "report.json"
    violations = tmp_path / "violations.json"
    before = ledger.read_bytes()
    args = argparse.Namespace(
        ledger=ledger,
        producer_status=producer,
        ssot=ssot_path,
        report=report,
        violations=violations,
    )
    assert observer.run(args) == 0
    after = ledger.read_bytes()
    return json.loads(report.read_text()), json.loads(violations.read_text()), before, after


def test_empty_accumulation_is_not_a_violation(tmp_path: Path) -> None:
    report, violations, before, after = execute(tmp_path, [])
    assert report["status"] == "PASS"
    assert report["ledger_row_count"] == 0
    assert report["coverage"]["entry"]["complete_coverage_pct"] is None
    assert violations["state"] == "CLEAR"
    assert before == after


def test_valid_rows_build_read_only_attribution(tmp_path: Path) -> None:
    report, violations, before, after = execute(tmp_path, [row("p1:close", 1.5), row("p2:close", -0.5)])
    assert report["status"] == "PASS"
    assert report["coverage"]["entry"]["complete_count"] == 2
    bucket = report["overall_entry_feature_attribution"]["htf_bias"]["long"]
    assert bucket["sample_count"] == 2
    assert bucket["cumulative_R"] == 1.0
    assert bucket["decision"] == "OBSERVE_ONLY"
    assert report["attribution_decision_enabled"] is False
    assert violations["count"] == 0
    assert before == after


def test_missing_feature_field_holds(tmp_path: Path) -> None:
    broken = row("p1:close")
    del broken["entry_features"]["session_window"]
    report, violations, _, _ = execute(tmp_path, [broken])
    assert report["status"] == "HOLD"
    assert any(item["code"] == "FEATURE_FIELD_MISSING" for item in violations["violations"])


def test_feature_filter_enablement_is_blocked(tmp_path: Path) -> None:
    report, violations, _, _ = execute(tmp_path, [row("p1:close")], feature_filter_enabled=True)
    assert report["status"] == "HOLD"
    assert violations["severity"] == "C"
    assert any(item["code"] == "FEATURE_FILTER_ENABLED" for item in violations["violations"])


def test_premium_discount_inconsistency_is_reported(tmp_path: Path) -> None:
    broken = copy.deepcopy(row("p1:close"))
    broken["entry_features"]["premium_discount_side"] = "premium"
    report, violations, _, _ = execute(tmp_path, [broken])
    assert report["status"] == "HOLD"
    assert any(item["code"] == "PREMIUM_DISCOUNT_INCONSISTENT" for item in violations["violations"])


def test_identical_violation_is_deduplicated(tmp_path: Path) -> None:
    broken = row("p1:close")
    del broken["entry_features"]["session_window"]
    first, first_violations, _, _ = execute(tmp_path, [broken])
    assert first["violation_notify"] is True

    ledger = tmp_path / "ledger.jsonl"
    producer = tmp_path / "producer.json"
    ssot_path = tmp_path / "ssot.json"
    report = tmp_path / "report.json"
    violations = tmp_path / "violations.json"
    args = argparse.Namespace(
        ledger=ledger,
        producer_status=producer,
        ssot=ssot_path,
        report=report,
        violations=violations,
    )
    assert observer.run(args) == 0
    second = json.loads(report.read_text())
    second_violations = json.loads(violations.read_text())
    assert second["violation_notify"] is False
    assert second_violations["fingerprint"] == first_violations["fingerprint"]
