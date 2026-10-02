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
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    value = hashlib.sha256()
    with os.fdopen(fd, "rb") as handle:
        before = os.fstat(handle.fileno())
        require(stat.S_ISREG(before.st_mode), "REGULAR_FILE_REQUIRED")
        require(before.st_size <= 512 * 1024 * 1024, "INPUT_TOO_LARGE")
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
        after = os.fstat(handle.fileno())
    require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "INPUT_CHANGED_DURING_READ")
    return value.hexdigest()


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


def _validate_context(runtime: Path, binding: Mapping[str, Any], permit: Mapping[str, Any], pins: Pins) -> Path:
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
    return results


def inspect(runtime: Path, binding: Mapping[str, Any], permit: Mapping[str, Any], pins: Pins) -> dict[str, Any]:
    results = _validate_context(runtime, binding, permit, pins)
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


def _verify_existing_lock(path: Path, held: os.stat_result) -> None:
    """The named existing lock must still be the regular inode held by this caller."""
    current = os.stat(path, follow_symlinks=False)
    require(stat.S_ISREG(current.st_mode), "REGULAR_LOCK_REQUIRED")
    require((current.st_dev, current.st_ino) == (held.st_dev, held.st_ino), "LOCK_INODE_CHANGED")


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
        held = os.fstat(lock.fileno())
        require(stat.S_ISREG(held.st_mode), "REGULAR_LOCK_REQUIRED")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _verify_existing_lock(lock_path, held)
        ensure_no_worker()
        verify_frozen()
        plan = inspect(runtime, binding, permit, pins)
        _verify_existing_lock(lock_path, held)
        journal = runtime / "checkpoint_recovery_v1"
        journal.mkdir(mode=0o700)
        sync_directory(runtime)
        _verify_existing_lock(lock_path, held)
        save_exclusive(journal / "INTENT.json", {"pins": pins.__dict__, "permit": permit, "plan": plan})
        db_path = runtime / "candidate_registry.sqlite3"
        with database(db_path, writable=True) as db:
            validate_snapshot(snapshot(db), pins)
            _verify_existing_lock(lock_path, held)
            _event(db, pins, "RECOVERY_STARTED", {"permit_sha256": pins.continuation_permit_sha256,
                   "reused_checkpoint_sha256": pins.checkpoint_sha256,
                   "missing_segment": SEGMENTS[1], "additional_full_starts": 0,
                   "prior_uncheckpointed_segment_work_may_repeat": True})
            expected_events = snapshot(db)["events"]
            _verify_existing_lock(lock_path, held)
        destination = runtime / "results/SR_CONTROL.json"
        published = False
        try:
            _verify_existing_lock(lock_path, held)
            save_exclusive(journal / "SEGMENT_STARTED.json", {"segment_id": SEGMENTS[1], "attempt": 1})
            _verify_existing_lock(lock_path, held)
            new_result = dict(replay_missing(SEGMENTS[1]))
            _verify_existing_lock(lock_path, held)
            validate_child(new_result, binding["segment_bindings"][SEGMENTS[1]])
            checkpoint1 = destination.with_suffix("." + SEGMENTS[0] + ".checkpoint.json")
            first_raw = read_regular(checkpoint1)
            require(hashlib.sha256(first_raw).hexdigest() == pins.checkpoint_sha256, "REUSED_CHECKPOINT_CHANGED")
            checkpoint2 = destination.with_suffix("." + SEGMENTS[1] + ".checkpoint.json")
            _verify_existing_lock(lock_path, held)
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
            _verify_existing_lock(lock_path, held)
            save_exclusive(partial, result)
            _verify_existing_lock(lock_path, held)
            os.link(partial, destination, follow_symlinks=False)
            sync_directory(destination.parent)
            published = True
            _verify_existing_lock(lock_path, held)
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
                _verify_existing_lock(lock_path, held)
                changed = db.execute("UPDATE claims SET state='COMPLETED',result_json=? WHERE identity_key=? AND state='RUNNING'",
                                     (canonical(receipt).decode(), pins.control_identity)).rowcount
                require(changed == 1, "CONTROL_COMPLETION_CONFLICT")
                _event(db, pins, "COMPLETED", receipt)
                _event(db, pins, "RECOVERY_COMPLETED", {"reused_checkpoint_sha256": pins.checkpoint_sha256,
                        "additional_full_starts": 0, "segment_replay_calls": 1})
                _verify_existing_lock(lock_path, held)
            _verify_existing_lock(lock_path, held)
            save_exclusive(journal / "COMPLETED.json", {**receipt, "control_completed": True,
                           "retest_started_by_recovery": False, "additional_control_full_starts": 0})
            return result
        except BaseException as exc:
            # Preserve a published result for ledger-only reconciliation.
            save_exclusive(journal / "STOPPED.json", {"exception_type": type(exc).__name__,
                           "durable_result_published": published, "automatic_retry": False,
                           "requires_explicit_reconciliation": True, "ledger_not_reset": True})
            raise


