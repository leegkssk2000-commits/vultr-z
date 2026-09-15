"""Research-only campaign claims and evidence gates; never executes a strategy.

The integrator supplies explicit budgets and is the only ledger owner. A claim
must return ``new=True`` and ``start`` must return True before economic work.
Legacy receipts retain their original facts without receiving canonical IDs.
"""

from __future__ import annotations

import hashlib
import json
import math
import operator
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _hash(value: str) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


@dataclass(frozen=True)
class CandidateIdentity:
    candidate_id: str
    strategy_id: str
    baseline_id: str
    changed_axis: str
    rule_sha256: str
    data_sha256: str
    cost_sha256: str
    window_sha256: str

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"IDENTITY_MISSING:{name}")
            if name.endswith("sha256") and not _hash(value):
                raise ValueError(f"IDENTITY_HASH_INVALID:{name}")

    @property
    def key(self) -> str:
        # Cosmetic renaming and changing scope cannot reset a previous failure.
        value = asdict(self)
        value.pop("candidate_id")
        return digest(value)


class CampaignLedger:
    """SQLite transaction boundary for one owner's bounded research campaign."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS scopes (
                    scope TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    max_candidates INTEGER NOT NULL, max_executions INTEGER NOT NULL,
                    contract_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS claims (
                    identity_key TEXT PRIMARY KEY, scope TEXT NOT NULL,
                    candidate_id TEXT NOT NULL, identity_json TEXT NOT NULL,
                    state TEXT NOT NULL, result_json TEXT,
                    UNIQUE(scope, candidate_id), FOREIGN KEY(scope) REFERENCES scopes(scope));
                CREATE TABLE IF NOT EXISTS closes (
                    identity_key TEXT NOT NULL, close_id TEXT NOT NULL,
                    receipt_json TEXT NOT NULL, PRIMARY KEY(identity_key, close_id),
                    FOREIGN KEY(identity_key) REFERENCES claims(identity_key));
                CREATE TABLE IF NOT EXISTS legacy (
                    receipt_sha256 TEXT PRIMARY KEY, receipt_json TEXT NOT NULL,
                    identity_state TEXT NOT NULL CHECK(identity_state='legacy_no_canonical_id'));
                CREATE TABLE IF NOT EXISTS legacy_sources (
                    scope TEXT NOT NULL, source TEXT NOT NULL, receipt_sha256 TEXT NOT NULL,
                    PRIMARY KEY(scope, source, receipt_sha256),
                    FOREIGN KEY(scope) REFERENCES scopes(scope),
                    FOREIGN KEY(receipt_sha256) REFERENCES legacy(receipt_sha256));
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL, identity_key TEXT, event TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
                """
            )

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _owner(db: sqlite3.Connection, scope: str, owner: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM scopes WHERE scope=?", (scope,)).fetchone()
        if row is None or row["owner"] != owner:
            raise PermissionError("SINGLE_OWNER_REQUIRED")
        return row

    @staticmethod
    def _event(
        db: sqlite3.Connection, scope: str, key: str | None, event: str, value: Any
    ) -> None:
        db.execute(
            "INSERT INTO events(scope, identity_key, event, payload_json) VALUES(?,?,?,?)",
            (scope, key, event, canonical(value)),
        )

    def create_scope(
        self,
        scope: str,
        owner: str,
        max_candidates: int,
        max_executions: int,
        contract: Mapping[str, Any],
    ) -> bool:
        if not scope.strip() or not owner.strip():
            raise ValueError("SCOPE_AND_OWNER_REQUIRED")
        if any(type(x) is not int or x < 0 for x in (max_candidates, max_executions)):
            raise ValueError("EXPLICIT_NONNEGATIVE_BUDGET_REQUIRED")
        values = (
            scope,
            owner,
            max_candidates,
            max_executions,
            canonical(dict(contract)),
        )
        with self._transaction() as db:
            old = db.execute("SELECT * FROM scopes WHERE scope=?", (scope,)).fetchone()
            if old is not None:
                if tuple(old) != values:
                    raise ValueError("IMMUTABLE_SCOPE_CONFLICT")
                return False
            db.execute("INSERT INTO scopes VALUES(?,?,?,?,?)", values)
            self._event(db, scope, None, "SCOPE_CREATED", dict(contract))
            return True

    def reserve(
        self, scope: str, owner: str, identity: CandidateIdentity
    ) -> dict[str, Any]:
        key = identity.key
        with self._transaction() as db:
            limits = self._owner(db, scope, owner)
            named = db.execute(
                "SELECT * FROM claims WHERE scope=? AND candidate_id=?",
                (scope, identity.candidate_id),
            ).fetchone()
            if named is not None and named["identity_key"] != key:
                raise ValueError("IMMUTABLE_CANDIDATE_CONFLICT")
            old = db.execute(
                "SELECT * FROM claims WHERE identity_key=?", (key,)
            ).fetchone()
            if old is not None:
                return {"new": False, **dict(old)}
            count = db.execute(
                "SELECT count(*) FROM claims WHERE scope=?", (scope,)
            ).fetchone()[0]
            if count >= limits["max_candidates"]:
                raise ValueError("CANDIDATE_BUDGET_EXHAUSTED")
            value = canonical(asdict(identity))
            db.execute(
                "INSERT INTO claims VALUES(?,?,?,?,?,NULL)",
                (key, scope, identity.candidate_id, value, "RESERVED"),
            )
            self._event(db, scope, key, "RESERVED", asdict(identity))
            return {"new": True, "identity_key": key, "state": "RESERVED"}

    def _claim(self, db: sqlite3.Connection, key: str, owner: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM claims WHERE identity_key=?", (key,)).fetchone()
        if row is None:
            raise KeyError("CLAIM_NOT_FOUND")
        self._owner(db, row["scope"], owner)
        return row

    def start(self, key: str, owner: str) -> bool:
        with self._transaction() as db:
            row = self._claim(db, key, owner)
            if row["state"] != "RESERVED":
                return False
            scope = row["scope"]
            limits = self._owner(db, scope, owner)
            count = db.execute(
                "SELECT count(*) FROM events WHERE scope=? AND event='STARTED'",
                (scope,),
            ).fetchone()[0]
            if count >= limits["max_executions"]:
                raise ValueError("EXECUTION_BUDGET_EXHAUSTED")
            db.execute("UPDATE claims SET state='RUNNING' WHERE identity_key=?", (key,))
            self._event(db, scope, key, "STARTED", {})
            return True

    def finish(
        self, key: str, owner: str, state: str, receipt: Mapping[str, Any]
    ) -> bool:
        if state not in {"COMPLETED", "REJECTED", "FAILED", "HOLD"}:
            raise ValueError("TERMINAL_STATE_INVALID")
        value = canonical(dict(receipt))
        with self._transaction() as db:
            row = self._claim(db, key, owner)
            if row["state"] not in {"RESERVED", "RUNNING"}:
                if row["state"] == state and row["result_json"] == value:
                    return False
                raise ValueError("IMMUTABLE_TERMINAL_CONFLICT")
            if row["state"] == "RESERVED" and state not in {"REJECTED", "HOLD"}:
                raise ValueError("EXECUTION_NOT_STARTED")
            db.execute(
                "UPDATE claims SET state=?, result_json=? WHERE identity_key=?",
                (state, value, key),
            )
            self._event(db, row["scope"], key, state, dict(receipt))
            return True

    def record_close(
        self, key: str, owner: str, close_id: str, receipt: Mapping[str, Any]
    ) -> bool:
        if not close_id.strip():
            raise ValueError("CLOSE_ID_REQUIRED")
        value = canonical(dict(receipt))
        with self._transaction() as db:
            row = self._claim(db, key, owner)
            old = db.execute(
                "SELECT receipt_json FROM closes WHERE identity_key=? AND close_id=?",
                (key, close_id),
            ).fetchone()
            if old is not None:
                if old[0] != value:
                    raise ValueError("IMMUTABLE_CLOSE_CONFLICT")
                return False
            if row["state"] != "RUNNING":
                raise ValueError("CLOSE_REQUIRES_RUNNING_CLAIM")
            db.execute("INSERT INTO closes VALUES(?,?,?)", (key, close_id, value))
            self._event(db, row["scope"], key, "CLOSE_RECORDED", {"close_id": close_id})
            return True

    def ingest_legacy(
        self, scope: str, owner: str, source: str, receipt: Mapping[str, Any]
    ) -> dict[str, Any]:
        if not source.strip():
            raise ValueError("LEGACY_SOURCE_REQUIRED")
        value = canonical(dict(receipt))
        key = digest(dict(receipt))
        with self._transaction() as db:
            self._owner(db, scope, owner)
            inserted = (
                db.execute(
                    "INSERT OR IGNORE INTO legacy VALUES(?,?,'legacy_no_canonical_id')",
                    (key, value),
                ).rowcount
                == 1
            )
            db.execute(
                "INSERT OR IGNORE INTO legacy_sources VALUES(?,?,?)",
                (scope, source, key),
            )
            if inserted:
                self._event(
                    db,
                    scope,
                    None,
                    "LEGACY_INGESTED",
                    {"source": source, "receipt_sha256": key},
                )
            return {
                "new": inserted,
                "receipt_sha256": key,
                "identity_state": "legacy_no_canonical_id",
            }

    def status(self, scope: str) -> dict[str, Any]:
        with self._db() as db:
            counts = {
                r[0]: r[1]
                for r in db.execute(
                    "SELECT state,count(*) FROM claims WHERE scope=? GROUP BY state",
                    (scope,),
                )
            }
            started = db.execute(
                "SELECT count(*) FROM events WHERE scope=? AND event='STARTED'",
                (scope,),
            ).fetchone()[0]
            return {
                "scope": scope,
                "claims": counts,
                "executions_started": started,
                "order_authority": "BLOCKED",
                "live_authority": "BLOCKED",
            }


@dataclass(frozen=True)
class GateDecision:
    state: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class MaterialPolicy:
    materials: Mapping[str, Mapping[str, Any]]
    cost_floor_bps: float
    minimum_trades: int
    minimum_pf_exclusive: float
    cosine_threshold: float
    max_rounds: int
    source_sha256: str

    @classmethod
    def load(cls, directory: str | Path) -> MaterialPolicy:
        directory = Path(directory)
        policy = json.loads(
            (directory / "economic_material_policy_v2.json").read_text()
        )
        program = json.loads(
            (directory / "material_upgrade_program_v3_results.json").read_text()
        )
        gates = program["host_touch_gate"]["required"]
        # Read explicit existing contract values; unknown gate text fails closed.
        t_values = [int(x[3:]) for x in gates if re.fullmatch(r"T>=\d+", x)]
        pf_values = [
            float(x[3:]) for x in gates if re.fullmatch(r"PF>\d+(?:\.\d+)?", x)
        ]
        if len(t_values) != 1 or len(pf_values) != 1:
            raise ValueError("SSOT_NUMERIC_GATE_MISSING")
        upgrade = policy["upgrade_rules"]
        return cls(
            {x["strategy_id"]: x for x in program["materials"]},
            float(upgrade["realistic_cost_bps"]),
            t_values[0],
            pf_values[0],
            float(upgrade["dedup_cosine_threshold"]),
            int(upgrade["max_rounds_per_material"]),
            digest({"policy": policy, "program": program}),
        )


ROLES = {
    "entry_quality",
    "context_filter_or_veto",
    "exit_or_risk",
    "execution/microstructure",
}


def _role(value: Any) -> str:
    return str(value).removesuffix("_material")


def material_attempt_gate(
    policy: MaterialPolicy,
    material_id: str,
    role: str,
    stage: str,
    changed_axes: int,
    round_number: int,
) -> GateDecision:
    row = policy.materials.get(material_id)
    if row is None:
        return GateDecision("HOLD", ("UNKNOWN_MATERIAL",))
    if role not in ROLES or stage not in {
        "source_completion",
        "marginal_ablation",
        "standalone_grade_up",
    }:
        return GateDecision("BLOCKED", ("ROLE_OR_STAGE_INVALID",))
    if type(changed_axes) is not int or changed_axes != 1:
        return GateDecision("BLOCKED", ("ONE_CHANGED_AXIS_REQUIRED",))
    if type(round_number) is not int or not 1 <= round_number <= policy.max_rounds:
        return GateDecision("BLOCKED", ("ROUND_BUDGET_EXCEEDED",))
    grade = row["material_grade"]
    if grade == "HOLD":
        return GateDecision(
            "ELIGIBLE" if stage == "source_completion" else "HOLD",
            ("SOURCE_EXECUTION_SAMPLE_COMPLETION_ONLY",),
        )
    if grade == "D":
        if stage != "marginal_ablation" or role not in {
            "context_filter_or_veto",
            "exit_or_risk",
        }:
            return GateDecision("BLOCKED", ("D_CANNOT_CREATE_ENTRIES",))
    elif role != _role(row["role"]):
        return GateDecision("BLOCKED", ("FROZEN_MATERIAL_ROLE_CONFLICT",))
    return GateDecision("ELIGIBLE", ())


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _bound_json(reference: Any) -> dict[str, Any] | None:
    if not isinstance(reference, dict) or not isinstance(reference.get("path"), str):
        return None
    try:
        raw = Path(reference["path"]).read_bytes()
        if (
            not _hash(reference.get("sha256", ""))
            or hashlib.sha256(raw).hexdigest() != reference["sha256"]
        ):
            return None
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except (OSError, TypeError, ValueError):
        return None


def _marginal_acceptance_gate(receipt: Mapping[str, Any]) -> GateDecision:
    """Apply explicit preregistered comparisons, never synthesize grade criteria."""
    pending = GateDecision("HOLD", ("HOLD_REQUIRES_PREREG_MARGINAL_ACCEPTANCE",))
    policy = _bound_json(receipt.get("marginal_acceptance"))
    if policy is None or policy.get("state") != "FROZEN_PREREGISTRATION":
        return pending
    source = policy.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("path"), str):
        return pending
    try:
        raw_source = Path(source["path"]).read_bytes()
        if (
            not _hash(source.get("sha256", ""))
            or hashlib.sha256(raw_source).hexdigest() != source["sha256"]
        ):
            return pending
        frozen_at = datetime.fromisoformat(policy["frozen_at"].replace("Z", "+00:00"))
        execution_at = datetime.fromisoformat(
            receipt["execution_started_at"].replace("Z", "+00:00")
        )
        if (
            frozen_at.tzinfo is None
            or execution_at.tzinfo is None
            or frozen_at >= execution_at
        ):
            return pending
    except (OSError, KeyError, TypeError, ValueError, AttributeError):
        return pending
    if policy.get("subject_id") != receipt.get(
        "material_id", receipt.get("composite_id")
    ) or not policy.get("subject_id"):
        return pending
    for key in ("rule_sha256", "data_sha256", "cost_sha256", "window_sha256"):
        if not _hash(policy.get(key, "")) or policy[key] != receipt.get(key):
            return pending
    requirements = policy.get("requirements")
    metrics = receipt.get("metrics")
    if (
        not isinstance(requirements, list)
        or not requirements
        or not isinstance(metrics, dict)
    ):
        return pending
    comparisons = {
        ">": operator.gt,
        ">=": operator.ge,
        "<": operator.lt,
        "<=": operator.le,
        "==": operator.eq,
    }
    allowed = {
        "marginal_net_bps",
        "delta_pf",
        "dd_improvement_bps",
        "winner_preservation",
        "t_retention",
        "max_loss_streak",
    }
    for requirement in requirements:
        if not isinstance(requirement, dict):
            return pending
        name, comparison = requirement.get("metric"), requirement.get("op")
        if (
            not isinstance(name, str)
            or name not in allowed
            or not isinstance(comparison, str)
            or comparison not in comparisons
        ):
            return pending
        actual, threshold = _number(metrics.get(name)), _number(
            requirement.get("value")
        )
        if actual is None or threshold is None:
            return pending
        if not comparisons[comparison](actual, threshold):
            return GateDecision("BLOCKED", ("PREREG_MARGINAL_ACCEPTANCE_FAILED",))
    return GateDecision(
        "ELIGIBLE", ("RESEARCH_REVIEW_ELIGIBILITY_ONLY_NO_GRADE_OR_CORE_PROMOTION",)
    )


def verified_material_receipt(
    path: str | Path,
    expected_sha256: str,
    policy: MaterialPolicy,
) -> tuple[GateDecision, dict[str, Any] | None]:
    """Validate a saved B/A receipt's binding and explicit gates, without rescore."""
    try:
        raw = Path(path).read_bytes()
        if (
            not _hash(expected_sha256)
            or hashlib.sha256(raw).hexdigest() != expected_sha256
        ):
            return GateDecision("HOLD", ("RECEIPT_HASH_MISMATCH",)), None
        row = json.loads(raw)
        if not isinstance(row, dict):
            return GateDecision("HOLD", ("RECEIPT_SCHEMA_INVALID",)), None
    except (OSError, ValueError, TypeError):
        return GateDecision("HOLD", ("RECEIPT_UNREADABLE",)), None
    if row.get("material_id") not in policy.materials or row.get("grade") not in {
        "B",
        "A",
    }:
        return GateDecision("HOLD", ("VERIFIED_B_A_REQUIRED",)), None
    if row.get("role") not in ROLES or row.get("integrity") != "PASS":
        return GateDecision("HOLD", ("ROLE_OR_INTEGRITY_INVALID",)), None
    baseline = policy.materials[row["material_id"]]
    if baseline["material_grade"] == "D":
        allowed_roles = {"context_filter_or_veto", "exit_or_risk"}
    elif baseline["material_grade"] == "HOLD":
        if not _hash(row.get("source_completion_sha256", "")):
            return GateDecision("HOLD", ("SOURCE_COMPLETION_RECEIPT_REQUIRED",)), None
        allowed_roles = {_role(baseline["role"])}
        if row["material_id"] in {"scalp_snap", "liquidity_sweep"}:
            allowed_roles = {"execution/microstructure"}
    else:
        allowed_roles = {_role(baseline["role"])}
    if row["role"] not in allowed_roles:
        return GateDecision("BLOCKED", ("FROZEN_MATERIAL_ROLE_CONFLICT",)), None
    if any(
        not _hash(row.get(k, ""))
        for k in ("rule_sha256", "data_sha256", "cost_sha256", "window_sha256")
    ):
        return GateDecision("HOLD", ("EVIDENCE_BINDING_MISSING",)), None
    if row.get("fresh_forward") is not True:
        return GateDecision("HOLD", ("FRESH_FORWARD_REQUIRED",)), None
    metrics = row.get("metrics")
    required = (
        "net_bps",
        "pf",
        "t",
        "dd_bps",
        "reference_dd_bps",
        "reference_net_bps",
        "reference_pf",
        "reference_t",
        "cost_bps_T",
        "marginal_net_bps",
        "delta_pf",
        "dd_improvement_bps",
        "winner_preservation",
        "t_retention",
        "max_loss_streak",
    )
    if not isinstance(metrics, dict) or any(
        _number(metrics.get(k)) is None for k in required
    ):
        return GateDecision("HOLD", ("FINITE_METRICS_REQUIRED",)), None
    if any(
        metrics[k] < 0 for k in ("dd_bps", "reference_dd_bps", "max_loss_streak")
    ) or any(not 0 <= metrics[k] <= 1 for k in ("winner_preservation", "t_retention")):
        return GateDecision("HOLD", ("METRIC_UNITS_INVALID",)), None
    if type(metrics["t"]) is not int or metrics["t"] < policy.minimum_trades:
        return GateDecision("HOLD", ("SAMPLE_GATE_NOT_MET",)), None
    if metrics["cost_bps_T"] < policy.cost_floor_bps:
        return GateDecision("HOLD", ("COST_AUTHORITY_BELOW_SSOT",)), None
    if (
        metrics["net_bps"] <= 0
        or metrics["pf"] <= policy.minimum_pf_exclusive
        or metrics["dd_bps"] >= metrics["reference_dd_bps"]
    ):
        return GateDecision("BLOCKED", ("ABSOLUTE_ECONOMIC_GATE_FAILED",)), None
    if type(metrics["reference_t"]) is not int or metrics["reference_t"] <= 0:
        return GateDecision("HOLD", ("REFERENCE_SAMPLE_INVALID",)), None
    deltas = {
        "marginal_net_bps": metrics["net_bps"] - metrics["reference_net_bps"],
        "delta_pf": metrics["pf"] - metrics["reference_pf"],
        "dd_improvement_bps": metrics["reference_dd_bps"] - metrics["dd_bps"],
        "t_retention": metrics["t"] / metrics["reference_t"],
    }
    if any(
        not math.isclose(metrics[key], expected, rel_tol=1e-9, abs_tol=1e-9)
        for key, expected in deltas.items()
    ):
        return GateDecision("HOLD", ("MARGINAL_METRICS_INCONSISTENT",)), None
    acceptance = _marginal_acceptance_gate(row)
    if acceptance.state != "ELIGIBLE":
        return acceptance, None
    if row.get("changed_axes") != 1:
        return GateDecision("BLOCKED", ("ONE_CHANGED_AXIS_REQUIRED",)), None
    return acceptance, {
        **row,
        "verified_receipt_sha256": expected_sha256,
    }


def fusion_gate(
    policy: MaterialPolicy,
    receipts: list[tuple[str | Path, str]],
    behavior_cosine: float | None,
    changed_axes: int,
) -> GateDecision:
    if len(receipts) != 2:
        return GateDecision("BLOCKED", ("TWO_VERIFIED_MATERIALS_REQUIRED",))
    if type(changed_axes) is not int or not 1 <= changed_axes <= 2:
        return GateDecision("BLOCKED", ("MAX_TWO_NEW_AXES",))
    cosine = _number(behavior_cosine)
    if cosine is None or not -1 <= cosine <= 1:
        return GateDecision("HOLD", ("BEHAVIOR_COSINE_MISSING_OR_INVALID",))
    if cosine > policy.cosine_threshold:
        return GateDecision("BLOCKED", ("DUPLICATE_BEHAVIOR",))
    rows: list[dict[str, Any]] = []
    for path, sha in receipts:
        decision, row = verified_material_receipt(path, sha, policy)
        if row is None:
            return decision
        rows.append(row)
    if (
        rows[0]["material_id"] == rows[1]["material_id"]
        or rows[0]["role"] == rows[1]["role"]
    ):
        return GateDecision("BLOCKED", ("DISTINCT_COMPLEMENTARY_MATERIALS_REQUIRED",))
    return GateDecision("ELIGIBLE", ("RESEARCH_ONLY_NO_HOST_OR_CORE_PROMOTION",))


def composite_promotion_gate(
    policy: MaterialPolicy, receipt: Mapping[str, Any]
) -> GateDecision:
    """Require verified parents plus fresh/rolling marginal evidence; never Core."""
    parents = receipt.get("parents")
    if not isinstance(parents, list) or len(parents) != 2:
        return GateDecision("HOLD", ("VERIFIED_PARENT_RECEIPTS_REQUIRED",))
    refs: list[tuple[str | Path, str]] = []
    for parent in parents:
        if not isinstance(parent, dict) or not isinstance(parent.get("path"), str):
            return GateDecision("HOLD", ("VERIFIED_PARENT_RECEIPTS_REQUIRED",))
        refs.append((parent["path"], parent.get("sha256", "")))
    decision = fusion_gate(
        policy, refs, receipt.get("behavior_cosine"), receipt.get("changed_axes", 0)
    )
    if decision.state != "ELIGIBLE":
        return decision
    if receipt.get("integrity") != "PASS" or any(
        not _hash(receipt.get(key, ""))
        for key in ("rule_sha256", "data_sha256", "cost_sha256", "window_sha256")
    ):
        return GateDecision("HOLD", ("COMPOSITE_EVIDENCE_BINDING_MISSING",))
    if (
        receipt.get("fresh_forward") is not True
        or receipt.get("rolling_oos_positive") is not True
    ):
        return GateDecision("HOLD", ("FRESH_AND_ROLLING_REQUIRED",))
    metrics = receipt.get("metrics")
    if not isinstance(metrics, dict):
        return GateDecision("HOLD", ("MARGINAL_METRICS_MISSING",))
    for key in ("marginal_net_bps", "delta_pf", "dd_improvement_bps"):
        number = _number(metrics.get(key))
        if number is None:
            return GateDecision("HOLD", ("MARGINAL_METRICS_MISSING",))
    if all(
        metrics[key] <= 0
        for key in ("marginal_net_bps", "delta_pf", "dd_improvement_bps")
    ):
        return GateDecision("BLOCKED", ("ALL_MARGINAL_CONTRIBUTIONS_NONBENEFICIAL",))
    return _marginal_acceptance_gate(receipt)
