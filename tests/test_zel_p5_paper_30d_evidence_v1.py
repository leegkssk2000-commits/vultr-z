from __future__ import annotations

import copy
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from backend.runtime.zel_paper_canary_ledger_v1 import PaperCanaryLedgerError
from backend.runtime.zel_paper_canary_ledger_v1_1 import PaperCanaryLedgerV1_1

BERLIN = ZoneInfo("Europe/Berlin")
UTC = ZoneInfo("UTC")


def policy() -> dict:
    return {
        "policy_ref": "runtime:ssot/paper_policy",
        "policy_sha256": "f" * 64,
        "minimum_calendar_days": 30,
        "minimum_closed_positions": 20,
        "minimum_daily_coverage_minutes": 1380,
        "maximum_fee_delta_bps": 1.0,
        "maximum_slippage_delta_bps": 2.0,
        "maximum_funding_delta_bps": 1.0,
        "maximum_latency_p95_ms": 1000.0,
        "maximum_shadow_paper_net_delta_r": 0.5,
    }


def period(day: date) -> tuple[int, int, int]:
    start_local = datetime.combine(day, time.min, tzinfo=BERLIN)
    end_local = datetime.combine(day + timedelta(days=1), time.min, tzinfo=BERLIN)
    start_ms = int(start_local.astimezone(UTC).timestamp() * 1000)
    end_ms = int(end_local.astimezone(UTC).timestamp() * 1000)
    coverage = int((end_ms - start_ms) / 60000)
    return start_ms, end_ms, coverage


def day_receipt(day: date, *, fixture_only: bool = False, slippage: float = 0.5) -> dict:
    start_ms, end_ms, coverage = period(day)
    suffix = day.isoformat().replace("-", "")
    return {
        "canary_id": "paper.canary.test",
        "berlin_date": day.isoformat(),
        "period_start_ms": start_ms,
        "period_end_ms": end_ms,
        "observed_at_ms": end_ms + 1000,
        "environment_kind": "VPS_RUNTIME",
        "source_ref": f"runtime:paper/day/{suffix}",
        "source_sha256": ("1" + suffix).ljust(64, "a")[:64],
        "private_api_receipt_sha256": ("2" + suffix).ljust(64, "a")[:64],
        "oms_receipt_sha256": ("3" + suffix).ljust(64, "a")[:64],
        "shadow_receipt_sha256": ("4" + suffix).ljust(64, "a")[:64],
        "formal_ledger_sha256": ("5" + suffix).ljust(64, "a")[:64],
        "display_sha256": ("6" + suffix).ljust(64, "a")[:64],
        "closed_positions": 1,
        "coverage_minutes": coverage,
        "lifecycle_mismatch_count": 0,
        "ledger_mismatch_count": 0,
        "display_mismatch_count": 0,
        "duplicate_order_count": 0,
        "orphan_order_count": 0,
        "unreconciled_position_count": 0,
        "threshold_breach_count": 0,
        "fee_delta_bps": 0.2,
        "slippage_delta_bps": slippage,
        "funding_delta_bps": 0.1,
        "latency_p95_ms": 500.0,
        "shadow_paper_net_delta_r": 0.2,
        "source_authority_verified": True,
        "fixture_only": fixture_only,
    }


def drill(day: date, drill_type: str, index: int) -> dict:
    start_ms, _, _ = period(day)
    return {
        "canary_id": "paper.canary.test",
        "drill_id": f"drill.{index}",
        "drill_type": drill_type,
        "passed": True,
        "occurred_at_ms": start_ms + 3_600_000,
        "evidence_sha256": str(index + 7) * 64,
        "source_ref": f"runtime:paper/drill/{index}",
    }


def append_days(ledger: PaperCanaryLedgerV1_1, start: date, count: int, *, fixture_only: bool = False) -> int:
    now_ms = period(start + timedelta(days=count + 2))[1]
    for index in range(count):
        ledger.append_day(day_receipt(start + timedelta(days=index), fixture_only=fixture_only), now_ms=now_ms)
    return now_ms


