"""Synthetic unit tests only. No genuine source loader, VPS, or strategy import."""
from __future__ import annotations

import dataclasses
import fcntl
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts import scalp7_sr_checkpoint_recovery_v1 as m


class RecoveryTests(unittest.TestCase):
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
        self.first_result = self.child(m.SEGMENTS[0])
        self.checkpoint = self.root / "results/SR_CONTROL.common_contiguous_1.checkpoint.json"
        m.save_exclusive(self.checkpoint, {
            "outer_identity_key": "control", "segment_id": m.SEGMENTS[0],
            "binding_sha256": self.binding["binding_sha256"], "result": self.first_result,
        })
        self.first_bytes = self.checkpoint.read_bytes()
        self.permit = {
            "scope": "scope", "owner": "owner", "original_approval_sha256": m.sha(self.approval),
            "checkpoint_sha256": m.sha(self.checkpoint), "control_identity": "control", "retest_identity": "retest",
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
                           m.sha(self.approval), m.digest(self.permit), m.sha(self.checkpoint),
                           m.digest(self.before["scopes"]), m.digest(self.before["claims"]), m.digest(self.before["events"]))
        self.calls = []

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

    def run_recovery(self, **kwargs):
        args = {"verify_frozen": lambda: None, "ensure_no_worker": lambda: None, "replay_missing": self.replay}
        args.update(kwargs)
        return m.recover_control(self.root, self.binding, self.permit, self.pins, **args)

    def test_readonly_inspection_has_no_side_effects(self):
        db_before = self.db_path.read_bytes()
        plan = m.inspect(self.root, self.binding, self.permit, self.pins)
        self.assertEqual(plan["additional_control_full_starts"], 0)
        self.assertEqual(self.db_path.read_bytes(), db_before)
        self.assertFalse((self.root / "checkpoint_recovery_v1").exists())

    def test_only_missing_segment_replayed_original_bytes_and_start_preserved(self):
        result = self.run_recovery()
        after = self.snapshot()
        self.assertEqual(self.calls, [m.SEGMENTS[1]])
        self.assertEqual(self.checkpoint.read_bytes(), self.first_bytes)
        self.assertEqual(result["segments"][m.SEGMENTS[0]], self.first_result)
        self.assertEqual(after["events"][:4], self.before["events"])
        self.assertEqual(after["scopes"], self.before["scopes"])
        self.assertEqual(sum(e["event"] == "STARTED" for e in after["events"]), 1)
        self.assertEqual({c["identity_key"]: c["state"] for c in after["claims"]}, {"control": "COMPLETED", "retest": "RESERVED"})
        self.assertEqual(result["full_execution_count"], 1)
        self.assertIsNone(result["whole_period_nav"])
        self.assertEqual(result["funding_status"], "UNKNOWN_NOT_ZERO")
        self.assertEqual(result["authority"], m.BLOCKED)
        self.assertEqual(m.decode(after["claims"][0]["result_json"].encode())["result_file_sha256"],
                         m.sha(self.root / "results/SR_CONTROL.json"))

    def test_second_invocation_is_not_an_automatic_retry(self):
        self.run_recovery()
        before = self.snapshot()
        with self.assertRaises(ValueError): self.run_recovery()
        self.assertEqual(self.calls, [m.SEGMENTS[1]])
        self.assertEqual(self.snapshot(), before)

    def test_existing_second_checkpoint_is_not_overwritten(self):
        p = self.root / "results/SR_CONTROL.common_contiguous_2.checkpoint.json"
        p.write_text('{}')
        with self.assertRaises(ValueError): self.run_recovery()
        self.assertEqual(p.read_text(), '{}')
        self.assertEqual(self.calls, [])

    def test_existing_final_partial_and_retest_checkpoint_fail_closed(self):
        for name in ("SR_CONTROL.json", "SR_CONTROL.json.partial", "SR_RETEST.json", "SR_RETEST.json.partial",
                     "SR_RETEST.common_contiguous_1.checkpoint.json"):
            with self.subTest(name=name):
                p = self.root / "results" / name
                p.write_text('{}')
                with self.assertRaises(ValueError): self.run_recovery()
                p.unlink()
        self.assertEqual(self.calls, [])

    def test_corrupted_first_checkpoint_rejected_before_writes(self):
        self.checkpoint.write_bytes(self.first_bytes + b' ')
        with self.assertRaisesRegex(ValueError, "CHECKPOINT_HASH_CHANGED"): self.run_recovery()
        self.assertEqual(self.snapshot(), self.before)
        self.assertEqual(self.calls, [])

    def test_changed_binding_rejected(self):
        self.binding["label"] = "SR_RETEST"
        with self.assertRaises(ValueError): self.run_recovery()
        self.assertEqual(self.calls, [])

    def test_changed_original_approval_rejected(self):
        self.approval.write_text('{}')
        with self.assertRaisesRegex(ValueError, "APPROVAL_FILE_CHANGED"): self.run_recovery()
        self.assertEqual(self.calls, [])

    def test_changed_permit_rejected(self):
        self.permit["cumulative_full_cap"] = 3
        with self.assertRaisesRegex(ValueError, "CONTINUATION_PERMIT_CHANGED"): self.run_recovery()

    def test_rehashed_unsafe_permit_still_rejected(self):
        for key, value in (("automatic_retry", True), ("rerun_completed_segment", True), ("service_change", True),
                           ("allow_missing_control_segment", False), ("cumulative_full_cap", 3)):
            with self.subTest(key=key):
                original = self.permit[key]
                self.permit[key] = value
                pins = dataclasses.replace(self.pins, continuation_permit_sha256=m.digest(self.permit))
                with self.assertRaisesRegex(ValueError, "PERMIT_BOUNDARY_CHANGED"):
                    m.inspect(self.root, self.binding, self.permit, pins)
                self.permit[key] = original

    def test_changed_owner_cap_and_state_rejected(self):
        mutations = (("UPDATE scopes SET owner='other'", "UPDATE scopes SET owner='owner'"),
                     ("UPDATE scopes SET max_executions=3", "UPDATE scopes SET max_executions=2"),
                     ("UPDATE claims SET state='FAILED' WHERE identity_key='control'", "UPDATE claims SET state='RUNNING' WHERE identity_key='control'"))
        for mutation, restore in mutations:
            with self.subTest(mutation=mutation):
                with sqlite3.connect(self.db_path) as db: db.execute(mutation)
                with self.assertRaisesRegex(ValueError, "LEDGER_CHANGED"): self.run_recovery()
                with sqlite3.connect(self.db_path) as db: db.execute(restore)
        self.assertEqual(self.calls, [])

    def test_original_event_edit_rejected(self):
        with sqlite3.connect(self.db_path) as db: db.execute("UPDATE events SET payload_json='{\"changed\":true}' WHERE event='STARTED'")
        with self.assertRaisesRegex(ValueError, "LEDGER_CHANGED:events"): self.run_recovery()

    def test_extra_started_event_rejected(self):
        with sqlite3.connect(self.db_path) as db: db.execute("INSERT INTO events(scope,identity_key,event,payload_json) VALUES('scope','control','STARTED','{}')")
        with self.assertRaises(ValueError): self.run_recovery()
        self.assertEqual(self.calls, [])

    def test_frozen_verification_failure_writes_nothing(self):
        def fail(): raise ValueError("FROZEN_SOURCE_CHANGED")
        with self.assertRaisesRegex(ValueError, "FROZEN_SOURCE_CHANGED"): self.run_recovery(verify_frozen=fail)
        self.assertEqual(self.snapshot(), self.before)
        self.assertFalse((self.root / "checkpoint_recovery_v1").exists())

    def test_live_worker_or_unverifiable_process_visibility_writes_nothing(self):
        def fail(): raise PermissionError("PROCESS_VISIBILITY_UNAVAILABLE")
        with self.assertRaises(PermissionError): self.run_recovery(ensure_no_worker=fail)
        self.assertEqual(self.snapshot(), self.before)

    def test_held_execution_lock_prevents_execution(self):
        with (self.root / "execution.lock").open('r+b') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError): self.run_recovery()
        self.assertEqual(self.calls, [])

    def test_missing_registry_or_lock_never_created(self):
        self.db_path.unlink()
        with self.assertRaises(ValueError): self.run_recovery()
        self.assertFalse(self.db_path.exists())

    def test_missing_lock_never_created(self):
        p = self.root / "execution.lock"
        p.unlink()
        with self.assertRaises(FileNotFoundError): self.run_recovery()
        self.assertFalse(p.exists())

    def test_symlink_checkpoint_and_dangling_final_rejected(self):
        target = self.root / "saved.json"
        self.checkpoint.rename(target)
        self.checkpoint.symlink_to(target)
        with self.assertRaises(OSError): self.run_recovery()
        self.checkpoint.unlink(); target.rename(self.checkpoint)
        (self.root / "results/SR_CONTROL.json").symlink_to(self.root / "absent")
        with self.assertRaises(ValueError): self.run_recovery()

    def test_symlink_runtime_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "CANONICAL_RUNTIME_REQUIRED"):
            m.inspect(alias, self.binding, self.permit, self.pins)

    def test_replay_failure_records_stop_never_resets_or_retries(self):
        def fail(sid):
            self.calls.append(sid)
            raise RuntimeError('synthetic interrupted replay')
        with self.assertRaises(RuntimeError): self.run_recovery(replay_missing=fail)
        after = self.snapshot()
        self.assertEqual(after["claims"], self.before["claims"])
        self.assertEqual(after["events"][:4], self.before["events"])
        self.assertEqual(after["events"][-1]["event"], "RECOVERY_STARTED")
        stopped = m.decode((self.root / "checkpoint_recovery_v1/STOPPED.json").read_bytes())
        self.assertFalse(stopped["automatic_retry"])
        self.assertFalse(stopped["durable_result_published"])
        with self.assertRaises(ValueError): self.run_recovery()
        self.assertEqual(self.calls, [m.SEGMENTS[1]])

    def test_wrong_child_identity_prevents_publication(self):
        def wrong(sid):
            result = self.child(sid); result["identity_key"] = "other"
            return result
        with self.assertRaisesRegex(ValueError, "CHILD_IDENTITY_CHANGED"): self.run_recovery(replay_missing=wrong)
        self.assertFalse((self.root / "results/SR_CONTROL.json").exists())

    def test_authority_or_nan_child_prevents_publication(self):
        result = self.child(m.SEGMENTS[1]); result["authority"]["live"] = "ENABLED"
        with self.assertRaisesRegex(ValueError, "AUTHORITY_CHANGED"):
            m.validate_child(result, self.binding["segment_bindings"][m.SEGMENTS[1]])
        result = self.child(m.SEGMENTS[1]); result['bad'] = float('nan')
        with self.assertRaises(ValueError): m.validate_child(result, self.binding["segment_bindings"][m.SEGMENTS[1]])

    def test_checkpoint_changed_during_replay_not_adopted(self):
        def changed(sid):
            self.checkpoint.write_bytes(self.first_bytes + b' ')
            return self.child(sid)
        with self.assertRaisesRegex(ValueError, "REUSED_CHECKPOINT_CHANGED"): self.run_recovery(replay_missing=changed)
        self.assertFalse((self.root / "results/SR_CONTROL.json").exists())

    def test_ledger_changed_during_replay_preserves_durable_result_for_reconciliation(self):
        def changed(sid):
            with sqlite3.connect(self.db_path) as db: db.execute("UPDATE events SET payload_json='[]' WHERE event='RECOVERY_STARTED'")
            return self.child(sid)
        with self.assertRaisesRegex(ValueError, "LEDGER_CHANGED_DURING_RECOVERY"): self.run_recovery(replay_missing=changed)
        self.assertTrue((self.root / "results/SR_CONTROL.json").exists())
        stopped = m.decode((self.root / "checkpoint_recovery_v1/STOPPED.json").read_bytes())
        self.assertTrue(stopped["durable_result_published"])
        self.assertEqual(sum(e['event'] == 'COMPLETED' for e in self.snapshot()['events']), 0)

    def test_registry_drift_in_validation_callback_rejected(self):
        def changed():
            with sqlite3.connect(self.db_path) as db: db.execute("UPDATE claims SET state='RUNNING' WHERE identity_key='retest'")
        with self.assertRaises(ValueError): self.run_recovery(verify_frozen=changed)
        self.assertFalse((self.root / "checkpoint_recovery_v1").exists())

    def test_invalid_json_rejected(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError): m.decode(raw)

    def test_exclusive_write_never_overwrites(self):
        path = self.root / 'exclusive.json'
        m.save_exclusive(path, {'first': True})
        with self.assertRaises(FileExistsError): m.save_exclusive(path, {'first': False})
        self.assertEqual(m.decode(path.read_bytes()), {'first': True})


if __name__ == '__main__':
    unittest.main()
