from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from backend.contracts.zel_micro_live_canary_v1 import (
    canonical_json,
    canonical_sha,
    normalize_approval,
    normalize_completion,
    normalize_policy,
)

SCHEMA_VERSION = "zel.micro_live.permit_registry.v1"


class MicroLivePermitError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise MicroLivePermitError(f"{code}:{detail}" if detail else code)


class MicroLivePermitRegistry:
    """Issues/consumes approval receipts only. It contains no exchange execution adapter."""

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
                CREATE TABLE IF NOT EXISTS micro_live_permits (
                    approval_id TEXT PRIMARY KEY,
                    nonce TEXT NOT NULL UNIQUE,
                    permit_sha256 TEXT NOT NULL UNIQUE,
                    approval_sha256 TEXT NOT NULL UNIQUE,
                    strategy_id TEXT NOT NULL,
                    family TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    issued_at_ms INTEGER NOT NULL,
                    expires_at_ms INTEGER NOT NULL,
                    consumed_at_ms INTEGER,
                    status TEXT NOT NULL,
                    permit_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS micro_live_completions (
                    canary_id TEXT PRIMARY KEY,
                    permit_sha256 TEXT NOT NULL UNIQUE,
                    completion_sha256 TEXT NOT NULL UNIQUE,
                    completion_json TEXT NOT NULL,
                    FOREIGN KEY(permit_sha256) REFERENCES micro_live_permits(permit_sha256)
                );
                """
            )

    def issue(self, approval_value: Mapping[str, Any], policy_value: Mapping[str, Any], *, now_ms: int) -> dict[str, Any]:
        policy = normalize_policy(policy_value)
        approval = normalize_approval(approval_value, policy, now_ms=now_ms)
        permit = {
            "schema_version": "zel.micro_live.permit.v1",
            "approval_id": approval["approval_id"],
            "approval_sha256": approval["approval_sha256"],
            "nonce": approval["nonce"],
            "issued_at_ms": approval["issued_at_ms"],
            "expires_at_ms": approval["expires_at_ms"],
            "strategy_id": approval["strategy_id"],
            "strategy_source_sha256": approval["strategy_source_sha256"],
            "family": approval["family"],
            "symbol": approval["symbol"],
            "side": approval["side"],
            "notional_usdt": approval["notional_usdt"],
            "leverage": approval["leverage"],
            "position_pct": approval["position_pct"],
            "planned_loss_r": approval["planned_loss_r"],
            "liquidation_buffer_pct": approval["liquidation_buffer_pct"],
            "funding_8h_pct": approval["funding_8h_pct"],
            "exposure_minutes": approval["exposure_minutes"],
            "concurrent_positions": 1,
            "add_allowed": False,
            "p5_result_sha256": approval["p5_result_sha256"],
            "risk_policy_sha256": policy["policy_sha256"],
            "private_api_scope_ref": approval["private_api_scope_ref"],
            "emergency_stop_receipt_sha256": approval["emergency_stop_receipt_sha256"],
            "rollback_receipt_sha256": approval["rollback_receipt_sha256"],
            "reconciliation_receipt_sha256": approval["reconciliation_receipt_sha256"],
            "one_time": True,
            "exchange_execution_performed": False,
            "live_execution_adapter_present": False,
            "capital_scale_allowed": False,
        }
        permit["permit_sha256"] = canonical_sha(permit)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT permit_json FROM micro_live_permits WHERE approval_id=?",
                (permit["approval_id"],),
            ).fetchone()
            if prior is not None:
                existing = json.loads(prior["permit_json"])
                if existing["permit_sha256"] != permit["permit_sha256"]:
                    _fail("APPROVAL_ID_CONFLICT", permit["approval_id"])
                connection.commit()
                existing["replayed"] = True
                return existing
            try:
                connection.execute(
                    """INSERT INTO micro_live_permits(
                    approval_id,nonce,permit_sha256,approval_sha256,strategy_id,family,symbol,side,
                    issued_at_ms,expires_at_ms,consumed_at_ms,status,permit_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        permit["approval_id"], permit["nonce"], permit["permit_sha256"],
                        permit["approval_sha256"], permit["strategy_id"], permit["family"],
                        permit["symbol"], permit["side"], permit["issued_at_ms"],
                        permit["expires_at_ms"], None, "ISSUED", canonical_json(permit),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                _fail("NONCE_OR_PERMIT_REPLAY_BLOCKED", str(exc))
            connection.commit()
        result = dict(permit)
        result["replayed"] = False
        return result

    def consume(self, permit_sha256: str, nonce: str, *, now_ms: int) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM micro_live_permits WHERE permit_sha256=?", (permit_sha256,)
            ).fetchone()
            if row is None:
                _fail("PERMIT_NOT_FOUND")
            if row["nonce"] != nonce:
                _fail("PERMIT_NONCE_MISMATCH")
            if not int(row["issued_at_ms"]) <= now_ms < int(row["expires_at_ms"]):
                _fail("PERMIT_EXPIRED_OR_NOT_CURRENT")
            if row["status"] != "ISSUED":
                _fail("PERMIT_ALREADY_CONSUMED")
            connection.execute(
                "UPDATE micro_live_permits SET status='CONSUMED',consumed_at_ms=? WHERE permit_sha256=? AND status='ISSUED'",
                (now_ms, permit_sha256),
            )
            if connection.total_changes != 1:
                _fail("PERMIT_CONSUME_RACE")
            connection.commit()
            permit = json.loads(row["permit_json"])
        request = {
            "schema_version": "zel.micro_live.activation_request.v1",
            "permit_sha256": permit_sha256,
            "consumed_at_ms": now_ms,
            "strategy_id": permit["strategy_id"],
            "strategy_source_sha256": permit["strategy_source_sha256"],
            "family": permit["family"],
            "symbol": permit["symbol"],
            "side": permit["side"],
            "notional_usdt": permit["notional_usdt"],
            "leverage": permit["leverage"],
            "position_pct": permit["position_pct"],
            "planned_loss_r": permit["planned_loss_r"],
            "private_api_scope_ref": permit["private_api_scope_ref"],
            "one_time": True,
            "add_allowed": False,
            "exchange_execution_performed": False,
            "live_execution_adapter_present": False,
            "capital_scale_allowed": False,
            "next_step": "SEPARATE_HUMAN_CONTROLLED_LIVE_ADAPTER_CANARY",
        }
        request["request_sha256"] = canonical_sha(request)
        return request

    def record_completion(self, value: Mapping[str, Any], policy_value: Mapping[str, Any]) -> dict[str, Any]:
        completion = normalize_completion(value, policy_value)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            permit = connection.execute(
                "SELECT * FROM micro_live_permits WHERE permit_sha256=?", (completion["permit_sha256"],)
            ).fetchone()
            if permit is None:
                _fail("PERMIT_NOT_FOUND")
            if permit["status"] != "CONSUMED" or permit["consumed_at_ms"] is None:
                _fail("PERMIT_NOT_CONSUMED")
            if completion["started_at_ms"] < int(permit["consumed_at_ms"]):
                _fail("COMPLETION_STARTED_BEFORE_PERMIT_CONSUMPTION")
            prior = connection.execute(
                "SELECT completion_json FROM micro_live_completions WHERE canary_id=?", (completion["canary_id"],)
            ).fetchone()
            if prior is not None:
                existing = json.loads(prior["completion_json"])
                if existing["completion_sha256"] != completion["completion_sha256"]:
                    _fail("COMPLETION_ID_CONFLICT")
                connection.commit()
                existing["replayed"] = True
                return existing
            connection.execute(
                "INSERT INTO micro_live_completions(canary_id,permit_sha256,completion_sha256,completion_json) VALUES(?,?,?,?)",
                (completion["canary_id"], completion["permit_sha256"], completion["completion_sha256"], canonical_json(completion)),
            )
            connection.commit()
        result = dict(completion)
        result["replayed"] = False
        return result

    def status(self, permit_sha256: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM micro_live_permits WHERE permit_sha256=?", (permit_sha256,)
            ).fetchone()
            return dict(row) if row is not None else None