def _reconciliation_evidence(runtime: Path, binding: Mapping[str, Any],
                             permit: Mapping[str, Any], pins: Pins, *,
                             expected_intent_sha256: str, expected_result_sha256: str,
                             expected_second_checkpoint_sha256: str) -> dict[str, Any]:
    """Read original intent and completed bytes; never turn current state into new pins."""
    results = _validate_context(runtime, binding, permit, pins)
    journal = runtime / "checkpoint_recovery_v1"
    require(journal.is_dir() and journal.resolve() == journal, "EXISTING_CANONICAL_JOURNAL_REQUIRED")
    for expected in (expected_intent_sha256, expected_result_sha256, expected_second_checkpoint_sha256):
        require(isinstance(expected, str) and len(expected) == 64 and
                all(c in "0123456789abcdef" for c in expected), "EXTERNAL_EVIDENCE_HASH_REQUIRED")
    intent_raw = read_regular(journal / "INTENT.json")
    require(hashlib.sha256(intent_raw).hexdigest() == expected_intent_sha256, "INTENT_HASH_CHANGED")
    intent = decode(intent_raw)
    require(canonical(intent["pins"]) == canonical(pins.__dict__) and
            canonical(intent["permit"]) == canonical(permit), "ORIGINAL_INTENT_CHANGED")
    before = intent["plan"]["ledger_before"]
    validate_snapshot(before, pins)
    expected_plan = {"ledger_before": before, "reused_segment": SEGMENTS[0],
                     "missing_segment": SEGMENTS[1], "checkpoint_sha256": pins.checkpoint_sha256,
                     "existing_full_starts": 1, "additional_control_full_starts": 0,
                     "automatic_retry": False}
    require(canonical(intent) == canonical({"pins": pins.__dict__, "permit": permit,
                                          "plan": expected_plan}), "ORIGINAL_INTENT_CHANGED")
    file_hashes = {runtime / "USER_APPROVAL.json": pins.original_approval_sha256,
                   journal / "INTENT.json": expected_intent_sha256}
    absent_paths = []
    started_raw = read_regular(journal / "SEGMENT_STARTED.json")
    file_hashes[journal / "SEGMENT_STARTED.json"] = hashlib.sha256(started_raw).hexdigest()
    require(canonical(decode(started_raw)) ==
            canonical({"segment_id": SEGMENTS[1], "attempt": 1}), "SEGMENT_START_EVIDENCE_CHANGED")
    if os.path.lexists(journal / "STOPPED.json"):
        stopped_raw = read_regular(journal / "STOPPED.json")
        file_hashes[journal / "STOPPED.json"] = hashlib.sha256(stopped_raw).hexdigest()
        stopped = decode(stopped_raw)
        require(stopped["automatic_retry"] is False and stopped["ledger_not_reset"] is True and
                stopped["requires_explicit_reconciliation"] is True and
                type(stopped["durable_result_published"]) is bool, "STOPPED_BOUNDARY_CHANGED")
        # The flag can be false after link() succeeded but directory fsync failed.
        # Actual pinned files decide whether ledger-only reconciliation is possible.
    else:
        absent_paths.append(journal / "STOPPED.json")
    destination = results / "SR_CONTROL.json"
    require(os.path.lexists(destination), "EXISTING_FINAL_RESULT_REQUIRED")
    result_raw = read_regular(destination)
    require(hashlib.sha256(result_raw).hexdigest() == expected_result_sha256, "RESULT_HASH_CHANGED")
    file_hashes[destination] = expected_result_sha256
    result = decode(result_raw)
    del result_raw
    require(isinstance(result, dict) and isinstance(result.get("segments"), dict) and
            set(result["segments"]) == set(SEGMENTS), "PUBLISHED_RESULT_EVIDENCE_CONFLICT")
    partial = results / "SR_CONTROL.json.partial"
    if os.path.lexists(partial):
        require(sha(partial) == expected_result_sha256, "PARTIAL_RESULT_CONFLICT")
        file_hashes[partial] = expected_result_sha256
    else:
        absent_paths.append(partial)
    for path in (results / "SR_RETEST.json", results / "SR_RETEST.json.partial"):
        require(not os.path.lexists(path), "RETEST_ALREADY_EXECUTED")
        absent_paths.append(path)
    require(not list(results.glob("SR_RETEST.*.checkpoint.json")), "RETEST_ALREADY_EXECUTED")
    receipts = {}
    for sid, expected in ((SEGMENTS[0], pins.checkpoint_sha256),
                          (SEGMENTS[1], expected_second_checkpoint_sha256)):
        checkpoint = destination.with_suffix("." + sid + ".checkpoint.json")
        raw = read_regular(checkpoint)
        require(hashlib.sha256(raw).hexdigest() == expected, "CHECKPOINT_HASH_CHANGED:" + sid)
        file_hashes[checkpoint] = expected
        saved = decode(raw)
        del raw
        require(canonical({k: v for k, v in saved.items() if k != "result"}) ==
                canonical({"outer_identity_key": pins.control_identity, "segment_id": sid,
                           "binding_sha256": pins.control_binding_sha256}), "CHECKPOINT_BINDING_CHANGED")
        validate_child(saved["result"], binding["segment_bindings"][sid])
        require(digest(saved["result"]) == digest(result["segments"][sid]),
                "PUBLISHED_RESULT_EVIDENCE_CONFLICT")
        del saved
        receipts[sid] = {"path": str(checkpoint), "sha256": expected}
    expected_header = {"schema": "scalp7.measurement.segment_comparison_result.v1",
                       "identity_key": pins.control_identity, "binding_sha256": pins.control_binding_sha256,
                       "segment_checkpoints": receipts,
                       "whole_period_nav": None, "cross_segment_nav_aggregation": "FORBIDDEN",
                       "full_execution_performed": True, "full_execution_count": 1,
                       "funding_status": "UNKNOWN_NOT_ZERO",
                       "old_unresolved_positions": "PRESERVED_SEPARATE_PARENT_STATE", "authority": dict(BLOCKED)}
    require(canonical({k: v for k, v in result.items() if k != "segments"}) == canonical(expected_header),
            "PUBLISHED_RESULT_EVIDENCE_CONFLICT")
    receipt = {"result_path": str(destination), "result_file_sha256": expected_result_sha256,
               "binding_sha256": pins.control_binding_sha256}
    completed_path = journal / "COMPLETED.json"
    if os.path.lexists(completed_path):
        completed_raw = read_regular(completed_path)
        file_hashes[completed_path] = hashlib.sha256(completed_raw).hexdigest()
        require(canonical(decode(completed_raw)) == canonical(
            {**receipt, "control_completed": True, "retest_started_by_recovery": False,
             "additional_control_full_starts": 0}), "COMPLETION_JOURNAL_CONFLICT")
    else:
        absent_paths.append(completed_path)
    return {"ledger_before": before, "result": result, "receipt": receipt,
            "destination": destination, "file_hashes": file_hashes, "absent_paths": absent_paths,
            "completion_journal_present": os.path.lexists(completed_path),
            "reconciliation_payload": {
                "intent_file_sha256": expected_intent_sha256, "result_file_sha256": expected_result_sha256,
                "reused_checkpoint_sha256": pins.checkpoint_sha256,
                "second_checkpoint_sha256": expected_second_checkpoint_sha256,
                "ledger_only": True, "additional_full_starts": 0, "segment_replay_calls": 0,
                "preserves_prior_recovery_work": True}}


