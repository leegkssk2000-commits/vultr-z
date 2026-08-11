from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from backend.production.zel_production_owner_binding_v1 import ProductionEventLedger, run_cycle, stable_sha

SCHEMA = "zel.production_auto_cycle_supervisor.v1"
FINAL_STATES = {"COMPLETED", "HOLD", "FAILED"}


@dataclass(frozen=True)
class SupervisorPolicy:
    lease_ttl_s: float = 30.0
    max_attempts: int = 2
    retry_backoff_s: float = 0.05
    retry_budget_s: float = 5.0
    min_evidence_samples: int = 30
    min_score_gain: float = 0.0
    max_dd_regression_pct: float = 0.0
    error_budget: int = 0
    allowlisted_knobs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.lease_ttl_s <= 0:
            raise ValueError("lease_ttl_s must be > 0")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.retry_backoff_s < 0 or self.retry_budget_s < 0:
            raise ValueError("retry timing must be >= 0")
        if self.min_evidence_samples < 1:
            raise ValueError("min_evidence_samples must be >= 1")
        if self.error_budget < 0:
            raise ValueError("error_budget must be >= 0")


class SupervisorStateStore:
    """Durable single-flight lease, receipt replay, and reason counters."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS supervisor_cycles (
                    cycle_key TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at REAL NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_reason TEXT NOT NULL DEFAULT '',
                    receipt_json TEXT,
                    updated_at REAL NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS supervisor_reason_counts (
                    reason TEXT PRIMARY KEY,
                    count INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30.0)
        db.row_factory = sqlite3.Row
        return db

    def claim(self, cycle_key: str, owner: str, now: float, lease_ttl_s: float) -> dict[str, Any]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM supervisor_cycles WHERE cycle_key=?", (cycle_key,)
            ).fetchone()
            if row is not None and row["receipt_json"]:
                receipt = json.loads(row["receipt_json"])
                db.commit()
                return {"kind": "REPLAY", "receipt": receipt}
            if row is not None and row["state"] == "RUNNING" and float(row["lease_expires_at"]) > now:
                db.commit()
                return {
                    "kind": "BUSY",
                    "lease_expires_at": float(row["lease_expires_at"]),
                    "lease_owner": row["lease_owner"],
                }
            expires = now + lease_ttl_s
            if row is None:
                db.execute(
                    """
                    INSERT INTO supervisor_cycles(
                        cycle_key,state,lease_owner,lease_expires_at,attempts,last_reason,receipt_json,updated_at
                    ) VALUES(?,?,?,?,0,'',NULL,?)
                    """,
                    (cycle_key, "RUNNING", owner, expires, now),
                )
                stale_recovered = False
            else:
                stale_recovered = row["state"] == "RUNNING" and float(row["lease_expires_at"]) <= now
                db.execute(
                    """
                    UPDATE supervisor_cycles
                    SET state='RUNNING', lease_owner=?, lease_expires_at=?, receipt_json=NULL, updated_at=?
                    WHERE cycle_key=?
                    """,
                    (owner, expires, now, cycle_key),
                )
            db.commit()
            return {"kind": "CLAIMED", "stale_recovered": stale_recovered, "lease_expires_at": expires}

    def heartbeat(self, cycle_key: str, owner: str, now: float, lease_ttl_s: float, attempts: int) -> None:
        with self._connect() as db:
            cursor = db.execute(
                """
                UPDATE supervisor_cycles
                SET lease_expires_at=?, attempts=?, updated_at=?
                WHERE cycle_key=? AND state='RUNNING' AND lease_owner=?
                """,
                (now + lease_ttl_s, attempts, now, cycle_key, owner),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("SUPERVISOR_LEASE_LOST")
            db.commit()

    def finish(self, cycle_key: str, owner: str, state: str, reason: str, receipt: Mapping[str, Any], now: float) -> None:
        if state not in FINAL_STATES:
            raise ValueError(f"INVALID_FINAL_STATE:{state}")
        encoded = json.dumps(dict(receipt), sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                """
                UPDATE supervisor_cycles
                SET state=?, lease_owner=NULL, lease_expires_at=0, last_reason=?, receipt_json=?, updated_at=?
                WHERE cycle_key=? AND state='RUNNING' AND lease_owner=?
                """,
                (state, reason, encoded, now, cycle_key, owner),
            )
            if cursor.rowcount != 1:
                db.rollback()
                raise RuntimeError("SUPERVISOR_LEASE_LOST")
            db.commit()

    def record_reason(self, reason: str, now: float) -> None:
        if not reason:
            return
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO supervisor_reason_counts(reason,count,updated_at) VALUES(?,1,?)
                ON CONFLICT(reason) DO UPDATE SET count=count+1, updated_at=excluded.updated_at
                """,
                (reason, now),
            )
            db.commit()

    def reason_counts(self) -> dict[str, int]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT reason,count FROM supervisor_reason_counts ORDER BY count DESC, reason"
            ).fetchall()
        return {str(row["reason"]): int(row["count"]) for row in rows}

    def cycle(self, cycle_key: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM supervisor_cycles WHERE cycle_key=?", (cycle_key,)).fetchone()
        return None if row is None else dict(row)


def cycle_key_for(payload: Mapping[str, Any]) -> str:
    explicit = str(payload.get("cycle_id") or "").strip()
    if explicit:
        return explicit
    material = {
        "mode": payload.get("mode"),
        "symbol": payload.get("symbol"),
        "strategy_id": payload.get("strategy_id"),
        "alpha_id": payload.get("alpha_id"),
        "signal": payload.get("signal"),
        "signal_ts": payload.get("signal_ts"),
        "position_id": payload.get("position_id"),
        "event_id": payload.get("event_id"),
        "decision_id": payload.get("decision_id"),
        "price": payload.get("price"),
        "qty": payload.get("qty"),
    }
    return stable_sha(material)


def _f(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def evaluate_improvement(evidence: Mapping[str, Any] | None, policy: SupervisorPolicy) -> dict[str, Any]:
    """Evaluate candidate evidence only; never mutates strategy or code."""

    if not isinstance(evidence, Mapping):
        return {
            "state": "HOLD",
            "action": "hold",
            "reason": "INSUFFICIENT_IMPROVEMENT_EVIDENCE",
            "promotion_allowed": False,
            "rollback_required": False,
            "strategy_mutation_applied": False,
            "self_modification_applied": False,
        }

    candidate = evidence.get("candidate")
    candidate = dict(candidate) if isinstance(candidate, Mapping) else {}
    knobs = candidate.get("knobs")
    knobs = dict(knobs) if isinstance(knobs, Mapping) else {}
    disallowed = sorted(set(knobs) - set(policy.allowlisted_knobs))
    candidate_hash = stable_sha(candidate) if candidate else None
    base = {
        "candidate_id": candidate.get("candidate_id"),
        "candidate_hash": candidate_hash,
        "incumbent_id": evidence.get("incumbent_id"),
        "incumbent_hash": evidence.get("incumbent_hash"),
        "promotion_allowed": False,
        "rollback_required": False,
        "strategy_mutation_applied": False,
        "self_modification_applied": False,
        "disallowed_knobs": disallowed,
    }
    if disallowed:
        return {**base, "state": "HOLD", "action": "hold", "reason": "CANDIDATE_KNOB_NOT_ALLOWLISTED"}

    required = (
        "sample_count",
        "candidate_score",
        "incumbent_score",
        "candidate_max_dd_pct",
        "incumbent_max_dd_pct",
        "error_count",
    )
    if any(key not in evidence for key in required):
        return {**base, "state": "HOLD", "action": "hold", "reason": "INSUFFICIENT_IMPROVEMENT_EVIDENCE"}

    sample_count = int(evidence["sample_count"])
    error_count = int(evidence["error_count"])
    candidate_score = _f(evidence["candidate_score"])
    incumbent_score = _f(evidence["incumbent_score"])
    candidate_dd = _f(evidence["candidate_max_dd_pct"])
    incumbent_dd = _f(evidence["incumbent_max_dd_pct"])
    if sample_count < policy.min_evidence_samples:
        return {**base, "state": "HOLD", "action": "hold", "reason": "EVIDENCE_SAMPLE_BELOW_GATE"}

    regression_reason = ""
    if error_count > policy.error_budget:
        regression_reason = "ERROR_BUDGET_EXCEEDED"
    elif candidate_score < incumbent_score + policy.min_score_gain:
        regression_reason = "CANDIDATE_SCORE_NOT_BETTER"
    elif candidate_dd > incumbent_dd + policy.max_dd_regression_pct:
        regression_reason = "CANDIDATE_DD_REGRESSION"

    if regression_reason:
        promoted = bool(evidence.get("promoted", False))
        return {
            **base,
            "state": "ROLLBACK_REQUIRED" if promoted else "HOLD",
            "action": "rollback" if promoted else "hold",
            "reason": regression_reason,
            "rollback_required": promoted,
        }

    return {
        **base,
        "state": "PROMOTION_ELIGIBLE",
        "action": "hold",
        "reason": "EVIDENCE_GATE_PASS",
        "promotion_allowed": True,
    }


class ProductionAutoCycleSupervisor:
    def __init__(
        self,
        state_path: str | Path,
        *,
        policy: SupervisorPolicy | None = None,
        run_fn: Callable[[Mapping[str, Any], ProductionEventLedger], dict[str, Any]] = run_cycle,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.store = SupervisorStateStore(state_path)
        self.policy = policy or SupervisorPolicy()
        self.run_fn = run_fn
        self.clock = clock
        self.sleeper = sleeper

    def supervise(self, payload: Mapping[str, Any], ledger: ProductionEventLedger) -> dict[str, Any]:
        key = cycle_key_for(payload)
        owner = uuid.uuid4().hex
        started = self.clock()
        claim = self.store.claim(key, owner, started, self.policy.lease_ttl_s)
        if claim["kind"] == "REPLAY":
            receipt = dict(claim["receipt"])
            receipt["replayed"] = True
            return receipt
        if claim["kind"] == "BUSY":
            return {
                "schema_version": SCHEMA,
                "cycle_key": key,
                "state": "HOLD",
                "action": "hold",
                "reason": "SINGLE_FLIGHT_ACTIVE",
                "lease_expires_at": claim["lease_expires_at"],
                "replayed": False,
                "exchange_order_submitted": False,
                "strategy_mutation_applied": False,
                "self_modification_applied": False,
            }

        attempts = 0
        result: dict[str, Any] | None = None
        last_error = ""
        while attempts < self.policy.max_attempts:
            attempts += 1
            now = self.clock()
            self.store.heartbeat(key, owner, now, self.policy.lease_ttl_s, attempts)
            try:
                result = self.run_fn(payload, ledger)
                break
            except (KeyError, ValueError) as exc:
                last_error = f"{type(exc).__name__}:{exc}"
                break
            except RuntimeError as exc:
                last_error = f"{type(exc).__name__}:{exc}"
                if attempts >= self.policy.max_attempts:
                    break
                if self.clock() - started + self.policy.retry_backoff_s > self.policy.retry_budget_s:
                    last_error = "RETRY_BUDGET_EXHAUSTED:" + last_error
                    break
                if self.policy.retry_backoff_s:
                    self.sleeper(self.policy.retry_backoff_s)

        finished = self.clock()
        improvement = evaluate_improvement(payload.get("improvement_evidence"), self.policy)
        if result is None:
            reason = last_error or "CYCLE_EXECUTION_FAILED"
            self.store.record_reason(reason, finished)
            receipt = {
                "schema_version": SCHEMA,
                "cycle_key": key,
                "state": "FAILED",
                "action": "hold",
                "reason": reason,
                "attempts": attempts,
                "stale_lease_recovered": bool(claim.get("stale_recovered", False)),
                "elapsed_ms": max(0.0, (finished - started) * 1000.0),
                "improvement": improvement,
                "replayed": False,
                "exchange_order_submitted": False,
                "strategy_mutation_applied": False,
                "self_modification_applied": False,
            }
            receipt["receipt_sha256"] = stable_sha(receipt)
            self.store.finish(key, owner, "FAILED", reason, receipt, finished)
            return receipt

        decision = dict(result.get("decision") or {})
        decision_state = str(decision.get("state") or "UNKNOWN")
        reason = str(decision.get("reason") or "CYCLE_COMPLETE")
        if decision_state in {"HOLD", "BLOCKED", "STOPPED"}:
            final_state = "HOLD"
            action = str(decision.get("action") or "hold")
            self.store.record_reason(reason, finished)
        else:
            final_state = "COMPLETED"
            action = str(decision.get("action") or "hold")

        receipt = {
            "schema_version": SCHEMA,
            "cycle_key": key,
            "state": final_state,
            "action": action,
            "reason": reason,
            "attempts": attempts,
            "stale_lease_recovered": bool(claim.get("stale_recovered", False)),
            "elapsed_ms": max(0.0, (finished - started) * 1000.0),
            "result": result,
            "improvement": improvement,
            "reason_counts": self.store.reason_counts(),
            "replayed": False,
            "exchange_order_submitted": False,
            "strategy_mutation_applied": False,
            "self_modification_applied": False,
        }
        receipt["receipt_sha256"] = stable_sha(receipt)
        self.store.finish(key, owner, final_state, reason, receipt, finished)
        return receipt
