from __future__ import annotations

import json
from pathlib import Path

from backend.research.carry_positioning_event_study_v1 import evaluate


def contract() -> dict:
    return json.loads(Path("config/zel_production_carry_positioning_v1.json").read_text())


def coverage(ready: bool) -> dict:
    return {
        "schema_version": "zel.p3.prospective_native_coverage.v1",
        "state": "PASS_P3_BASIS_OI_COVERAGE_READY_FLOW_BLOCKED" if ready else "HOLD_P3_PROSPECTIVE_HISTORY_ACCUMULATING",
        "required_capture_span_ms": 1814340000,
        "basis_oi_duration_gate_pass": ready,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }


def record(feature: str, symbol: str, collected: int, event: int, *, mark: float, index: float, funding: float, oi: float) -> dict:
    values = (
        {
            "symbol": symbol,
            "markPrice": str(mark),
            "indexPrice": str(index),
            "lastFundingRate": str(funding),
            "fundingIntervalHours": 8,
            "nextFundingTime": event,
            "updateTime": collected,
        }
        if feature == "premium_index"
        else {"symbol": symbol, "openInterest": str(oi), "time": collected}
    )
    return {
        "schema_version": "zel.p3.prospective_native_feature_record.v1",
        "feature": feature,
        "symbol": symbol,
        "source_endpoint": "fixture",
        "source_base": "fixture",
        "source_timestamp_ms": collected,
        "collected_at_ms": collected,
        "latency_ms": 1.0,
        "values": values,
        "source_payload_sha256": "a" * 64,
        "prospective_only": True,
        "historical_coverage_claim": False,
        "derived_basis_value_emitted": False,
        "signal_generation_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }


def write_history(root: Path, profitable: bool) -> None:
    for symbol in ("BTC-USDT", "ETH-USDT"):
        premium = []
        oi_rows = []
        base = 100.0 if symbol.startswith("BTC") else 200.0
        for i in range(4):
            event = 100_000_000 + i * 28_800_000
            first = event - 25_000_000
            last = event - 1_000_000
            entry = base + i * 2.0
            exit_price = entry * (0.995 if profitable else 1.005)
            for collected, mark in ((first, entry), (last, exit_price)):
                premium.append(record("premium_index", symbol, collected, event, mark=mark, index=mark * 0.999, funding=0.0001, oi=0))
                oi_rows.append(record("open_interest", symbol, collected, event, mark=0, index=0, funding=0, oi=1000 + i * 100))
        compact = symbol.replace("-", "")
        (root / f"premium_index__{compact}.ndjson").write_text("".join(json.dumps(x) + "\n" for x in premium))
        (root / f"open_interest__{compact}.ndjson").write_text("".join(json.dumps(x) + "\n" for x in oi_rows))


def test_coverage_pending_is_o1_hold(tmp_path: Path) -> None:
    r = evaluate(tmp_path, coverage(False), contract())
    assert r["state"] == "HOLD_CARRY_POSITIONING_HISTORY_COVERAGE_PENDING"
    assert r["trades"] == []
    assert r["selection_authority"] is False
    assert r["execution_authority"] == "NONE"


def test_profitable_both_temporal_halves_is_candidate_only(tmp_path: Path) -> None:
    write_history(tmp_path, True)
    r = evaluate(tmp_path, coverage(True), contract())
    assert r["state"] == "PASS_CARRY_POSITIONING_EVENT_STUDY_CANDIDATE_AUTHORITY_BLOCKED"
    assert r["economic_candidate"] is True
    assert r["temporal_split"]["first_half_pass"] is True
    assert r["temporal_split"]["second_half_pass"] is True
    assert r["survivor_authority"] is False
    assert r["promotion_authority"] is False
    assert r["order_authority"] == "BLOCKED"


def test_losing_crowding_unwind_is_terminal_economic_reject(tmp_path: Path) -> None:
    write_history(tmp_path, False)
    r = evaluate(tmp_path, coverage(True), contract())
    assert r["state"] == "REJECT_CARRY_POSITIONING_EVENT_STUDY_DURABILITY"
    assert r["economic_candidate"] is False
    assert r["action"] == "hold"
    assert r["exchange_order_submitted"] is False
