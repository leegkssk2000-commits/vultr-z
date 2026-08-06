#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "backend/research/zel_scalp_data_split_materialization_v1.json"


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def main() -> None:
    data = json.loads(PATH.read_text())
    assert data["schema_version"] == "zel.scalp.data_split_materialization.v1"
    assert data["state"] == "PASS_SPLIT_BOUNDARIES_SEALED_FILE_SHA_MATERIALIZATION_REQUIRED"
    assert data["strategy_id"] == "intraday_pullback_reclaim_v1"
    src = data["source_dataset"]
    assert src["accepted_parent_pr"] == 575
    assert src["required_timeframes"] == ["3m", "5m", "15m"]
    assert len(src["symbols"]) == 5

    coverage_start = parse(src["coverage_start"])
    coverage_end = parse(src["coverage_end_exclusive"])
    excluded_start = parse(src["excluded_interval"]["start"])
    excluded_end = parse(src["excluded_interval"]["end_exclusive"])
    assert coverage_start < excluded_start < excluded_end < coverage_end

    windows = data["sealed_windows"]
    ordered = ["research", "W1", "W2", "W3"]
    parsed = []
    for name in ordered:
        start = parse(windows[name]["start"])
        end = parse(windows[name]["end_exclusive"])
        assert coverage_start <= start < end <= coverage_end
        parsed.append((name, start, end))
    for (_, _, left_end), (_, right_start, _) in zip(parsed, parsed[1:]):
        gap_h = (right_start - left_end).total_seconds() / 3600
        assert gap_h >= data["separation"]["minimum_gap_hours_between_windows"]

    assert data["separation"]["non_overlap_assertion"] is True
    assert data["execution_contract"]["entry"] == "next eligible bar only after closed reclaim confirmation"
    assert data["execution_contract"]["same_bar_entry_hindsight"] is False
    assert data["execution_contract"]["maker_fill_assumption"] is False
    assert data["execution_contract"]["future_MFE_MAE"] is False

    required = set(data["required_materialized_fields_before_replay"])
    must = {
        "candidate_source_sha256",
        "design_receipt_sha256",
        "trial_plan_sha256",
        "cost_receipt_sha256",
        "funding_receipt_sha256",
        "per_symbol_timeframe_file_sha256",
        "manifest_receipt_sha256",
    }
    assert must <= required
    authority = data["authority"]
    assert authority == {
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    print({"state": data["state"], "windows": ordered, "replay_allowed": False})


if __name__ == "__main__":
    main()
