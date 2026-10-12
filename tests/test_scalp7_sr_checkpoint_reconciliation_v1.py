"""Ledger-only reconciliation using temporary synthetic fixtures; no source replay."""
from __future__ import annotations

import fcntl
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import scalp7_sr_checkpoint_recovery_v1 as m


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / "results").mkdir()
        (self.root / "execution.lock").touch()
        self.approval = self.root / "USER_APPROVAL.json"
        self.approval.write_text('{"fixture":"SYNTHETIC_UNIT_TEST_ONLY"}')
        self.binding = {
            "label": "SR_CONTROL", "identity_key": "control", "cross_segment_nav_aggregation": "FORBIDDEN",
            "segment_bindings": {sid: {"identity_key": sid + "-identity", "binding_sha256": sid + "-binding"}
                                 for sid in m.SEGMENTS},
        }
        self.binding["binding_sha256"] = m.digest(self.binding)
        self.checkpoint1 = self.root / "results/SR_CONTROL.common_contiguous_1.checkpoint.json"
        m.save_exclusive(self.checkpoint1, {"outer_identity_key": "control", "segment_id": m.SEGMENTS[0],
                         "binding_sha256": self.binding["binding_sha256"], "result": self.child(m.SEGMENTS[0])})
        self.first_bytes = self.checkpoint1.read_bytes()
        self.permit = {
            "scope": "scope", "owner": "owner", "original_approval_sha256": m.sha(self.approval),
            "checkpoint_sha256": m.sha(self.checkpoint1), "control_identity": "control", "retest_identity": "retest",
            "cumulative_full_cap": 2, "automatic_retry": False, "rerun_completed_segment": False,
            "service_change": False, "allow_missing_control_segment": True,
        }
        self.db_path = self.root / "candidate_registry.sqlite3"
        with sqlite3.connect(self.db_path) as db:
            db.executescript('''
                CREATE TABLE scopes(scope TEXT PRIMARY KEY,owner TEXT,max_candidates INTEGER,max_executions INTEGER,contract_json TEXT);
                CREATE TABLE claims(identity_key TEXT PRIMARY KEY,scope TEXT,candidate_id TEXT,identity_json TEXT,state TEXT,result_json TEXT);
                CREATE TABLE events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,scope TEXT,identity_key TEXT,event TEXT,payload_json TEXT,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
            ''')
            contract = {"automatic_retry": False, "max_per_identity": 1,
                        "approval_sha256": m.sha(self.approval), "allowed_identity_keys": ["control", "retest"]}
            db.execute("INSERT INTO scopes VALUES(?,?,?,?,?)", ("scope", "owner", 2, 2, json.dumps(contract)))
            for key, state in (("control", "RUNNING"), ("retest", "RESERVED")):
                db.execute("INSERT INTO claims VALUES(?,?,?,?,?,NULL)", (key, "scope", key, '{}', state))
            for key, event in ((None, "SCOPE_CREATED"), ("control", "RESERVED"), ("retest", "RESERVED"), ("control", "STARTED")):
                db.execute("INSERT INTO events(scope,identity_key,event,payload_json) VALUES(?,?,?,?)", ("scope", key, event, '{}'))
        self.before = self.snapshot()
        self.pins = m.Pins("scope", "owner", "control", "retest", self.binding["binding_sha256"],
                           m.sha(self.approval), m.digest(self.permit), m.sha(self.checkpoint1),
                           m.digest(self.before["scopes"]), m.digest(self.before["claims"]), m.digest(self.before["events"]))
        self.calls = []
        self.final = self.root / "results/SR_CONTROL.json"
        self.partial = self.root / "results/SR_CONTROL.json.partial"
        self.checkpoint2 = self.root / "results/SR_CONTROL.common_contiguous_2.checkpoint.json"
        self.journal = self.root / "checkpoint_recovery_v1"

    def child(self, sid):
        return {"schema": "zel.scalp7.exact25_model_runner.v1", "identity_key": sid + "-identity",
                "binding_sha256": sid + "-binding", "authority": dict(m.BLOCKED), "formal_promotion": "BLOCKED",
                "fresh_T": 0, "cost_scenarios": {"1x": {"fixture": True}, "2x": {"fixture": True}}}

    def snapshot(self):
        with m.database(self.db_path) as db:
            return m.snapshot(db)

    def replay(self, sid):
        self.calls.append(sid)
        return self.child(sid)

    def recover(self):
        return m.recover_control(self.root, self.binding, self.permit, self.pins,
                                verify_frozen=lambda: None, ensure_no_worker=lambda: None,
                                replay_missing=self.replay)

    def published_interruption(self, *, after_link=False):
        if after_link:
            original = m.sync_directory
            failed = [False]

            def interrupted(path):
                if path == self.root / "results" and self.final.exists() and not failed[0]:
                    failed[0] = True
                    raise OSError("SYNTHETIC_FSYNC_AFTER_LINK")
                original(path)

            with patch.object(m, "sync_directory", side_effect=interrupted):
                with self.assertRaisesRegex(OSError, "SYNTHETIC_FSYNC_AFTER_LINK"):
                    self.recover()
        else:
            original = m._event

            def interrupted(db, pins, name, payload):
                if name == "COMPLETED":
                    raise RuntimeError("SYNTHETIC_COMPLETION_ROLLBACK")
                original(db, pins, name, payload)

            with patch.object(m, "_event", side_effect=interrupted):
                with self.assertRaisesRegex(RuntimeError, "SYNTHETIC_COMPLETION_ROLLBACK"):
                    self.recover()
        # Only synthetic test fixtures self-compute hashes. Runtime callers must
        # receive these from an independent read-only evidence validation step.
        self.hashes = {"expected_intent_sha256": m.sha(self.journal / "INTENT.json"),
                       "expected_result_sha256": m.sha(self.final),
                       "expected_second_checkpoint_sha256": m.sha(self.checkpoint2)}

    def reconcile(self, **kwargs):
        args = {**self.hashes, "verify_frozen": lambda: None, "ensure_no_worker": lambda: None}
        args.update(kwargs)
        return m.reconcile_control(self.root, self.binding, self.permit, self.pins, **args)

    def replace_lock(self, *, symlink=False):
        lock = self.root / "execution.lock"
        previous = self.root / "previous-execution.lock"
        lock.rename(previous)
        if symlink:
            lock.symlink_to("previous-execution.lock")
        else:
            lock.touch()

    def restore_lock(self):
        (self.root / "execution.lock").unlink()
        (self.root / "previous-execution.lock").rename(self.root / "execution.lock")

    def files(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*")
                if p.is_file() and p != self.db_path and not p.name.startswith("candidate_registry.sqlite3-")}

    def test_only_ledger_closes_without_new_start_or_replay(self):
        self.published_interruption()
        files, ledger = self.files(), self.snapshot()
        result = self.reconcile()
        after = self.snapshot()
        self.assertTrue(result["reconciliation_performed"])
        self.assertFalse(result["already_completed"])
        self.assertEqual(result["segment_replay_calls"], 0)
        self.assertEqual(result["additional_full_starts"], 0)
        self.assertEqual(self.calls, [m.SEGMENTS[1]])
        self.assertEqual(self.files(), files)
        self.assertEqual(self.checkpoint1.read_bytes(), self.first_bytes)
        self.assertEqual(after["scopes"], self.before["scopes"])
        self.assertEqual(after["events"][:len(ledger["events"])], ledger["events"])
        self.assertEqual([e["event"] for e in after["events"][-2:]], ["COMPLETED", "RECOVERY_RECONCILED"])
        self.assertEqual(sum(e["event"] == "STARTED" for e in after["events"]), 1)
        self.assertEqual(sum(e["event"] == "RECOVERY_STARTED" for e in after["events"]), 1)
        self.assertEqual({r["identity_key"]: r["state"] for r in after["claims"]},
                         {"control": "COMPLETED", "retest": "RESERVED"})
        self.assertEqual(m.decode(after["claims"][0]["result_json"].encode()), result["receipt"])

    def test_matching_second_call_is_noop(self):
        self.published_interruption()
        self.reconcile()
        ledger, db_bytes, files = self.snapshot(), self.db_path.read_bytes(), self.files()
        again = self.reconcile()
        self.assertTrue(again["already_completed"])
        self.assertFalse(again["reconciliation_performed"])
        self.assertEqual(self.snapshot(), ledger)
        self.assertEqual(self.db_path.read_bytes(), db_bytes)
        self.assertEqual(self.files(), files)
        self.assertEqual(self.calls, [m.SEGMENTS[1]])

    def test_original_successful_completion_is_verified_noop(self):
        self.recover()
        self.hashes = {"expected_intent_sha256": m.sha(self.journal / "INTENT.json"),
                       "expected_result_sha256": m.sha(self.final),
                       "expected_second_checkpoint_sha256": m.sha(self.checkpoint2)}
        ledger = self.snapshot()
        result = self.reconcile()
        self.assertTrue(result["already_completed"])
        self.assertEqual(self.snapshot(), ledger)

    def test_database_commit_before_completion_journal_crash_is_noop(self):
        original = m.save_exclusive

        def interrupted(path, value):
            if path == self.journal / "COMPLETED.json":
                raise OSError("SYNTHETIC_JOURNAL_AFTER_DATABASE_COMMIT")
            original(path, value)

        with patch.object(m, "save_exclusive", side_effect=interrupted), self.assertRaises(OSError):
            self.recover()
        self.assertFalse((self.journal / "COMPLETED.json").exists())
        self.hashes = {"expected_intent_sha256": m.sha(self.journal / "INTENT.json"),
                       "expected_result_sha256": m.sha(self.final),
                       "expected_second_checkpoint_sha256": m.sha(self.checkpoint2)}
        ledger, files = self.snapshot(), self.files()
        result = self.reconcile()
        self.assertTrue(result["already_completed"])
        self.assertEqual(self.snapshot(), ledger)
        self.assertEqual(self.files(), files)

    def test_link_fsync_failure_uses_actual_files_and_preserves_partial_and_stop(self):
        self.published_interruption(after_link=True)
        stop = m.decode((self.journal / "STOPPED.json").read_bytes())
        self.assertFalse(stop["durable_result_published"])
        self.assertEqual(self.partial.read_bytes(), self.final.read_bytes())
        files = self.files()
        self.assertTrue(self.reconcile()["reconciliation_performed"])
        self.assertEqual(self.files(), files)

    def test_partial_only_never_published_or_replayed(self):
        self.published_interruption(after_link=True)
        self.final.unlink()
        ledger, files = self.snapshot(), self.files()
        with self.assertRaisesRegex(ValueError, "EXISTING_FINAL_RESULT_REQUIRED"):
            self.reconcile()
        self.assertFalse(self.final.exists())
        self.assertEqual(self.files(), files)
        self.assertEqual(self.snapshot(), ledger)

    def test_conflicting_partial_rejected(self):
        self.published_interruption(after_link=True)
        self.partial.unlink()
        self.partial.write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, "PARTIAL_RESULT_CONFLICT"):
            self.reconcile()

    def test_result_hash_and_second_checkpoint_hash_required(self):
        self.published_interruption()
        for key in ("expected_intent_sha256", "expected_result_sha256", "expected_second_checkpoint_sha256"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.reconcile(**{key: "0" * 64})
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "EXTERNAL_EVIDENCE_HASH_REQUIRED"):
                self.reconcile(**{key: ""})

    def test_original_intent_self_repin_does_not_adopt_changed_ledger(self):
        self.published_interruption()
        intent_path = self.journal / "INTENT.json"
        intent = m.decode(intent_path.read_bytes())
        intent["plan"]["ledger_before"]["events"][0]["payload_json"] = '{"changed":true}'
        intent_path.write_bytes(m.canonical(intent))
        with self.assertRaisesRegex(ValueError, "LEDGER_CHANGED:events"):
            self.reconcile(expected_intent_sha256=m.sha(intent_path))

    def test_original_event_or_recovery_payload_change_rejected(self):
        self.published_interruption()
        for name in ("STARTED", "RECOVERY_STARTED"):
            with self.subTest(event=name):
                with sqlite3.connect(self.db_path) as db:
                    old = db.execute("SELECT payload_json FROM events WHERE event=?", (name,)).fetchone()[0]
                    db.execute("UPDATE events SET payload_json='{}' WHERE event=?", (name,))
                    if old == '{}':
                        db.execute("UPDATE events SET payload_json='[]' WHERE event=?", (name,))
                with self.assertRaises(ValueError):
                    self.reconcile()
                with sqlite3.connect(self.db_path) as db:
                    db.execute("UPDATE events SET payload_json=? WHERE event=?", (old, name))

    def test_failed_or_started_retest_state_never_reset(self):
        self.published_interruption()
        for key, state in (("control", "FAILED"), ("retest", "RUNNING")):
            with self.subTest(identity=key):
                with sqlite3.connect(self.db_path) as db:
                    old = db.execute("SELECT state FROM claims WHERE identity_key=?", (key,)).fetchone()[0]
                    db.execute("UPDATE claims SET state=? WHERE identity_key=?", (state, key))
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    self.reconcile()
                self.assertEqual(self.snapshot(), before)
                with sqlite3.connect(self.db_path) as db:
                    db.execute("UPDATE claims SET state=? WHERE identity_key=?", (old, key))

    def test_extra_started_or_recovery_started_rejected(self):
        self.published_interruption()
        with sqlite3.connect(self.db_path) as db:
            db.execute("INSERT INTO events(scope,identity_key,event,payload_json) VALUES('scope','control','STARTED','{}')")
        ledger = self.snapshot()
        with self.assertRaisesRegex(ValueError, "RECOVERY_EVENT_CHAIN_CHANGED"):
            self.reconcile()
        self.assertEqual(self.snapshot(), ledger)

    def test_frozen_or_worker_callback_failure_writes_nothing(self):
        self.published_interruption()
        ledger, files = self.snapshot(), self.files()

        def fail():
            raise PermissionError("SYNTHETIC_UNVERIFIABLE")

        for callback in ("verify_frozen", "ensure_no_worker"):
            with self.subTest(callback=callback), self.assertRaises(PermissionError):
                self.reconcile(**{callback: fail})
        self.assertEqual(self.snapshot(), ledger)
        self.assertEqual(self.files(), files)

    def test_lock_collision_prevents_callbacks_and_mutation(self):
        self.published_interruption()
        ledger = self.snapshot()
        with (self.root / "execution.lock").open('r+b') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            callback = unittest.mock.Mock()
            with self.assertRaises(BlockingIOError):
                self.reconcile(verify_frozen=callback, ensure_no_worker=callback)
            callback.assert_not_called()
        self.assertEqual(self.snapshot(), ledger)

    def test_recovery_callback_lock_rename_or_relative_symlink_rejected_before_writes(self):
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                def changed():
                    self.replace_lock(symlink=symlink)

                with self.assertRaisesRegex(ValueError, "LOCK_INODE_CHANGED|REGULAR_LOCK_REQUIRED"):
                    m.recover_control(self.root, self.binding, self.permit, self.pins,
                                      verify_frozen=changed, ensure_no_worker=lambda: None,
                                      replay_missing=self.replay)
                self.assertEqual(self.snapshot(), self.before)
                self.assertEqual(self.calls, [])
                self.assertFalse(self.journal.exists())
                self.restore_lock()

    def test_reconciliation_callback_lock_rename_or_relative_symlink_rejected(self):
        self.published_interruption()
        ledger = self.snapshot()
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                def changed():
                    self.replace_lock(symlink=symlink)

                with self.assertRaisesRegex(ValueError, "LOCK_INODE_CHANGED|REGULAR_LOCK_REQUIRED"):
                    self.reconcile(verify_frozen=changed)
                self.assertEqual(self.snapshot(), ledger)
                self.assertEqual(self.calls, [m.SEGMENTS[1]])
                self.restore_lock()

    def test_recovery_lock_replaced_by_replay_preserves_stop_without_publication(self):
        def changed(sid):
            result = self.replay(sid)
            self.replace_lock()
            return result

        with self.assertRaisesRegex(ValueError, "LOCK_INODE_CHANGED"):
            m.recover_control(self.root, self.binding, self.permit, self.pins,
                              verify_frozen=lambda: None, ensure_no_worker=lambda: None,
                              replay_missing=changed)
        self.assertEqual(self.calls, [m.SEGMENTS[1]])
        self.assertFalse(self.checkpoint2.exists())
        self.assertFalse(self.final.exists())
        self.assertEqual(self.checkpoint1.read_bytes(), self.first_bytes)
        self.assertFalse(m.decode((self.journal / "STOPPED.json").read_bytes())["automatic_retry"])
        self.assertEqual(sum(e["event"] == "COMPLETED" for e in self.snapshot()["events"]), 0)
        self.restore_lock()
        with self.assertRaisesRegex(ValueError, "EXISTING_RECOVERY_OR_RESULT"):
            self.recover()
        self.assertEqual(self.calls, [m.SEGMENTS[1]])

    def test_recovery_lock_replaced_after_checkpoint_preserves_checkpoint_not_final(self):
        original = m.save_exclusive

        def changed(path, value):
            original(path, value)
            if path == self.checkpoint2:
                self.replace_lock()

        with patch.object(m, "save_exclusive", side_effect=changed), self.assertRaisesRegex(ValueError, "LOCK_INODE_CHANGED"):
            self.recover()
        self.assertTrue(self.checkpoint2.exists())
        self.assertFalse(self.partial.exists())
        self.assertFalse(self.final.exists())
        self.assertTrue((self.journal / "STOPPED.json").exists())
        self.assertEqual(sum(e["event"] == "COMPLETED" for e in self.snapshot()["events"]), 0)

    def test_recovery_lock_replaced_after_partial_does_not_link_final(self):
        original = m.save_exclusive

        def changed(path, value):
            original(path, value)
            if path == self.partial:
                self.replace_lock(symlink=True)

        with patch.object(m, "save_exclusive", side_effect=changed), self.assertRaisesRegex(ValueError, "REGULAR_LOCK_REQUIRED"):
            self.recover()
        self.assertTrue(self.partial.exists())
        self.assertFalse(self.final.exists())
        self.assertEqual(sum(e["event"] == "COMPLETED" for e in self.snapshot()["events"]), 0)

    def test_recovery_lock_replaced_during_completion_event_rolls_back(self):
        original = m._event

        def changed(db, pins, name, payload):
            original(db, pins, name, payload)
            if name == "COMPLETED":
                self.replace_lock()

        with patch.object(m, "_event", side_effect=changed), self.assertRaisesRegex(ValueError, "LOCK_INODE_CHANGED"):
            self.recover()
        self.assertTrue(self.final.exists())
        self.assertTrue(m.decode((self.journal / "STOPPED.json").read_bytes())["durable_result_published"])
        self.assertEqual(sum(e["event"] == "COMPLETED" for e in self.snapshot()["events"]), 0)
        self.assertEqual({r["identity_key"]: r["state"] for r in self.snapshot()["claims"]},
                         {"control": "RUNNING", "retest": "RESERVED"})

    def test_reconciliation_lock_replaced_at_durability_barrier_rolls_back(self):
        self.published_interruption()
        ledger = self.snapshot()
        original = m.sync_directory

        def changed(path):
            original(path)
            self.replace_lock(symlink=True)

        with patch.object(m, "sync_directory", side_effect=changed), self.assertRaisesRegex(ValueError, "REGULAR_LOCK_REQUIRED"):
            self.reconcile()
        self.assertEqual(self.snapshot(), ledger)
        self.assertEqual(self.calls, [m.SEGMENTS[1]])

    def test_reconciliation_lock_replaced_during_completion_event_rolls_back(self):
        self.published_interruption()
        ledger = self.snapshot()
        original = m._event

        def changed(db, pins, name, payload):
            original(db, pins, name, payload)
            if name == "RECOVERY_RECONCILED":
                self.replace_lock()

        with patch.object(m, "_event", side_effect=changed), self.assertRaisesRegex(ValueError, "LOCK_INODE_CHANGED"):
            self.reconcile()
        self.assertEqual(self.snapshot(), ledger)
        self.assertEqual(self.calls, [m.SEGMENTS[1]])

    def test_callback_ledger_drift_not_adopted(self):
        self.published_interruption()

        def changed():
            with sqlite3.connect(self.db_path) as db:
                db.execute("UPDATE scopes SET max_executions=3")

        with self.assertRaisesRegex(ValueError, "ORIGINAL_SCOPE_CHANGED"):
            self.reconcile(verify_frozen=changed)
        self.assertEqual(sum(e["event"] == "COMPLETED" for e in self.snapshot()["events"]), 0)

    def test_callback_result_drift_not_adopted(self):
        self.published_interruption()

        def changed():
            self.final.write_bytes(self.final.read_bytes() + b' ')

        with self.assertRaisesRegex(ValueError, "RESULT_HASH_CHANGED"):
            self.reconcile(verify_frozen=changed)

    def test_source_approval_and_checkpoint_one_remain_original_pins(self):
        self.published_interruption()
        for path in (self.approval, self.checkpoint1):
            with self.subTest(path=path):
                original = path.read_bytes()
                path.write_bytes(original + b' ')
                with self.assertRaises(ValueError):
                    self.reconcile()
                path.write_bytes(original)

    def test_rehashed_result_authority_or_nav_change_still_rejected(self):
        self.published_interruption()
        original = self.final.read_bytes()
        for key, value in (("authority", {"live": "ENABLED", "order": "BLOCKED", "promotion": False}),
                           ("whole_period_nav", [1, 2]), ("full_execution_count", 2)):
            with self.subTest(key=key):
                result = m.decode(original)
                result[key] = value
                self.final.write_bytes(m.canonical(result))
                with self.assertRaisesRegex(ValueError, "PUBLISHED_RESULT_EVIDENCE_CONFLICT"):
                    self.reconcile(expected_result_sha256=m.sha(self.final))
        self.final.write_bytes(original)

    def test_rehashed_second_checkpoint_header_still_rejected(self):
        self.published_interruption()
        saved = m.decode(self.checkpoint2.read_bytes())
        saved["outer_identity_key"] = "other"
        self.checkpoint2.write_bytes(m.canonical(saved))
        with self.assertRaisesRegex(ValueError, "CHECKPOINT_BINDING_CHANGED"):
            self.reconcile(expected_second_checkpoint_sha256=m.sha(self.checkpoint2))

    def test_final_and_checkpoint_child_must_be_same_saved_result(self):
        self.published_interruption()
        result = m.decode(self.final.read_bytes())
        result["segments"][m.SEGMENTS[1]]["cost_scenarios"]["1x"]["changed"] = True
        self.final.write_bytes(m.canonical(result))
        with self.assertRaisesRegex(ValueError, "PUBLISHED_RESULT_EVIDENCE_CONFLICT"):
            self.reconcile(expected_result_sha256=m.sha(self.final))

    def test_completed_receipt_conflict_rejected_instead_of_reset(self):
        self.published_interruption()
        self.reconcile()
        with sqlite3.connect(self.db_path) as db:
            db.execute("UPDATE claims SET result_json='{}' WHERE identity_key='control'")
        ledger = self.snapshot()
        with self.assertRaisesRegex(ValueError, "CONTROL_CLAIM_CHANGED"):
            self.reconcile()
        self.assertEqual(self.snapshot(), ledger)

    def test_completed_journal_with_running_ledger_is_not_adopted(self):
        self.published_interruption()
        receipt = {"result_path": str(self.final), "result_file_sha256": self.hashes["expected_result_sha256"],
                   "binding_sha256": self.pins.control_binding_sha256}
        m.save_exclusive(self.journal / "COMPLETED.json", {**receipt, "control_completed": True,
                         "retest_started_by_recovery": False, "additional_control_full_starts": 0})
        ledger = self.snapshot()
        with self.assertRaisesRegex(ValueError, "COMPLETION_JOURNAL_CONFLICT"):
            self.reconcile()
        self.assertEqual(self.snapshot(), ledger)

    def test_fsync_failure_rolls_back_ledger_without_deleting_evidence(self):
        self.published_interruption()
        ledger, files = self.snapshot(), self.files()
        with patch.object(m, "sync_directory", side_effect=OSError("SYNTHETIC_FSYNC_FAILURE")):
            with self.assertRaises(OSError):
                self.reconcile()
        self.assertEqual(self.snapshot(), ledger)
        self.assertEqual(self.files(), files)

    def test_file_drift_at_durability_barrier_prevents_database_commit(self):
        self.published_interruption()
        ledger = self.snapshot()
        original = m.sync_directory

        def changed(path):
            original(path)
            self.final.write_bytes(self.final.read_bytes() + b' ')

        with patch.object(m, "sync_directory", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "EVIDENCE_CHANGED_BEFORE_COMMIT:SR_CONTROL.json"):
                self.reconcile()
        self.assertEqual(self.snapshot(), ledger)
        self.assertEqual(self.calls, [m.SEGMENTS[1]])

    def test_database_completion_failure_rolls_back_without_new_recovery_start(self):
        self.published_interruption()
        ledger = self.snapshot()
        original = m._event

        def interrupted(db, pins, name, payload):
            if name == "RECOVERY_RECONCILED":
                raise RuntimeError("SYNTHETIC_RECONCILIATION_ROLLBACK")
            original(db, pins, name, payload)

        with patch.object(m, "_event", side_effect=interrupted), self.assertRaises(RuntimeError):
            self.reconcile()
        self.assertEqual(self.snapshot(), ledger)
        self.assertEqual(self.calls, [m.SEGMENTS[1]])

    def test_symlink_final_or_journal_rejected(self):
        self.published_interruption()
        saved = self.root / "saved-final.json"
        self.final.rename(saved)
        self.final.symlink_to(saved)
        with self.assertRaises(OSError):
            self.reconcile()
        self.final.unlink()
        saved.rename(self.final)
        real_journal = self.root / "saved-journal"
        self.journal.rename(real_journal)
        self.journal.symlink_to(real_journal, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "EXISTING_CANONICAL_JOURNAL_REQUIRED"):
            self.reconcile()


if __name__ == '__main__':
    unittest.main()
