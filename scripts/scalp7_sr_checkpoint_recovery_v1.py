"""One-shot SR segment recovery; never reset an identity, scope, or FULL budget.

The caller must pin the pre-interruption ledger snapshot, original approval,
checkpoint, and explicit continuation permit from independently saved evidence.
Only the missing CONTROL segment is delegated to the frozen replay adapter.
RETEST remains a first execution through the original admission gateway.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

BLOCKED = {"live": "BLOCKED", "order": "BLOCKED", "promotion": False}
SEGMENTS = ("common_contiguous_1", "common_contiguous_2")


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def decode(raw: bytes) -> Any:
    def invalid(value: str) -> None:
        raise ValueError("NONFINITE_JSON:" + value)
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid)


def read_regular(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        require(stat.S_ISREG(before.st_mode), "REGULAR_FILE_REQUIRED")
        require(before.st_size <= 512 * 1024 * 1024, "INPUT_TOO_LARGE")
        raw = handle.read()
        after = os.fstat(handle.fileno())
    require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "INPUT_CHANGED_DURING_READ")
    return raw


def sha(path: Path) -> str:
    return hashlib.sha256(read_regular(path)).hexdigest()


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save_exclusive(path: Path, value: Any) -> None:
    raw = canonical(value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    sync_directory(path.parent)


@dataclass(frozen=True)
class Pins:
    scope: str
    owner: str
    control_identity: str
    retest_identity: str
    control_binding_sha256: str
    original_approval_sha256: str
    continuation_permit_sha256: str
    checkpoint_sha256: str
    scopes_sha256: str
    claims_sha256: str
    events_sha256: str


def snapshot(db: sqlite3.Connection) -> dict[str, Any]:
    # This dedicated registry must not be recreated or widened to another scope.
    return {table: [dict(row) for row in db.execute("SELECT * FROM " + table + " ORDER BY " + key)]
            for table, key in (("scopes", "scope"), ("claims", "identity_key"), ("events", "sequence"))}


@contextmanager
def database(path: Path, *, writable: bool = False) -> Iterator[sqlite3.Connection]:
    require(not path.is_symlink() and path.is_file(), "EXISTING_REGISTRY_REQUIRED")
    db = sqlite3.connect(path.as_uri() + ("?mode=rw" if writable else "?mode=ro"),
                         uri=True, timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    if not writable:
        db.execute("PRAGMA query_only=ON")
    try:
        db.execute("BEGIN IMMEDIATE" if writable else "BEGIN")
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def validate_snapshot(value: Mapping[str, Any], pins: Pins) -> None:
    for table in ("scopes", "claims", "events"):
        require(digest(value[table]) == getattr(pins, table + "_sha256"), "LEDGER_CHANGED:" + table)
    require(len(value["scopes"]) == 1 and len(value["claims"]) == 2, "EXACT_EXISTING_SCOPE_REQUIRED")
    scope = value["scopes"][0]
    require(scope["scope"] == pins.scope and scope["owner"] == pins.owner, "SINGLE_OWNER_REQUIRED")
    require(scope["max_candidates"] == scope["max_executions"] == 2, "ORIGINAL_CAP_REQUIRED")
    contract = decode(scope["contract_json"].encode())
    require(contract["automatic_retry"] is False and contract["max_per_identity"] == 1,
            "NO_AUTOMATIC_RETRY_REQUIRED")
    require(contract["approval_sha256"] == pins.original_approval_sha256, "ORIGINAL_APPROVAL_CHANGED")
    require(set(contract["allowed_identity_keys"]) == {pins.control_identity, pins.retest_identity},
            "IDENTITY_ALLOWLIST_CHANGED")
    claims = {row["identity_key"]: row for row in value["claims"]}
    require(set(claims) == {pins.control_identity, pins.retest_identity}, "EXACT_TWO_IDENTITIES_REQUIRED")
    require(claims[pins.control_identity]["state"] == "RUNNING" and
            claims[pins.retest_identity]["state"] == "RESERVED", "RECOVERY_STATE_CHANGED")
    require(all(row["scope"] == pins.scope and row["result_json"] is None for row in claims.values()),
            "RESULT_OR_SCOPE_CHANGED")
    starts = [row["identity_key"] for row in value["events"] if row["event"] == "STARTED"]
    require(starts == [pins.control_identity], "ORIGINAL_SINGLE_START_REQUIRED")
    require(all(row["event"] in {"SCOPE_CREATED", "RESERVED", "STARTED"} for row in value["events"]),
            "EXISTING_RECOVERY_OR_TERMINAL_REQUIRES_RECONCILIATION")


def validate_child(result: Mapping[str, Any], child: Mapping[str, Any]) -> None:
    require(result["schema"] == "zel.scalp7.exact25_model_runner.v1", "CHILD_SCHEMA_CHANGED")
    require(result["identity_key"] == child["identity_key"] and
            result["binding_sha256"] == child["binding_sha256"], "CHILD_IDENTITY_CHANGED")
    require(result["authority"] == BLOCKED and result["formal_promotion"] == "BLOCKED" and
            result["fresh_T"] == 0, "AUTHORITY_CHANGED")
    require(set(result["cost_scenarios"]) == {"1x", "2x"}, "SAME_FILL_COST_SCENARIOS_REQUIRED")
    canonical(result)


def inspect(runtime: Path, binding: Mapping[str, Any], permit: Mapping[str, Any], pins: Pins) -> dict[str, Any]:
    require(runtime.is_absolute() and runtime.resolve(strict=True) == runtime, "CANONICAL_RUNTIME_REQUIRED")
    results = runtime / "results"
    require(results.is_dir() and results.resolve() == results, "CANONICAL_RESULTS_REQUIRED")
    require(digest(permit) == pins.continuation_permit_sha256, "CONTINUATION_PERMIT_CHANGED")
    require(permit["scope"] == pins.scope and permit["owner"] == pins.owner and
            permit["original_approval_sha256"] == pins.original_approval_sha256,
            "PERMIT_SCOPE_CHANGED")
    require(permit["checkpoint_sha256"] == pins.checkpoint_sha256 and
            permit["control_identity"] == pins.control_identity and
            permit["retest_identity"] == pins.retest_identity, "PERMIT_IDENTITY_CHANGED")
    require(permit["cumulative_full_cap"] == 2 and permit["automatic_retry"] is False and
            permit["rerun_completed_segment"] is False and permit["service_change"] is False and
            permit["allow_missing_control_segment"] is True, "PERMIT_BOUNDARY_CHANGED")
    require(sha(runtime / "USER_APPROVAL.json") == pins.original_approval_sha256, "APPROVAL_FILE_CHANGED")
    require(binding["label"] == "SR_CONTROL" and binding["identity_key"] == pins.control_identity and
            binding["binding_sha256"] == pins.control_binding_sha256 and
            digest({k: v for k, v in binding.items() if k != "binding_sha256"}) == pins.control_binding_sha256,
            "FROZEN_BINDING_CHANGED")
    require(set(binding["segment_bindings"]) == set(SEGMENTS), "EXACT_TWO_SEGMENTS_REQUIRED")
    require(binding["cross_segment_nav_aggregation"] == "FORBIDDEN", "SEGMENT_CAPITAL_CHANGED")
    for path in (runtime / "checkpoint_recovery_v1", results / "SR_CONTROL.json",
                 results / "SR_CONTROL.json.partial", results / "SR_RETEST.json",
                 results / "SR_RETEST.json.partial", results / ("SR_CONTROL." + SEGMENTS[1] + ".checkpoint.json")):
        require(not os.path.lexists(path), "EXISTING_RECOVERY_OR_RESULT:" + path.name)
    require(not list(results.glob("SR_RETEST.*.checkpoint.json")), "RETEST_ALREADY_EXECUTED")
    checkpoint = results / ("SR_CONTROL." + SEGMENTS[0] + ".checkpoint.json")
    raw = read_regular(checkpoint)
    require(hashlib.sha256(raw).hexdigest() == pins.checkpoint_sha256, "CHECKPOINT_HASH_CHANGED")
    saved = decode(raw)
    require(saved["outer_identity_key"] == pins.control_identity and saved["segment_id"] == SEGMENTS[0]
            and saved["binding_sha256"] == pins.control_binding_sha256, "CHECKPOINT_BINDING_CHANGED")
    validate_child(saved["result"], binding["segment_bindings"][SEGMENTS[0]])
    with database(runtime / "candidate_registry.sqlite3") as db:
        before = snapshot(db)
    validate_snapshot(before, pins)
    return {"ledger_before": before, "reused_segment": SEGMENTS[0], "missing_segment": SEGMENTS[1],
            "checkpoint_sha256": pins.checkpoint_sha256, "existing_full_starts": 1,
            "additional_control_full_starts": 0, "automatic_retry": False}


def _event(db: sqlite3.Connection, pins: Pins, name: str, payload: Mapping[str, Any]) -> None:
    db.execute("INSERT INTO events(scope,identity_key,event,payload_json) VALUES(?,?,?,?)",
               (pins.scope, pins.control_identity, name, canonical(payload).decode()))


def recover_control(runtime: Path, binding: Mapping[str, Any], permit: Mapping[str, Any], pins: Pins,
                    *, verify_frozen: Callable[[], None], ensure_no_worker: Callable[[], None],
                    replay_missing: Callable[[str], Mapping[str, Any]]) -> dict[str, Any]:
    """Resume exactly one missing segment under the original STARTED event.

    verify_frozen must verify the unchanged code closure and every source hash;
    ensure_no_worker must fail closed when process visibility is unavailable.
    Nothing is replayed, and nothing is written, before both callbacks succeed.
    """
    inspect(runtime, binding, permit, pins)
    lock_path = runtime / "execution.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(fd, "r+b") as lock:
        require(stat.S_ISREG(os.fstat(lock.fileno()).st_mode), "REGULAR_LOCK_REQUIRED")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(os.stat(lock_path, follow_symlinks=False).st_ino == os.fstat(lock.fileno()).st_ino,
                "LOCK_INODE_CHANGED")
        ensure_no_worker()
        verify_frozen()
        plan = inspect(runtime, binding, permit, pins)
        journal = runtime / "checkpoint_recovery_v1"
        journal.mkdir(mode=0o700)
        sync_directory(runtime)
        save_exclusive(journal / "INTENT.json", {"pins": pins.__dict__, "permit": permit, "plan": plan})
        db_path = runtime / "candidate_registry.sqlite3"
        with database(db_path, writable=True) as db:
            validate_snapshot(snapshot(db), pins)
            _event(db, pins, "RECOVERY_STARTED", {"permit_sha256": pins.continuation_permit_sha256,
                   "reused_checkpoint_sha256": pins.checkpoint_sha256,
                   "missing_segment": SEGMENTS[1], "additional_full_starts": 0,
                   "prior_uncheckpointed_segment_work_may_repeat": True})
            expected_events = snapshot(db)["events"]
        destination = runtime / "results/SR_CONTROL.json"
        published = False
        try:
            save_exclusive(journal / "SEGMENT_STARTED.json", {"segment_id": SEGMENTS[1], "attempt": 1})
            new_result = dict(replay_missing(SEGMENTS[1]))
            validate_child(new_result, binding["segment_bindings"][SEGMENTS[1]])
            checkpoint1 = destination.with_suffix("." + SEGMENTS[0] + ".checkpoint.json")
            first_raw = read_regular(checkpoint1)
            require(hashlib.sha256(first_raw).hexdigest() == pins.checkpoint_sha256, "REUSED_CHECKPOINT_CHANGED")
            checkpoint2 = destination.with_suffix("." + SEGMENTS[1] + ".checkpoint.json")
            save_exclusive(checkpoint2, {"outer_identity_key": pins.control_identity,
                           "segment_id": SEGMENTS[1], "binding_sha256": pins.control_binding_sha256,
                           "result": new_result})
            result = {"schema": "scalp7.measurement.segment_comparison_result.v1",
                      "identity_key": pins.control_identity, "binding_sha256": pins.control_binding_sha256,
                      "segments": {SEGMENTS[0]: decode(first_raw)["result"], SEGMENTS[1]: new_result},
                      "segment_checkpoints": {SEGMENTS[0]: {"path": str(checkpoint1), "sha256": pins.checkpoint_sha256},
                                              SEGMENTS[1]: {"path": str(checkpoint2), "sha256": sha(checkpoint2)}},
                      "whole_period_nav": None, "cross_segment_nav_aggregation": "FORBIDDEN",
                      "full_execution_performed": True, "full_execution_count": 1,
                      "funding_status": "UNKNOWN_NOT_ZERO",
                      "old_unresolved_positions": "PRESERVED_SEPARATE_PARENT_STATE", "authority": dict(BLOCKED)}
            partial = destination.with_suffix(".json.partial")
            save_exclusive(partial, result)
            os.link(partial, destination, follow_symlinks=False)
            sync_directory(destination.parent)
            published = True
            partial.unlink()
            sync_directory(destination.parent)
            receipt = {"result_path": str(destination), "result_file_sha256": sha(destination),
                       "binding_sha256": pins.control_binding_sha256}
            with database(db_path, writable=True) as db:
                current = snapshot(db)
                require(current["scopes"] == plan["ledger_before"]["scopes"] and
                        current["claims"] == plan["ledger_before"]["claims"] and
                        current["events"] == expected_events,
                        "LEDGER_CHANGED_DURING_RECOVERY")
                changed = db.execute("UPDATE claims SET state='COMPLETED',result_json=? WHERE identity_key=? AND state='RUNNING'",
                                     (canonical(receipt).decode(), pins.control_identity)).rowcount
                require(changed == 1, "CONTROL_COMPLETION_CONFLICT")
                _event(db, pins, "COMPLETED", receipt)
                _event(db, pins, "RECOVERY_COMPLETED", {"reused_checkpoint_sha256": pins.checkpoint_sha256,
                        "additional_full_starts": 0, "segment_replay_calls": 1})
            save_exclusive(journal / "COMPLETED.json", {**receipt, "control_completed": True,
                           "retest_started_by_recovery": False, "additional_control_full_starts": 0})
            return result
        except BaseException as exc:
            # Preserve a published result for ledger-only reconciliation.
            save_exclusive(journal / "STOPPED.json", {"exception_type": type(exc).__name__,
                           "durable_result_published": published, "automatic_retry": False,
                           "requires_explicit_reconciliation": True, "ledger_not_reset": True})
            raise