def _validate_reconciliation_ledger(current: Mapping[str, Any], evidence: Mapping[str, Any], pins: Pins) -> bool:
    before, receipt = evidence["ledger_before"], evidence["receipt"]
    require(canonical(current["scopes"]) == canonical(before["scopes"]), "ORIGINAL_SCOPE_CHANGED")
    claims = {row["identity_key"]: row for row in current["claims"]}
    original_claims = {row["identity_key"]: row for row in before["claims"]}
    require(set(claims) == set(original_claims), "EXACT_TWO_IDENTITIES_REQUIRED")
    require(canonical(claims[pins.retest_identity]) == canonical(original_claims[pins.retest_identity]),
            "RETEST_RESERVATION_CHANGED")
    control = claims[pins.control_identity]
    require(control["state"] in {"RUNNING", "COMPLETED"}, "CONTROL_TERMINAL_CONFLICT")
    expected_control = dict(original_claims[pins.control_identity])
    completed = control["state"] == "COMPLETED"
    require(completed or not evidence["completion_journal_present"], "COMPLETION_JOURNAL_CONFLICT")
    if completed:
        expected_control.update(state="COMPLETED", result_json=canonical(receipt).decode())
    require(canonical(control) == canonical(expected_control), "CONTROL_CLAIM_CHANGED")
    events, original = current["events"], before["events"]
    require(canonical(events[:len(original)]) == canonical(original), "ORIGINAL_EVENTS_CHANGED")
    tail = events[len(original):]
    names = [row["event"] for row in tail]
    require(names == ["RECOVERY_STARTED"] if not completed else
            names in (["RECOVERY_STARTED", "COMPLETED", "RECOVERY_COMPLETED"],
                      ["RECOVERY_STARTED", "COMPLETED", "RECOVERY_RECONCILED"]),
            "RECOVERY_EVENT_CHAIN_CHANGED")
    expected_payloads = [{"permit_sha256": pins.continuation_permit_sha256,
                          "reused_checkpoint_sha256": pins.checkpoint_sha256,
                          "missing_segment": SEGMENTS[1], "additional_full_starts": 0,
                          "prior_uncheckpointed_segment_work_may_repeat": True}]
    if completed:
        last_payload = evidence["reconciliation_payload"] if names[-1] == "RECOVERY_RECONCILED" else {
            "reused_checkpoint_sha256": pins.checkpoint_sha256,
            "additional_full_starts": 0, "segment_replay_calls": 1}
        expected_payloads.extend([receipt, last_payload])
    previous_sequence = original[-1]["sequence"]
    for row, payload in zip(tail, expected_payloads):
        require(row["scope"] == pins.scope and row["identity_key"] == pins.control_identity and
                type(row["sequence"]) is int and row["sequence"] == previous_sequence + 1 and
                isinstance(row["created_at"], str) and bool(row["created_at"]), "RECOVERY_EVENT_HEADER_CHANGED")
        require(canonical(decode(row["payload_json"].encode())) == canonical(payload),
                "RECOVERY_EVENT_PAYLOAD_CHANGED")
        previous_sequence = row["sequence"]
    return completed


