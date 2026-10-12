"""Explicit one-shot caller for the existing SR recovery core and frozen gateway.

This CLI can be launched directly by an authorized owner with detached stdout;
it does not register a service, allocate FULLs, reset claims, or retry a worker.
Inspect and frozen verification read metadata and bytes, never price rows.
"""

from __future__ import annotations

import argparse
import fcntl
import importlib
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import scalp7_sr_checkpoint_recovery_v1 as core

CAMPAIGN = Path("research/campaigns/scalp7_20261001/measurement_exact25_closure_v1")
FROZEN_FILES = {
    "NEXT_ECONOMIC_BATCH.json": "fdddfb38abedf6b978d94d2c40a6720fa6a7360a7dca7ae710bff727034115d7",
    "next_freezes/SR_CONTROL.json": "4190825d0de08e115f741356251717ac8edc3e0e0b5514cac34acee6e262d223",
    "next_freezes/SR_RETEST.json": "ae505e4c9de1e369486c8f19df896b00e6aae687e0562da02053b44b2e8629d0",
    "measurement/CANONICAL_MINUTE_HASHES.json": "eb26df4fc7b556a120b3f3a3e972e8512d7bcd2dc208c4e1332fe6ab72b84976",
}
CANONICAL_FILE_COUNT = 2196
CODE_PATHS = frozenset(
    "backend/research/rebuild/" + name + ".py"
    for name in (
        "economic7_campaign_registry_v1",
        "economic7_canonical_history_v1",
        "scalp7_exact25_execution_v1",
        "scalp7_exact25_model_runner_v1",
        "scalp7_exact25_pipeline_v1",
        "scalp7_exact25_reference_models_v1",
        "scalp7_exact25_reference_v1",
        "scalp7_implementation_contract_v1",
        "scalp7_measurement_compare_v1",
        "scalp7_measurement_repair_v1",
        "scalp7_source_data_v2",
    )
)


def _read(path: Path) -> Any:
    return core.decode(core.read_regular(path))


def _canonical_directory(path: Path) -> None:
    core.require(
        path.is_absolute() and path.is_dir() and path.resolve(strict=True) == path,
        "CANONICAL_DIRECTORY_REQUIRED:" + str(path),
    )


def _repository_file(repo: Path, relative: str) -> Path:
    path = repo / relative
    core.require(
        not Path(relative).is_absolute()
        and path.resolve(strict=True).is_relative_to(repo)
        and path.resolve(strict=True) == path,
        "CANONICAL_REPOSITORY_FILE_REQUIRED",
    )
    return path


def _held_lock_visible(path: Path, fd: int) -> None:
    opened, current = os.fstat(fd), path.stat(follow_symlinks=False)
    core.require(stat.S_ISREG(opened.st_mode) and stat.S_ISREG(current.st_mode), "REGULAR_LOCK_REQUIRED")
    core.require((current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino), "LOCK_INODE_CHANGED")


def _real_modules(repo: Path) -> SimpleNamespace:
    sys.path.insert(0, str(repo))
    prefix = "backend.research.rebuild."
    names = {
        "compare": "scalp7_measurement_compare_v1",
        "runner": "scalp7_exact25_model_runner_v1",
        "source": "scalp7_source_data_v2",
        "loader": "scalp7_exact25_model_data_v1",
    }
    modules = {}
    for role, name in names.items():
        module = importlib.import_module(prefix + name)
        core.require(
            Path(module.__file__).resolve() == repo / "backend/research/rebuild" / (name + ".py"),
            "IMPORTED_MODULE_FROM_OTHER_CHECKOUT",
        )
        modules[role] = module
    return SimpleNamespace(**modules)