def test_30_consecutive_runtime_days_and_drills_pass_gate(tmp_path: Path) -> None:
    ledger = PaperCanaryLedgerV1_1(tmp_path / "paper.sqlite3")
    start = date(2026, 1, 1)
    now_ms = append_days(ledger, start, 30)
    ledger.append_drill(drill(start + timedelta(days=10), "RESTART_RECOVERY", 1), now_ms=now_ms)
    ledger.append_drill(drill(start + timedelta(days=20), "ROLLBACK", 2), now_ms=now_ms)
    result = ledger.evaluate("paper.canary.test", policy())
    assert result["state"] == "PASS_P5_PAPER_30D_CANARY", result
    assert result["calendar_day_count"] == 30
    assert result["closed_position_count"] == 30
    assert result["activation_allowed"] is False
    assert result["live_allowed"] is False


def test_fixture_days_can_never_pass_real_gate(tmp_path: Path) -> None:
    ledger = PaperCanaryLedgerV1_1(tmp_path / "paper.sqlite3")
    start = date(2026, 1, 1)
    now_ms = append_days(ledger, start, 30, fixture_only=True)
    ledger.append_drill(drill(start + timedelta(days=10), "RESTART_RECOVERY", 1), now_ms=now_ms)
    ledger.append_drill(drill(start + timedelta(days=20), "ROLLBACK", 2), now_ms=now_ms)
    result = ledger.evaluate("paper.canary.test", policy())
    assert result["state"] == "HOLD_P5_PAPER_30D_INCOMPLETE"
    assert "FIXTURE_DAY_FORBIDDEN" in result["blockers"]


def test_less_than_30_days_stays_hold(tmp_path: Path) -> None:
    ledger = PaperCanaryLedgerV1_1(tmp_path / "paper.sqlite3")
    append_days(ledger, date(2026, 1, 1), 29)
    result = ledger.evaluate("paper.canary.test", policy())
    assert "MINIMUM_30_CALENDAR_DAYS_NOT_MET" in result["blockers"]


def test_day_chain_rejects_gap_and_payload_conflict(tmp_path: Path) -> None:
    ledger = PaperCanaryLedgerV1_1(tmp_path / "paper.sqlite3")
    start = date(2026, 1, 1)
    now_ms = period(start + timedelta(days=4))[1]
    first = day_receipt(start)
    assert ledger.append_day(first, now_ms=now_ms)["replayed"] is False
    assert ledger.append_day(first, now_ms=now_ms)["replayed"] is True
    changed = copy.deepcopy(first)
    changed["closed_positions"] = 2
    with pytest.raises(PaperCanaryLedgerError, match="DAY_IDEMPOTENCY_CONFLICT"):
        ledger.append_day(changed, now_ms=now_ms)
    with pytest.raises(PaperCanaryLedgerError, match="PAPER_DAY_NOT_CONSECUTIVE"):
        ledger.append_day(day_receipt(start + timedelta(days=2)), now_ms=now_ms)


def test_calibration_breach_holds_even_with_30_days(tmp_path: Path) -> None:
    ledger = PaperCanaryLedgerV1_1(tmp_path / "paper.sqlite3")
    start = date(2026, 1, 1)
    now_ms = period(start + timedelta(days=33))[1]
    for index in range(30):
        receipt = day_receipt(start + timedelta(days=index), slippage=5.0 if index == 12 else 0.5)
        ledger.append_day(receipt, now_ms=now_ms)
    ledger.append_drill(drill(start + timedelta(days=10), "RESTART_RECOVERY", 1), now_ms=now_ms)
    ledger.append_drill(drill(start + timedelta(days=20), "ROLLBACK", 2), now_ms=now_ms)
    result = ledger.evaluate("paper.canary.test", policy())
    assert "SLIPPAGE_DELTA_BPS_LIMIT" in result["blockers"]
    assert result["state"] == "HOLD_P5_PAPER_30D_INCOMPLETE"