def _recheck_reconciliation_files(evidence: Mapping[str, Any]) -> None:
    for path, expected in evidence["file_hashes"].items():
        require(sha(path) == expected, "EVIDENCE_CHANGED_BEFORE_COMMIT:" + path.name)
    for path in evidence["absent_paths"]:
        require(not os.path.lexists(path), "EVIDENCE_APPEARED_BEFORE_COMMIT:" + path.name)
    require(not list(evidence["destination"].parent.glob("SR_RETEST.*.checkpoint.json")),
            "RETEST_ALREADY_EXECUTED")


def reconcile_control(runtime: Path, binding: Mapping[str, Any], permit: Mapping[str, Any], pins: Pins, *,
                      expected_intent_sha256: str, expected_result_sha256: str,
                      expected_second_checkpoint_sha256: str, verify_frozen: Callable[[], None],
                      ensure_no_worker: Callable[[], None]) -> dict[str, Any]:
    """Finish an already published CONTROL result without any replay or new start.

    Pins and the INTENT hash must come from independently saved original approval
    and execution evidence. The result and second-checkpoint hashes must come
    from an explicit read-only validation of their actual bytes, child/header,
    frozen source and economic consistency; hashing arbitrary current files is
    not authorization. The caller records that validation's provenance.

    Both callbacks have the same fail-closed contract as recover_control. This
    API has no replay callback, does not publish a partial-only result, preserves
    every checkpoint/partial/STOPPED byte and never widens the original budget.
    Matching completed state is a read-only no-op; conflicts require investigation.
    """
    hashes = {"expected_intent_sha256": expected_intent_sha256,
              "expected_result_sha256": expected_result_sha256,
              "expected_second_checkpoint_sha256": expected_second_checkpoint_sha256}
    evidence = _reconciliation_evidence(runtime, binding, permit, pins, **hashes)
    with database(runtime / "candidate_registry.sqlite3") as db:
        _validate_reconciliation_ledger(snapshot(db), evidence, pins)
    # Do not retain two decoded account results while inspecting the locked state.
    del evidence
    lock_path = runtime / "execution.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(fd, "r+b") as lock:
        locked = os.fstat(lock.fileno())
        require(stat.S_ISREG(locked.st_mode), "REGULAR_LOCK_REQUIRED")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _verify_existing_lock(lock_path, locked)
        ensure_no_worker()
        verify_frozen()
        evidence = _reconciliation_evidence(runtime, binding, permit, pins, **hashes)
        _verify_existing_lock(lock_path, locked)
        with database(runtime / "candidate_registry.sqlite3", writable=True) as db:
            completed = _validate_reconciliation_ledger(snapshot(db), evidence, pins)
            _recheck_reconciliation_files(evidence)
            _verify_existing_lock(lock_path, locked)
            if not completed:
                # A prior crash can leave link() successful without directory fsync.
                # Establish durability of the verified existing result before the DB commit.
                result_fd = os.open(evidence["destination"], os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    os.fsync(result_fd)
                finally:
                    os.close(result_fd)
                sync_directory(evidence["destination"].parent)
                _recheck_reconciliation_files(evidence)
                _verify_existing_lock(lock_path, locked)
                changed = db.execute("UPDATE claims SET state='COMPLETED',result_json=? "
                                     "WHERE identity_key=? AND state='RUNNING'",
                                     (canonical(evidence["receipt"]).decode(), pins.control_identity)).rowcount
                require(changed == 1, "CONTROL_COMPLETION_CONFLICT")
                _event(db, pins, "COMPLETED", evidence["receipt"])
                _event(db, pins, "RECOVERY_RECONCILED", evidence["reconciliation_payload"])
                _verify_existing_lock(lock_path, locked)
        return {"result": evidence["result"], "receipt": evidence["receipt"],
                "reconciliation_performed": not completed, "already_completed": completed,
                "segment_replay_calls": 0, "additional_full_starts": 0}