def ensure_no_worker(
    runtime: Path,
    repo: Path,
    identities: tuple[str, str],
    *,
    proc: Path = Path("/proc"),
) -> None:
    """Require visible process inventory and no foreign owner of this lock.

    The core itself holds execution.lock while invoking this callback. A lock
    owned by this PID is therefore allowed; a foreign or unknown PID is not.
    Reading failure, restricted proc mounts, and disappearing visibility fail
    closed. A process which exits during a read is the only tolerated absence.
    """
    try:
        mounts = (proc / "mounts").read_text().splitlines()
        own_mount = [r.split() for r in mounts if len(r.split()) >= 4 and r.split()[1] == str(proc)]
        core.require(len(own_mount) == 1 and own_mount[0][2] == "proc", "PROC_MOUNT_UNVERIFIED")
        options = own_mount[0][3].split(",")
        core.require(not any(x.startswith("hidepid=") and x != "hidepid=0" for x in options),
                     "PROCESS_VISIBILITY_RESTRICTED")
        process_dirs = [p for p in proc.iterdir() if p.name.isdecimal()]
        own_pid = os.getpid()
        core.require(any(p.name == str(own_pid) for p in process_dirs), "OWN_PROCESS_NOT_VISIBLE")
        for directory in process_dirs:
            try:
                command = (directory / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
            except FileNotFoundError:
                core.require(not directory.exists(), "PROCESS_COMMAND_UNVERIFIABLE")
                continue
            if directory.name == str(own_pid):
                continue
            markers = (str(runtime), *identities, "scalp7_sr_checkpoint_runtime_v1.py")
            relevant = any(marker in command for marker in markers)
            if command and "python" in command.lower():
                try:
                    cwd = (directory / "cwd").resolve(strict=True)
                except FileNotFoundError:
                    core.require(not directory.exists(), "PROCESS_CWD_UNVERIFIABLE")
                    continue
                relevant = relevant or cwd == repo or repo in cwd.parents
            core.require(not relevant, "EXISTING_WORKER_REQUIRES_OBSERVATION:" + directory.name)
        lock_path = runtime / "execution.lock"
        lock_stat = lock_path.stat(follow_symlinks=False)
        core.require(stat.S_ISREG(lock_stat.st_mode) and not lock_path.is_symlink(), "REGULAR_LOCK_REQUIRED")
        for line in (proc / "locks").read_text().splitlines():
            fields = line.split()
            if len(fields) > 1 and fields[1] == "->":
                fields.pop(1)
            core.require(len(fields) >= 8, "LOCK_VISIBILITY_UNVERIFIABLE")
            device = fields[5].split(":")
            core.require(len(device) == 3, "LOCK_DEVICE_UNVERIFIABLE")
            if (int(device[0], 16), int(device[1], 16), int(device[2])) == (
                os.major(lock_stat.st_dev), os.minor(lock_stat.st_dev), lock_stat.st_ino
            ):
                core.require(int(fields[4]) == own_pid, "FOREIGN_EXECUTION_LOCK_OWNER")
        current_lock = lock_path.stat(follow_symlinks=False)
        core.require(stat.S_ISREG(current_lock.st_mode), "REGULAR_LOCK_REQUIRED")
        core.require((current_lock.st_dev, current_lock.st_ino) == (lock_stat.st_dev, lock_stat.st_ino),
                     "LOCK_INODE_CHANGED")
    except (OSError, UnicodeError) as exc:
        raise PermissionError("PROCESS_OR_LOCK_VISIBILITY_UNAVAILABLE") from exc


class RuntimeAdapter:
    def __init__(
        self,
        repo: Path,
        runtime: Path,
        pins: core.Pins,
        permit: Mapping[str, Any],
        *,
        modules_factory: Callable[[Path], Any] = _real_modules,
        proc: Path = Path("/proc"),
    ) -> None:
        _canonical_directory(repo)
        _canonical_directory(runtime)
        self.repo, self.runtime, self.pins = repo, runtime, pins
        self.permit = dict(permit)
        self.modules_factory, self.proc = modules_factory, proc
        self._modules: Any = None
        self._recovering = False
        self._missing_called = False
        self.frozen = {}
        for label in ("SR_CONTROL", "SR_RETEST"):
            path = _repository_file(repo, str(CAMPAIGN / "next_freezes" / (label + ".json")))
            core.require(core.sha(path) == FROZEN_FILES["next_freezes/" + label + ".json"], "FREEZE_FILE_CHANGED")
            self.frozen[label] = _read(path)

    def _snapshot(self) -> dict[str, Any]:
        with core.database(self.runtime / "candidate_registry.sqlite3") as db:
            return core.snapshot(db)

    def ensure_no_worker(self) -> None:
        ensure_no_worker(self.runtime, self.repo, (self.pins.control_identity, self.pins.retest_identity), proc=self.proc)

    def verify_frozen(self) -> None:
        """Verify external pins and actual source bytes without loading candles."""
        core._validate_context(self.runtime, self.frozen["SR_CONTROL"], self.permit, self.pins)
        core.require(core.sha(self.runtime / "USER_APPROVAL.json") == self.pins.original_approval_sha256,
                     "ORIGINAL_APPROVAL_CHANGED")
        approval = _read(self.runtime / "USER_APPROVAL.json")
        core.require(approval["scope_key"] == self.pins.scope and approval["max_candidates"] == 2
                     and approval["max_executions_cumulative"] == 2 and approval["max_per_identity"] == 1
                     and approval["automatic_retry"] is False and approval["additional_full_authorized"] == 0,
                     "ORIGINAL_APPROVAL_BOUNDARY_CHANGED")
        for relative, expected in FROZEN_FILES.items():
            core.require(core.sha(_repository_file(self.repo, str(CAMPAIGN / relative))) == expected,
                         "FROZEN_ARTIFACT_CHANGED:" + relative)
        batch = _read(self.repo / CAMPAIGN / "NEXT_ECONOMIC_BATCH.json")
        core.require(batch["scope_key"] == self.pins.scope and batch["minimum_new_full_runs"] == 2,
                     "FROZEN_BATCH_CHANGED")
        allowed = {r["label"]: r for r in approval["approved_identities"]}
        prepared = {r["label"]: r for r in batch["prepared_identities"]}
        labels = {"SR_CONTROL_CONTINUOUS_SEGMENTS_V1", "SR_RETEST_CONTINUOUS_SEGMENTS_V1"}
        core.require(len(approval["approved_identities"]) == len(batch["prepared_identities"]) == 2
                     and set(allowed) == set(prepared) == labels, "EXACT_APPROVED_IDENTITIES_REQUIRED")
        ledger = self._snapshot()
        core.require(core.digest(ledger["scopes"]) == self.pins.scopes_sha256, "ORIGINAL_SCOPE_CHANGED")
        claims = {row["identity_key"]: row for row in ledger["claims"]}
        core.require(len(ledger["claims"]) == 2 and set(claims) == {self.pins.control_identity, self.pins.retest_identity},
                     "EXACT_EXISTING_CLAIMS_REQUIRED")
        for label, binding in self.frozen.items():
            entry = allowed[label + "_CONTINUOUS_SEGMENTS_V1"]
            original = prepared[entry["label"]]
            for key in ("identity_key", "binding_sha256", "binding_file_sha256"):
                core.require(entry[key] == original[key], "APPROVAL_FREEZE_MISMATCH")
            key = binding["identity_key"]
            expected_key = self.pins.control_identity if label == "SR_CONTROL" else self.pins.retest_identity
            core.require(key == expected_key == entry["identity_key"] and binding["label"] == label
                         and binding["binding_sha256"] == entry["binding_sha256"]
                         and core.digest({k: v for k, v in binding.items() if k != "binding_sha256"}) == entry["binding_sha256"],
                         "FROZEN_BINDING_CHANGED")
            identity = binding["candidate_identity"]
            core.require(core.digest({k: v for k, v in identity.items() if k != "candidate_id"}) == key,
                         "CANDIDATE_IDENTITY_CHANGED")
            claim = claims[key]
            core.require(claim["scope"] == self.pins.scope and claim["candidate_id"] == identity["candidate_id"]
                         and core.decode(claim["identity_json"].encode()) == identity, "CLAIM_IDENTITY_CHANGED")
            core.require(set(binding["segment_bindings"]) == set(core.SEGMENTS)
                         and set(binding["code_closure"]) == CODE_PATHS, "FROZEN_CLOSURE_OR_SEGMENTS_CHANGED")
            for path, expected in binding["code_closure"].items():
                core.require(core.sha(_repository_file(self.repo, path)) == expected, "FROZEN_CODE_CHANGED:" + path)
            parent = binding["parent_binding"]
            for path, expected in parent["loader_code_closure"].items():
                core.require(core.sha(_repository_file(self.repo, path)) == expected, "FROZEN_LOADER_CHANGED:" + path)
            for artifact in parent["data_manifest"]["artifacts"]:
                core.require(core.sha(Path(artifact["path"])) == artifact["sha256"], "FROZEN_SOURCE_ARTIFACT_CHANGED")
        minutes = _read(self.repo / CAMPAIGN / "measurement/CANONICAL_MINUTE_HASHES.json")
        core.require(len(minutes) == CANONICAL_FILE_COUNT, "CANONICAL_2196_FILE_SET_REQUIRED")
        for path, expected in minutes.items():
            core.require(core.sha(Path(path)) == expected, "CANONICAL_MINUTE_CHANGED:" + path)
        modules = self.modules_factory(self.repo)
        for binding in self.frozen.values():
            rebuilt = modules.compare.freeze_comparison(binding["parent_binding"], binding["continuous_contract"], binding["label"])
            core.require(rebuilt == binding, "FROZEN_RULES_OR_ENVIRONMENT_CHANGED")
        manifest = self.frozen["SR_CONTROL"]["parent_binding"]["data_manifest"]
        expected_inventory = _read(Path(manifest["source_inventory"]["path"]))
        actual_inventory = modules.source._inventory(Path(manifest["canonical_root"]), modules.source.MANIFEST_HASHES)
        core.require(actual_inventory == expected_inventory, "CANONICAL_SOURCE_INVENTORY_CHANGED")
        self._modules = modules

    def inspect(self) -> dict[str, Any]:
        self.ensure_no_worker()
        self.verify_frozen()
        return core.inspect(self.runtime, self.frozen["SR_CONTROL"], self.permit, self.pins)

    def _replay_missing(self, segment: str) -> Mapping[str, Any]:
        core.require(self._recovering and not self._missing_called and segment == core.SEGMENTS[1],
                     "ONLY_ONE_MISSING_CONTROL_SEGMENT_CALLBACK")
        journal = self.runtime / "checkpoint_recovery_v1"
        core.require(not os.path.lexists(journal / "STOPPED.json"), "STOPPED_RECOVERY_REQUIRES_RECONCILIATION")
        core.require(_read(journal / "SEGMENT_STARTED.json") == {"segment_id": segment, "attempt": 1},
                     "EXPLICIT_SEGMENT_START_REQUIRED")
        intent = _read(journal / "INTENT.json")
        core.require(intent["pins"] == self.pins.__dict__ and intent["permit"] == self.permit, "RECOVERY_INTENT_CHANGED")
        ledger = self._snapshot()
        core.require(core.digest(ledger["scopes"]) == self.pins.scopes_sha256
                     and core.digest(ledger["claims"]) == self.pins.claims_sha256
                     and core.digest(ledger["events"][:-1]) == self.pins.events_sha256,
                     "RECOVERY_LEDGER_BOUNDARY_CHANGED")
        event = ledger["events"][-1]
        core.require(event["event"] == "RECOVERY_STARTED" and event["identity_key"] == self.pins.control_identity
                     and event["scope"] == self.pins.scope, "RECOVERY_START_REQUIRED_BEFORE_PRICE_LOADER")
        payload = core.decode(event["payload_json"].encode())
        core.require(core.canonical(payload) == core.canonical({
            "permit_sha256": self.pins.continuation_permit_sha256,
            "reused_checkpoint_sha256": self.pins.checkpoint_sha256,
            "missing_segment": segment, "additional_full_starts": 0,
            "prior_uncheckpointed_segment_work_may_repeat": True}),
                     "RECOVERY_START_PAYLOAD_CHANGED")
        self._missing_called = True
        binding = self.frozen["SR_CONTROL"]
        parent = binding["parent_binding"]
        supplied = self._modules.loader.load(parent["data_manifest"], parent["config"])
        inputs = self._modules.compare.segment_inputs(supplied["detail_frames"], binding["continuous_contract"], segment)
        child = binding["segment_bindings"][segment]
        model = self._modules.runner.verify_binding(child, child["binding_sha256"])
        return self._modules.runner._replay(child, inputs, model)

    def recover_control(self) -> dict[str, Any]:
        core.require(not self._recovering and not self._missing_called, "NO_AUTOMATIC_RECOVERY_RETRY")
        self._recovering = True
        try:
            return core.recover_control(self.runtime, self.frozen["SR_CONTROL"], self.permit, self.pins,
                                        verify_frozen=self.verify_frozen, ensure_no_worker=self.ensure_no_worker,
                                        replay_missing=self._replay_missing)
        finally:
            self._recovering = False

    def reconcile_control(self, *, expected_intent_sha256: str, expected_result_sha256: str,
                          expected_second_checkpoint_sha256: str) -> dict[str, Any]:
        return core.reconcile_control(
            self.runtime, self.frozen["SR_CONTROL"], self.permit, self.pins,
            expected_intent_sha256=expected_intent_sha256, expected_result_sha256=expected_result_sha256,
            expected_second_checkpoint_sha256=expected_second_checkpoint_sha256,
            verify_frozen=self.verify_frozen, ensure_no_worker=self.ensure_no_worker,
        )

    def _completed_result(self, label: str, ledger: Mapping[str, Any]) -> dict[str, Any]:
        binding = self.frozen[label]
        identity, binding_sha = binding["identity_key"], binding["binding_sha256"]
        claims = {row["identity_key"]: row for row in ledger["claims"]}
        claim = claims[identity]
        core.require(claim["state"] == "COMPLETED" and claim["result_json"] is not None, label + "_NOT_COMPLETED")
        receipt = core.decode(claim["result_json"].encode())
        path = self.runtime / "results" / (label + ".json")
        core.require(receipt == {"result_path": str(path), "result_file_sha256": core.sha(path),
                                  "binding_sha256": binding_sha}, label + "_COMPLETION_RECEIPT_CHANGED")
        result = _read(path)
        core.require(result["identity_key"] == identity
                     and result["binding_sha256"] == binding_sha
                     and result["schema"] == "scalp7.measurement.segment_comparison_result.v1"
                     and result["full_execution_performed"] is True and result["full_execution_count"] == 1
                     and result["whole_period_nav"] is None and result["cross_segment_nav_aggregation"] == "FORBIDDEN"
                     and result["funding_status"] == "UNKNOWN_NOT_ZERO" and result["authority"] == core.BLOCKED
                     and set(result["segments"]) == set(result["segment_checkpoints"]) == set(core.SEGMENTS),
                     label + "_DURABLE_RESULT_CHANGED")
        for segment in core.SEGMENTS:
            cp = self.runtime / "results" / (label + "." + segment + ".checkpoint.json")
            expected = core.sha(cp)
            core.require(result["segment_checkpoints"][segment] == {"path": str(cp), "sha256": expected},
                         label + "_CHECKPOINT_RECEIPT_CHANGED")
            if label == "SR_CONTROL" and segment == core.SEGMENTS[0]:
                core.require(expected == self.pins.checkpoint_sha256, "REUSED_CHECKPOINT_CHANGED")
            saved = _read(cp)
            core.require(saved == {"outer_identity_key": identity, "segment_id": segment,
                                   "binding_sha256": binding_sha, "result": result["segments"][segment]},
                         label + "_CHECKPOINT_RESULT_CHANGED")
            core.validate_child(saved["result"], binding["segment_bindings"][segment])
        expected_header = {
            "schema": "scalp7.measurement.segment_comparison_result.v1", "identity_key": identity,
            "binding_sha256": binding_sha, "segment_checkpoints": result["segment_checkpoints"],
            "whole_period_nav": None, "cross_segment_nav_aggregation": "FORBIDDEN",
            "full_execution_performed": True, "full_execution_count": 1,
            "funding_status": "UNKNOWN_NOT_ZERO", "old_unresolved_positions": "PRESERVED_SEPARATE_PARENT_STATE",
            "authority": dict(core.BLOCKED),
        }
        core.require(core.canonical({k: v for k, v in result.items() if k != "segments"}) == core.canonical(expected_header),
                     label + "_DURABLE_HEADER_CHANGED")
        return receipt

    def _completed_control(self, ledger: Mapping[str, Any]) -> dict[str, Any]:
        core.require(self.frozen["SR_CONTROL"]["binding_sha256"] == self.pins.control_binding_sha256,
                     "CONTROL_EXTERNAL_BINDING_PIN_CHANGED")
        return self._completed_result("SR_CONTROL", ledger)

    def _retest_first_gate(self) -> dict[str, Any]:
        core.require(self.permit.get("allow_reserved_retest_first_start") is True, "RETEST_FIRST_START_PERMIT_REQUIRED")
        ledger = self._snapshot()
        self._completed_control(ledger)
        original_claims = []
        for row in ledger["claims"]:
            old = dict(row)
            if row["identity_key"] == self.pins.control_identity:
                old.update(state="RUNNING", result_json=None)
            else:
                core.require(row["state"] == "RESERVED" and row["result_json"] is None, "RETEST_NOT_UNEXECUTED_RESERVED")
            original_claims.append(old)
        core.require(core.digest(original_claims) == self.pins.claims_sha256, "ORIGINAL_CLAIMS_CHANGED")
        events = ledger["events"]
        core.require(core.digest(events[:4]) == self.pins.events_sha256, "ORIGINAL_EVENTS_CHANGED")
        tail = events[4:]
        core.require([e["event"] for e in tail] in (["RECOVERY_STARTED", "COMPLETED", "RECOVERY_COMPLETED"],
                                                   ["RECOVERY_STARTED", "COMPLETED", "RECOVERY_RECONCILED"])
                     and all(e["identity_key"] == self.pins.control_identity and e["scope"] == self.pins.scope for e in tail),
                     "CONTROL_RECOVERY_COMPLETION_EVENTS_REQUIRED")
        core.require(core.decode(tail[1]["payload_json"].encode()) == core.decode(
            next(c for c in ledger["claims"] if c["identity_key"] == self.pins.control_identity)["result_json"].encode()),
            "CONTROL_COMPLETED_EVENT_CHANGED")
        journal = self.runtime / "checkpoint_recovery_v1"
        _canonical_directory(journal)
        intent = _read(journal / "INTENT.json")
        core.require(intent["pins"] == self.pins.__dict__ and intent["permit"] == self.permit, "ORIGINAL_INTENT_CHANGED")
        original = intent["plan"]["ledger_before"]
        core.validate_snapshot(original, self.pins)
        core.require(core.canonical(intent["plan"]) == core.canonical({
            "ledger_before": original, "reused_segment": core.SEGMENTS[0], "missing_segment": core.SEGMENTS[1],
            "checkpoint_sha256": self.pins.checkpoint_sha256, "existing_full_starts": 1,
            "additional_control_full_starts": 0, "automatic_retry": False}), "ORIGINAL_INTENT_CHANGED")
        completion = core.decode(tail[1]["payload_json"].encode())
        evidence = {
            "ledger_before": original, "receipt": completion,
            "completion_journal_present": os.path.lexists(journal / "COMPLETED.json"),
            "reconciliation_payload": {
                "intent_file_sha256": core.sha(journal / "INTENT.json"),
                "result_file_sha256": completion["result_file_sha256"],
                "reused_checkpoint_sha256": self.pins.checkpoint_sha256,
                "second_checkpoint_sha256": core.sha(self.runtime / "results/SR_CONTROL.common_contiguous_2.checkpoint.json"),
                "ledger_only": True, "additional_full_starts": 0, "segment_replay_calls": 0,
                "preserves_prior_recovery_work": True,
            },
        }
        core.require(core._validate_reconciliation_ledger(ledger, evidence, self.pins), "CONTROL_RECOVERY_NOT_COMPLETED")
        for path in (self.runtime / "retest_first_start_v1", self.runtime / "results/SR_RETEST.json",
                     self.runtime / "results/SR_RETEST.json.partial"):
            core.require(not os.path.lexists(path), "EXISTING_RETEST_REQUIRES_RECOVERY")
        core.require(not list((self.runtime / "results").glob("SR_RETEST.*.checkpoint.json")), "EXISTING_RETEST_CHECKPOINT")
        return ledger

    def _retest_transition(self, before: Mapping[str, Any], after: Mapping[str, Any], receipt: Mapping[str, Any]) -> None:
        core.require(after["scopes"] == before["scopes"], "RETEST_FIRST_EXECUTION_HISTORY_CHANGED")
        expected_claims = []
        for claim in before["claims"]:
            expected = dict(claim)
            if claim["identity_key"] == self.pins.retest_identity:
                expected.update(state="COMPLETED", result_json=core.canonical(receipt).decode())
            expected_claims.append(expected)
        core.require(after["claims"] == expected_claims, "RETEST_FIRST_EXECUTION_CLAIMS_CHANGED")
        prior_events = before["events"]
        core.require(after["events"][:len(prior_events)] == prior_events, "RETEST_FIRST_EXECUTION_HISTORY_CHANGED")
        tail = after["events"][len(prior_events):]
        core.require([event["event"] for event in tail] == ["STARTED", "COMPLETED"],
                     "RETEST_FIRST_EXECUTION_HISTORY_CHANGED")
        sequence = prior_events[-1]["sequence"]
        for event, payload in zip(tail, ({}, receipt)):
            core.require(event["scope"] == self.pins.scope and event["identity_key"] == self.pins.retest_identity
                         and type(event["sequence"]) is int and event["sequence"] == sequence + 1
                         and isinstance(event["created_at"], str) and bool(event["created_at"]),
                         "RETEST_FIRST_EXECUTION_EVENT_HEADER_CHANGED")
            core.require(core.decode(event["payload_json"].encode()) == payload,
                         "RETEST_FIRST_EXECUTION_EVENT_PAYLOAD_CHANGED")
            sequence = event["sequence"]

    def run_retest_first(self) -> dict[str, Any]:
        lock_path = self.runtime / "execution.lock"
        fd = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW)
        with os.fdopen(fd, "r+b") as lock:
            _held_lock_visible(lock_path, lock.fileno())
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            _held_lock_visible(lock_path, lock.fileno())
            self.ensure_no_worker()
            self.verify_frozen()
            before = self._retest_first_gate()
            _held_lock_visible(lock_path, lock.fileno())
            journal = self.runtime / "retest_first_start_v1"
            journal.mkdir(mode=0o700)
            core.sync_directory(self.runtime)
            core.save_exclusive(journal / "INTENT.json", {"permit_sha256": self.pins.continuation_permit_sha256,
                                 "ledger_before": before, "max_existing_full_starts": 1, "max_total_full_starts": 2})
            result_path = self.runtime / "results/SR_RETEST.json"
            try:
                _held_lock_visible(lock_path, lock.fileno())
                binding = self.frozen["SR_RETEST"]
                result = self._modules.compare.run_authorized_comparison(
                    binding, expected_binding_sha256=binding["binding_sha256"],
                    registry_path=str(self.runtime / "candidate_registry.sqlite3"), scope=self.pins.scope,
                    owner=self.pins.owner, output_path=str(result_path))
                _held_lock_visible(lock_path, lock.fileno())
                after = self._snapshot()
                retest = next(c for c in after["claims"] if c["identity_key"] == self.pins.retest_identity)
                core.require(retest["state"] == "COMPLETED", "RETEST_COMPLETION_REQUIRES_RECONCILIATION")
                receipt = self._completed_result("SR_RETEST", after)
                self._retest_transition(before, after, receipt)
                self._completed_control(after)
                core.require(_read(result_path) == result, "RETEST_PUBLISHED_RESULT_CHANGED")
                _held_lock_visible(lock_path, lock.fileno())
                core.save_exclusive(journal / "COMPLETED.json", {**receipt, "total_full_started": 2,
                                      "automatic_retry": False, "additional_control_full_starts": 0})
                return result
            except BaseException as exc:
                core.save_exclusive(journal / "STOPPED.json", {"exception_type": type(exc).__name__,
                                      "durable_result_present": os.path.lexists(result_path),
                                      "automatic_retry": False, "ledger_not_reset": True})
                raise


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--pins", type=Path, required=True)
    parser.add_argument("--pins-sha256", required=True, help="Externally reviewed pins-file bytes hash; never derive from current state.")
    parser.add_argument("--permit", type=Path, required=True)
    parser.add_argument("--mode", required=True, choices=("inspect", "recover-and-retest", "reconcile-and-retest", "retest-first"))
    for name in ("intent", "result", "second-checkpoint"):
        parser.add_argument("--expected-" + name + "-sha256")
    args = parser.parse_args(argv)
    core.require(core.sha(args.pins) == args.pins_sha256, "EXTERNAL_PINS_FILE_CHANGED")
    pins = core.Pins(**_read(args.pins))
    adapter = RuntimeAdapter(args.repo, args.runtime, pins, _read(args.permit))
    if args.mode == "inspect":
        report = adapter.inspect()
    else:
        if args.mode == "recover-and-retest":
            adapter.recover_control()
        elif args.mode == "reconcile-and-retest":
            values = {"expected_" + k + "_sha256": getattr(args, "expected_" + k + "_sha256")
                      for k in ("intent", "result", "second_checkpoint")}
            core.require(all(values.values()), "EXTERNAL_RECONCILIATION_PINS_REQUIRED")
            adapter.reconcile_control(**values)
        adapter.run_retest_first()
        report = {"schema": "g4.sr.runtime_two_completed.v1", "cumulative_full_starts": 2,
                  "completed_segment_reruns": 0, "additional_control_full_starts": 0,
                  "g4_complete": False, "profitability_pass": False}
    print(core.canonical(report).decode(), flush=True)


if __name__ == "__main__":
    main()
