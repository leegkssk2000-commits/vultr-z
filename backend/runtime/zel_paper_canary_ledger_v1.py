from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from backend.contracts.zel_paper_canary_v1 import (
    canonical_json,
    canonical_sha,
    normalize_day,
    normalize_drill,
    normalize_policy,
)

SCHEMA_VERSION = "zel.paper_canary.ledger.v1"
GENESIS_SHA = canonical_sha({"kind": "ZEL_PAPER_CANARY_GENESIS_V1"})
ZERO_COUNT_FIELDS = (
    "lifecycle_mismatch_count", "ledger_mismatch_count", "display_mismatch_count",
    "duplicate_order_count", "orphan_order_count", "unreconciled_position_count",
    "threshold_breach_count",
)


class PaperCanaryLedgerError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise PaperCanaryLedgerError(f"{code}:{detail}" if detail else code)


class PaperCanaryLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_days (
                    canary_id TEXT NOT NULL,
                    berlin_date TEXT NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    previous_day_sha256 TEXT NOT NULL,
                    day_sha256 TEXT NOT NULL UNIQUE,
                    day_json TEXT NOT NULL,
                    PRIMARY KEY(canary_id, berlin_date),
                    UNIQUE(canary_id, sequence_no)
                );
                CREATE TABLE IF NOT EXISTS paper_drills (
                    canary_id TEXT NOT NULL,
                    drill_id TEXT NOT NULL,
                    drill_type TEXT NOT NULL,
                    occurred_at_ms INTEGER NOT NULL,
                    drill_sha256 TEXT NOT NULL UNIQUE,
                    drill_json TEXT NOT NULL,
                    PRIMARY KEY(canary_id, drill_id)
                );
                """
            )

    def append_day(self, value: dict[str, Any], *, now_ms: int) -> dict[str, Any]:
        day = normalize_day(value, now_ms=now_ms)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT day_json FROM paper_days WHERE canary_id=? AND berlin_date=?",
                (day["canary_id"], day["berlin_date"]),
            ).fetchone()
            if prior is not None:
                existing = json.loads(prior["day_json"])
                if existing["day_payload_sha256"] != day["day_payload_sha256"]:
                    _fail("DAY_IDEMPOTENCY_CONFLICT", day["berlin_date"])
                connection.commit()
                existing["replayed"] = True
                return existing
            tail = connection.execute(
                "SELECT berlin_date,sequence_no,day_sha256 FROM paper_days WHERE canary_id=? ORDER BY sequence_no DESC LIMIT 1",
                (day["canary_id"],),
            ).fetchone()
            if tail is None:
                sequence = 0
                previous = GENESIS_SHA
            else:
                expected_date = date.fromisoformat(tail["berlin_date"]) + timedelta(days=1)
                if day["berlin_date"] != expected_date.isoformat():
                    _fail("PAPER_DAY_NOT_CONSECUTIVE", f"{tail['berlin_date']}->{day['berlin_date']}")
                sequence = int(tail["sequence_no"]) + 1
                previous = tail["day_sha256"]
            envelope = {
                "schema_version": SCHEMA_VERSION,
                "sequence_no": sequence,
                "previous_day_sha256": previous,
                "day": day,
            }
            day_sha = canonical_sha(envelope)
            envelope["day_sha256"] = day_sha
            connection.execute(
                "INSERT INTO paper_days(canary_id,berlin_date,sequence_no,previous_day_sha256,day_sha256,day_json) VALUES(?,?,?,?,?,?)",
                (day["canary_id"], day["berlin_date"], sequence, previous, day_sha, canonical_json(envelope)),
            )
            connection.commit()
            envelope["replayed"] = False
            return envelope

    def append_drill(self, value: dict[str, Any], *, now_ms: int) -> dict[str, Any]:
        drill = normalize_drill(value, now_ms=now_ms)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT drill_json FROM paper_drills WHERE canary_id=? AND drill_id=?",
                (drill["canary_id"], drill["drill_id"]),
            ).fetchone()
            if prior is not None:
                existing = json.loads(prior["drill_json"])
                if existing["drill_sha256"] != drill["drill_sha256"]:
                    _fail("DRILL_IDEMPOTENCY_CONFLICT", drill["drill_id"])
                connection.commit()
                existing["replayed"] = True
                return existing
            connection.execute(
                "INSERT INTO paper_drills(canary_id,drill_id,drill_type,occurred_at_ms,drill_sha256,drill_json) VALUES(?,?,?,?,?,?)",
                (drill["canary_id"], drill["drill_id"], drill["drill_type"], drill["occurred_at_ms"], drill["drill_sha256"], canonical_json(drill)),
            )
            connection.commit()
            result = dict(drill)
            result["replayed"] = False
            return result

    def rows(self, canary_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return [json.loads(row["day_json"]) for row in connection.execute(
                "SELECT day_json FROM paper_days WHERE canary_id=? ORDER BY sequence_no", (canary_id,)
            )]

    def drills(self, canary_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return [json.loads(row["drill_json"]) for row in connection.execute(
                "SELECT drill_json FROM paper_drills WHERE canary_id=? ORDER BY occurred_at_ms,drill_id", (canary_id,)
            )]

    def evaluate(self, canary_id: str, policy_value: dict[str, Any]) -> dict[str, Any]:
        policy = normalize_policy(policy_value)
        envelopes = self.rows(canary_id)
        drills = self.drills(canary_id)
        blockers: list[str] = []
        previous = GENESIS_SHA
        expected_sequence = 0
        days: list[dict[str, Any]] = []
        for envelope in envelopes:
            supplied = envelope.get("day_sha256")
            computed = canonical_sha({key: child for key, child in envelope.items() if key != "day_sha256"})
            if supplied != computed:
                blockers.append("DAY_SHA_MISMATCH")
            if envelope.get("sequence_no") != expected_sequence:
                blockers.append("DAY_SEQUENCE_GAP")
            if envelope.get("previous_day_sha256") != previous:
                blockers.append("DAY_CHAIN_BROKEN")
            previous = supplied
            expected_sequence += 1
            days.append(envelope["day"])
        if len(days) < policy["minimum_calendar_days"]:
            blockers.append("MINIMUM_30_CALENDAR_DAYS_NOT_MET")
        if any(day["fixture_only"] for day in days):
            blockers.append("FIXTURE_DAY_FORBIDDEN")
        if any(not day["source_authority_verified"] for day in days):
            blockers.append("SOURCE_AUTHORITY_GAP")
        if sum(day["closed_positions"] for day in days) < policy["minimum_closed_positions"]:
            blockers.append("MINIMUM_CLOSED_POSITIONS_NOT_MET")
        if any(day["coverage_minutes"] < policy["minimum_daily_coverage_minutes"] for day in days):
            blockers.append("DAILY_COVERAGE_GAP")
        for field in ZERO_COUNT_FIELDS:
            if sum(day[field] for day in days) != 0:
                blockers.append(f"NONZERO_{field.upper()}")
        metric_limits = {
            "fee_delta_bps": policy["maximum_fee_delta_bps"],
            "slippage_delta_bps": policy["maximum_slippage_delta_bps"],
            "funding_delta_bps": policy["maximum_funding_delta_bps"],
            "latency_p95_ms": policy["maximum_latency_p95_ms"],
            "shadow_paper_net_delta_r": policy["maximum_shadow_paper_net_delta_r"],
        }
        for field, limit in metric_limits.items():
            if any(abs(day[field]) > limit for day in days):
                blockers.append(f"{field.upper()}_LIMIT")
        drill_types = {row["drill_type"] for row in drills if row.get("passed") is True}
        if "RESTART_RECOVERY" not in drill_types:
            blockers.append("RESTART_RECOVERY_DRILL_MISSING")
        if "ROLLBACK" not in drill_types:
            blockers.append("ROLLBACK_DRILL_MISSING")
        if days and drills:
            start = min(day["period_start_ms"] for day in days)
            end = max(day["period_end_ms"] for day in days)
            if any(not start <= row["occurred_at_ms"] <= end for row in drills):
                blockers.append("DRILL_OUTSIDE_CANARY_PERIOD")
        result = {
            "schema_version": "zel.paper_canary.gate.v1",
            "state": "PASS_P5_PAPER_30D_CANARY" if not blockers else "HOLD_P5_PAPER_30D_INCOMPLETE",
            "canary_id": canary_id,
            "calendar_day_count": len(days),
            "closed_position_count": sum(day["closed_positions"] for day in days),
            "restart_recovery_drill_pass": "RESTART_RECOVERY" in drill_types,
            "rollback_drill_pass": "ROLLBACK" in drill_types,
            "blockers": sorted(set(blockers)),
            "last_day_sha256": previous,
            "policy_sha256": canonical_sha(policy),
            "paper_only": True,
            "live_allowed": False,
            "capital_scale_allowed": False,
            "activation_allowed": False,
            "execution_authority": "PAPER_CANARY_ONLY",
            "order_authority": "PAPER_CANARY_ONLY",
        }
        result["result_sha256"] = canonical_sha(result)
        return result
