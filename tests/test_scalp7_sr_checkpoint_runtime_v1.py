"""Synthetic caller-boundary tests; no genuine modules, candles, VPS, or FULL."""

from __future__ import annotations

import dataclasses
import fcntl
import os
import sqlite3
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import scalp7_sr_checkpoint_runtime_v1 as m

core = m.core


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.repo, self.runtime, self.proc = [self.root / name for name in ("repo", "runtime", "proc")]
        for path in (self.repo, self.runtime / "results", self.proc / str(os.getpid())):
            path.mkdir(parents=True)
        (self.runtime / "execution.lock").touch()
        (self.proc / "mounts").write_text(f"proc {self.proc} proc rw,hidepid=0 0 0\n")
        (self.proc / "locks").write_text("")
        (self.proc / str(os.getpid()) / "cmdline").write_bytes(b"synthetic-unit-test\0")
        self.campaign = self.repo / m.CAMPAIGN
        (self.campaign / "next_freezes").mkdir(parents=True)
        (self.campaign / "measurement").mkdir()
        self.code = {}
        for relative in sorted(m.CODE_PATHS):
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# SYNTHETIC_UNIT_TEST_ONLY\n")
            self.code[relative] = core.sha(path)
        loader_path = self.repo / "backend/research/rebuild/scalp7_exact25_model_data_v1.py"
        loader_path.write_text("# SYNTHETIC_UNIT_TEST_ONLY\n")
        self.minute = self.root / "synthetic-minute.bytes"
        self.minute.write_bytes(b"SYNTHETIC_NO_PRICE_ROWS")
        self.inventory_path = self.root / "SOURCE_INVENTORY.json"
        self.inventory = {self.minute.name: core.sha(self.minute)}
        core.save_exclusive(self.inventory_path, self.inventory)
        manifest = {"canonical_root": str(self.root), "source_inventory": {"path": str(self.inventory_path),
                    "sha256": core.sha(self.inventory_path)}, "artifacts": [{"path": str(self.inventory_path),
                    "sha256": core.sha(self.inventory_path)}]}
        self.frozen = {}
        prepared = []
        for label in ("SR_CONTROL", "SR_RETEST"):
            identity = {"candidate_id": label + "_CONTINUOUS_SEGMENTS_V1", "strategy_id": "sr_levels",
                        "baseline_id": "fixture", "changed_axis": "DATA_CONTINUITY_AND_INDEPENDENT_CAPITAL_ONLY",
                        **{k: core.digest(label + k) for k in ("rule_sha256", "data_sha256", "cost_sha256", "window_sha256")}}
            binding = {"label": label, "identity_key": core.digest({k: v for k, v in identity.items() if k != "candidate_id"}),
                       "candidate_identity": identity, "code_closure": self.code,
                       "cross_segment_nav_aggregation": "FORBIDDEN", "continuous_contract": {"fixture": True},
                       "parent_binding": {"data_manifest": manifest, "config": {}, "loader_code_closure": {
                           str(loader_path.relative_to(self.repo)): core.sha(loader_path)}},
                       "segment_bindings": {s: {"identity_key": label + s, "binding_sha256": core.digest(label + s)}
                                            for s in core.SEGMENTS}}
            binding["binding_sha256"] = core.digest(binding)
            self.frozen[label] = binding
            file = self.campaign / "next_freezes" / (label + ".json")
            core.save_exclusive(file, binding)
            prepared.append({"label": identity["candidate_id"], "identity_key": binding["identity_key"],
                             "binding_sha256": binding["binding_sha256"], "binding_file_sha256": core.sha(file)})
        core.save_exclusive(self.campaign / "NEXT_ECONOMIC_BATCH.json", {
            "scope_key": "scope", "minimum_new_full_runs": 2, "prepared_identities": prepared})
        core.save_exclusive(self.campaign / "measurement/CANONICAL_MINUTE_HASHES.json", {str(self.minute): core.sha(self.minute)})
        self.addCleanup(patch.stopall)
        patch.dict(m.FROZEN_FILES, {p: core.sha(self.campaign / p) for p in m.FROZEN_FILES}, clear=True).start()
        patch.object(m, "CANONICAL_FILE_COUNT", 1).start()
        core.save_exclusive(self.runtime / "USER_APPROVAL.json", {"scope_key": "scope", "max_candidates": 2,
            "max_executions_cumulative": 2, "max_per_identity": 1, "automatic_retry": False,
            "additional_full_authorized": 0, "approved_identities": prepared})
        self.control = self.frozen["SR_CONTROL"]["identity_key"]
        self.retest = self.frozen["SR_RETEST"]["identity_key"]
        self.checkpoint = self.runtime / "results/SR_CONTROL.common_contiguous_1.checkpoint.json"
        core.save_exclusive(self.checkpoint, self.cp("SR_CONTROL", core.SEGMENTS[0]))
        self.first_bytes = self.checkpoint.read_bytes()
        self.permit = {"scope": "scope", "owner": "owner", "original_approval_sha256": core.sha(self.runtime / "USER_APPROVAL.json"),
            "checkpoint_sha256": core.sha(self.checkpoint), "control_identity": self.control, "retest_identity": self.retest,
            "cumulative_full_cap": 2, "automatic_retry": False, "rerun_completed_segment": False,
            "service_change": False, "allow_missing_control_segment": True, "allow_reserved_retest_first_start": True}
        self.db_path = self.runtime / "candidate_registry.sqlite3"
        with sqlite3.connect(self.db_path) as db:
            db.executescript("""
                CREATE TABLE scopes(scope TEXT PRIMARY KEY,owner TEXT,max_candidates INTEGER,max_executions INTEGER,contract_json TEXT);
                CREATE TABLE claims(identity_key TEXT PRIMARY KEY,scope TEXT,candidate_id TEXT,identity_json TEXT,state TEXT,result_json TEXT);
                CREATE TABLE events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,scope TEXT,identity_key TEXT,event TEXT,payload_json TEXT,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
            """)
            contract = {"automatic_retry": False, "max_per_identity": 1, "approval_sha256": self.permit["original_approval_sha256"],
                        "allowed_identity_keys": [self.control, self.retest]}
            db.execute("INSERT INTO scopes VALUES(?,?,?,?,?)", ("scope", "owner", 2, 2, core.canonical(contract).decode()))
            for label, state in (("SR_CONTROL", "RUNNING"), ("SR_RETEST", "RESERVED")):
                b = self.frozen[label]
                db.execute("INSERT INTO claims VALUES(?,?,?,?,?,NULL)", (b["identity_key"], "scope", b["candidate_identity"]["candidate_id"],
                           core.canonical(b["candidate_identity"]).decode(), state))
            for key, event in ((None, "SCOPE_CREATED"), (self.control, "RESERVED"), (self.retest, "RESERVED"), (self.control, "STARTED")):
                self.event(db, key, event, {})
        self.before = self.snapshot()
        self.pins = core.Pins("scope", "owner", self.control, self.retest, self.frozen["SR_CONTROL"]["binding_sha256"],
            self.permit["original_approval_sha256"], core.digest(self.permit), core.sha(self.checkpoint),
            core.digest(self.before["scopes"]), core.digest(self.before["claims"]), core.digest(self.before["events"]))
        self.calls = []
        self.modules = SimpleNamespace(
            compare=SimpleNamespace(freeze_comparison=self.freeze, segment_inputs=self.segment_inputs,
                                    run_authorized_comparison=self.gateway),
            source=SimpleNamespace(_inventory=lambda *_: dict(self.inventory), MANIFEST_HASHES={}),
            loader=SimpleNamespace(load=self.load),
            runner=SimpleNamespace(verify_binding=lambda child, _: child, _replay=self.replay))
        self.adapter = m.RuntimeAdapter(self.repo, self.runtime, self.pins, self.permit,
                                        modules_factory=self.factory, proc=self.proc)

    def snapshot(self):
        with core.database(self.db_path) as db:
            return core.snapshot(db)

    def event(self, db, key, event, payload):
        db.execute("INSERT INTO events(scope,identity_key,event,payload_json) VALUES('scope',?,?,?)", (key, event, core.canonical(payload).decode()))

    def child(self, label, sid):
        child = self.frozen[label]["segment_bindings"][sid]
        return {"schema": "zel.scalp7.exact25_model_runner.v1", **child, "authority": dict(core.BLOCKED),
                "formal_promotion": "BLOCKED", "fresh_T": 0,
                "cost_scenarios": {k: {"windows": [{"complete_window": False, "net_complete_reference_usdt": None,
                    "DD_pct": None}], "fixture": "SYNTHETIC_UNIT_TEST_ONLY"} for k in ("1x", "2x")}}

    def cp(self, label, sid):
        binding = self.frozen[label]
        return {"outer_identity_key": binding["identity_key"], "binding_sha256": binding["binding_sha256"],
                "segment_id": sid, "result": self.child(label, sid)}

    def factory(self, _):
        self.calls.append("metadata_import")
        return self.modules

    def freeze(self, parent, contract, label):
        self.calls.append("metadata_freeze:" + label)
        return self.frozen[label]

    def load(self, manifest, config):
        self.assertEqual(self.snapshot()["events"][-1]["event"], "RECOVERY_STARTED")
        self.calls.append("price_loader")
        return {"detail_frames": "SYNTHETIC_UNIT_TEST_ONLY"}

    def segment_inputs(self, details, contract, sid):
        self.calls.append("segment_inputs:" + sid)
        return {"fixture": True}

    def replay(self, child, inputs, model):
        self.calls.append("replay:" + child["identity_key"])
        return self.child("SR_CONTROL", core.SEGMENTS[1])

    def gateway(self, binding, **kwargs):
        self.calls.append("original_retest_gateway")
        self.assertEqual(binding, self.frozen["SR_RETEST"])
        self.assertEqual(kwargs, {"expected_binding_sha256": binding["binding_sha256"], "registry_path": str(self.db_path),
            "scope": "scope", "owner": "owner", "output_path": str(self.runtime / "results/SR_RETEST.json")})
        before = self.snapshot()
        self.assertEqual(next(c for c in before["claims"] if c["identity_key"] == self.control)["state"], "COMPLETED")
        with sqlite3.connect(self.db_path) as db:
            db.execute("UPDATE claims SET state='RUNNING' WHERE identity_key=?", (self.retest,))
            self.event(db, self.retest, "STARTED", {})
        result = {"schema": "scalp7.measurement.segment_comparison_result.v1", "identity_key": self.retest,
            "binding_sha256": binding["binding_sha256"], "segments": {}, "segment_checkpoints": {},
            "full_execution_count": 1, "full_execution_performed": True, "whole_period_nav": None,
            "cross_segment_nav_aggregation": "FORBIDDEN", "funding_status": "UNKNOWN_NOT_ZERO", "authority": dict(core.BLOCKED),
            "old_unresolved_positions": "PRESERVED_SEPARATE_PARENT_STATE"}
        for sid in core.SEGMENTS:
            path = self.runtime / "results" / ("SR_RETEST." + sid + ".checkpoint.json")
            core.save_exclusive(path, self.cp("SR_RETEST", sid))
            result["segments"][sid] = self.child("SR_RETEST", sid)
            result["segment_checkpoints"][sid] = {"path": str(path), "sha256": core.sha(path)}
        destination = Path(kwargs["output_path"])
        core.save_exclusive(destination, result)
        receipt = {"result_path": str(destination), "result_file_sha256": core.sha(destination), "binding_sha256": binding["binding_sha256"]}
        with sqlite3.connect(self.db_path) as db:
            db.execute("UPDATE claims SET state='COMPLETED',result_json=? WHERE identity_key=?", (core.canonical(receipt).decode(), self.retest))
            self.event(db, self.retest, "COMPLETED", receipt)
        return result

    def test_metadata_only_inspection_no_imported_loader_or_replay(self):
        before = self.db_path.read_bytes()
        self.adapter.inspect()
        self.assertEqual(before, self.db_path.read_bytes())
        self.assertFalse(any(c.startswith(("price_loader", "replay", "segment_inputs", "original_retest")) for c in self.calls))
        self.assertFalse((self.runtime / "checkpoint_recovery_v1").exists())

    def test_frozen_code_mismatch_rejected_before_any_module_import(self):
        (self.repo / next(iter(m.CODE_PATHS))).write_text("# changed\n")
        with self.assertRaisesRegex(ValueError, "FROZEN_CODE_CHANGED"):
            self.adapter.recover_control()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.snapshot(), self.before)

    def test_source_bytes_mismatch_rejected_before_recovery_start(self):
        self.minute.write_bytes(b"changed source")
        with self.assertRaisesRegex(ValueError, "CANONICAL_MINUTE_CHANGED"):
            self.adapter.recover_control()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.snapshot(), self.before)

    def test_canonical_full_file_count_not_relaxed(self):
        with patch.object(m, "CANONICAL_FILE_COUNT", 2196):
            with self.assertRaisesRegex(ValueError, "CANONICAL_2196_FILE_SET_REQUIRED"):
                self.adapter.inspect()
        self.assertEqual(self.calls, [])

    def test_actual_claim_identity_json_checked_despite_matching_outer_key(self):
        with sqlite3.connect(self.db_path) as db:
            db.execute("UPDATE claims SET identity_json='{}' WHERE identity_key=?", (self.control,))
        with self.assertRaisesRegex(ValueError, "CLAIM_IDENTITY_CHANGED"):
            self.adapter.verify_frozen()
        self.assertEqual(self.calls, [])

    def test_full_source_inventory_mismatch_no_candle_call(self):
        self.modules.source._inventory = lambda *_: {"unexpected": "artifact"}
        with self.assertRaisesRegex(ValueError, "CANONICAL_SOURCE_INVENTORY_CHANGED"):
            self.adapter.recover_control()
        self.assertNotIn("price_loader", self.calls)
        self.assertEqual(self.snapshot(), self.before)

    def test_frozen_metadata_verification_mismatch_no_start(self):
        self.modules.compare.freeze_comparison = lambda *_: {"changed": True}
        with self.assertRaisesRegex(ValueError, "FROZEN_RULES_OR_ENVIRONMENT_CHANGED"):
            self.adapter.recover_control()
        self.assertEqual(self.snapshot(), self.before)
        self.assertNotIn("price_loader", self.calls)

    def test_only_missing_control_segment_after_recovery_start_no_new_full(self):
        self.adapter.recover_control()
        self.assertEqual(self.calls.count("price_loader"), 1)
        self.assertEqual([c for c in self.calls if c.startswith("segment_inputs:")], ["segment_inputs:" + core.SEGMENTS[1]])
        self.assertEqual([c for c in self.calls if c.startswith("replay:")], ["replay:" + self.frozen["SR_CONTROL"]["segment_bindings"][core.SEGMENTS[1]]["identity_key"]])
        self.assertEqual(self.checkpoint.read_bytes(), self.first_bytes)
        self.assertEqual(sum(e["event"] == "STARTED" for e in self.snapshot()["events"]), 1)

    def test_completed_control_then_original_reserved_retest_once(self):
        self.adapter.recover_control()
        self.adapter.run_retest_first()
        self.assertEqual(self.calls.count("original_retest_gateway"), 1)
        self.assertEqual(sum(e["event"] == "STARTED" for e in self.snapshot()["events"]), 2)
        self.assertEqual(self.checkpoint.read_bytes(), self.first_bytes)
        with self.assertRaises(ValueError):
            self.adapter.run_retest_first()
        self.assertEqual(self.calls.count("original_retest_gateway"), 1)

    def test_economic_incompleteness_does_not_trigger_segment_reexecution(self):
        result = self.adapter.recover_control()
        self.assertIsNone(result["segments"][core.SEGMENTS[0]]["cost_scenarios"]["1x"]["windows"][0]["DD_pct"])
        self.adapter.run_retest_first()
        self.assertEqual(self.calls.count("price_loader"), 1)

    def test_retest_blocked_while_control_running(self):
        with self.assertRaisesRegex(ValueError, "SR_CONTROL_NOT_COMPLETED"):
            self.adapter.run_retest_first()
        self.assertNotIn("original_retest_gateway", self.calls)
        self.assertFalse((self.runtime / "retest_first_start_v1").exists())

    def test_control_result_corruption_prevents_retest_first_start(self):
        self.adapter.recover_control()
        path = self.runtime / "results/SR_CONTROL.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "SR_CONTROL_COMPLETION_RECEIPT_CHANGED"):
            self.adapter.run_retest_first()
        self.assertNotIn("original_retest_gateway", self.calls)

    def test_missing_retest_permission_no_first_start(self):
        self.adapter.recover_control()
        self.adapter.permit["allow_reserved_retest_first_start"] = False
        with self.assertRaises(ValueError):
            self.adapter.run_retest_first()
        self.assertNotIn("original_retest_gateway", self.calls)

    def test_rehashed_unsafe_permit_still_rejected_in_standalone_retest_mode(self):
        self.adapter.recover_control()
        for key, value in (("cumulative_full_cap", 3), ("owner", "different"), ("automatic_retry", True)):
            with self.subTest(key=key):
                permit = {**self.permit, key: value}
                pins = dataclasses.replace(self.pins, continuation_permit_sha256=core.digest(permit))
                fresh = m.RuntimeAdapter(self.repo, self.runtime, pins, permit, modules_factory=self.factory, proc=self.proc)
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, "PERMIT_(BOUNDARY|SCOPE)_CHANGED"):
                    fresh.run_retest_first()
                self.assertEqual(self.snapshot(), before)
                self.assertFalse((self.runtime / "retest_first_start_v1").exists())
        self.assertNotIn("original_retest_gateway", self.calls)

    def test_recovery_payload_change_blocks_retest_before_any_write(self):
        self.adapter.recover_control()
        for event in ("RECOVERY_STARTED", "RECOVERY_COMPLETED"):
            with self.subTest(event=event):
                with sqlite3.connect(self.db_path) as db:
                    old = db.execute("SELECT payload_json FROM events WHERE event=?", (event,)).fetchone()[0]
                    db.execute("UPDATE events SET payload_json='{}' WHERE event=?", (event,))
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, "RECOVERY_EVENT_PAYLOAD_CHANGED"):
                    self.adapter.run_retest_first()
                self.assertEqual(self.snapshot(), before)
                self.assertFalse((self.runtime / "retest_first_start_v1").exists())
                with sqlite3.connect(self.db_path) as db:
                    db.execute("UPDATE events SET payload_json=? WHERE event=?", (old, event))
        self.assertNotIn("original_retest_gateway", self.calls)

    def test_control_completed_receipt_without_terminal_event_cannot_start_retest(self):
        self.adapter.recover_control()
        with sqlite3.connect(self.db_path) as db:
            db.execute("DELETE FROM events WHERE event='RECOVERY_COMPLETED'")
        with self.assertRaisesRegex(ValueError, "CONTROL_RECOVERY_COMPLETION_EVENTS_REQUIRED"):
            self.adapter.run_retest_first()
        self.assertNotIn("original_retest_gateway", self.calls)

    def test_lock_replacement_during_metadata_prevents_retest(self):
        self.adapter.recover_control()
        original = self.adapter.verify_frozen
        def replace_lock():
            original()
            lock = self.runtime / "execution.lock"
            lock.rename(self.runtime / "preserved-old-execution.lock")
            lock.touch()
        self.adapter.verify_frozen = replace_lock
        with self.assertRaisesRegex(ValueError, "LOCK_INODE_CHANGED"):
            self.adapter.run_retest_first()
        self.assertNotIn("original_retest_gateway", self.calls)
        self.assertFalse((self.runtime / "retest_first_start_v1").exists())

    def test_lock_symlink_replacement_during_metadata_prevents_retest(self):
        self.adapter.recover_control()
        original = self.adapter.verify_frozen
        def replace_lock():
            original()
            lock = self.runtime / "execution.lock"
            saved = self.runtime / "preserved-old-execution.lock"
            lock.rename(saved)
            lock.symlink_to(saved)
        self.adapter.verify_frozen = replace_lock
        with self.assertRaisesRegex(ValueError, "REGULAR_LOCK_REQUIRED"):
            self.adapter.run_retest_first()
        self.assertNotIn("original_retest_gateway", self.calls)
        self.assertFalse((self.runtime / "retest_first_start_v1").exists())

    def test_lock_replacement_after_gateway_preserves_result_without_completion_report(self):
        self.adapter.recover_control()
        def replace_lock(binding, **kwargs):
            result = self.gateway(binding, **kwargs)
            lock = self.runtime / "execution.lock"
            lock.rename(self.runtime / "preserved-old-execution.lock")
            lock.touch()
            return result
        self.modules.compare.run_authorized_comparison = replace_lock
        with self.assertRaisesRegex(ValueError, "LOCK_INODE_CHANGED"):
            self.adapter.run_retest_first()
        before = self.snapshot()
        self.assertEqual(next(c for c in before["claims"] if c["identity_key"] == self.retest)["state"], "COMPLETED")
        self.assertTrue((self.runtime / "results/SR_RETEST.json").exists())
        journal = self.runtime / "retest_first_start_v1"
        self.assertTrue(core.decode((journal / "STOPPED.json").read_bytes())["durable_result_present"])
        self.assertFalse((journal / "COMPLETED.json").exists())
        with self.assertRaises(ValueError):
            self.adapter.run_retest_first()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.calls.count("original_retest_gateway"), 1)

    def assert_postgateway_fault_preserved(self, statement, expected_error):
        self.adapter.recover_control()
        saved_hashes = {}
        def mutate_gateway(binding, **kwargs):
            result = self.gateway(binding, **kwargs)
            saved_hashes.update({p.name: core.sha(p) for p in (self.runtime / "results").iterdir()})
            with sqlite3.connect(self.db_path) as db:
                db.execute(statement)
            return result
        self.modules.compare.run_authorized_comparison = mutate_gateway
        with self.assertRaisesRegex(ValueError, expected_error):
            self.adapter.run_retest_first()
        before = self.snapshot()
        self.assertEqual(next(c for c in before["claims"] if c["identity_key"] == self.retest)["state"], "COMPLETED")
        self.assertEqual(saved_hashes, {p.name: core.sha(p) for p in (self.runtime / "results").iterdir()})
        journal = self.runtime / "retest_first_start_v1"
        self.assertTrue(core.decode((journal / "STOPPED.json").read_bytes())["durable_result_present"])
        self.assertFalse((journal / "COMPLETED.json").exists())
        with self.assertRaises(ValueError):
            self.adapter.run_retest_first()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.calls.count("original_retest_gateway"), 1)

    def test_retest_completed_payload_must_equal_saved_receipt(self):
        self.assert_postgateway_fault_preserved(
            "UPDATE events SET payload_json='{}' WHERE event='COMPLETED' AND sequence=(SELECT MAX(sequence) FROM events)",
            "RETEST_FIRST_EXECUTION_EVENT_PAYLOAD_CHANGED")

    def test_retest_started_payload_must_be_empty(self):
        self.assert_postgateway_fault_preserved(
            "UPDATE events SET payload_json='{\"extra_execution\":true}' WHERE event='STARTED' AND sequence>4",
            "RETEST_FIRST_EXECUTION_EVENT_PAYLOAD_CHANGED")

    def test_retest_event_scope_must_equal_original_scope(self):
        self.assert_postgateway_fault_preserved(
            "UPDATE events SET scope='other' WHERE sequence=(SELECT MAX(sequence) FROM events)",
            "RETEST_FIRST_EXECUTION_EVENT_HEADER_CHANGED")

    def test_retest_event_sequence_must_follow_existing_execution(self):
        self.assert_postgateway_fault_preserved(
            "UPDATE events SET sequence=sequence+5 WHERE sequence>7",
            "RETEST_FIRST_EXECUTION_EVENT_HEADER_CHANGED")

    def test_retest_event_timestamp_must_be_present(self):
        self.assert_postgateway_fault_preserved(
            "UPDATE events SET created_at='' WHERE sequence=(SELECT MAX(sequence) FROM events)",
            "RETEST_FIRST_EXECUTION_EVENT_HEADER_CHANGED")

    def test_retest_claim_identity_must_preserve_original_reservation(self):
        self.assert_postgateway_fault_preserved(
            "UPDATE claims SET identity_json='{}' WHERE candidate_id='SR_RETEST_CONTINUOUS_SEGMENTS_V1'",
            "RETEST_FIRST_EXECUTION_CLAIMS_CHANGED")

    def test_control_claim_must_remain_unchanged_during_retest(self):
        self.assert_postgateway_fault_preserved(
            "UPDATE claims SET candidate_id='changed' WHERE candidate_id='SR_CONTROL_CONTINUOUS_SEGMENTS_V1'",
            "RETEST_FIRST_EXECUTION_CLAIMS_CHANGED")

    def test_direct_cli_help_from_unrelated_directory_no_model_import(self):
        result = subprocess.run([sys.executable, str(Path(m.__file__).resolve()), "--help"], cwd=self.root,
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--pins-sha256", result.stdout)

    def test_cli_tampered_external_pins_rejected_before_adapter_creation(self):
        pins = self.root / "pins.json"
        permit = self.root / "permit.json"
        core.save_exclusive(pins, self.pins.__dict__)
        core.save_exclusive(permit, self.permit)
        with self.assertRaisesRegex(ValueError, "EXTERNAL_PINS_FILE_CHANGED"):
            m.main(["--repo", str(self.repo), "--runtime", str(self.runtime), "--pins", str(pins),
                    "--pins-sha256", "0" * 64, "--permit", str(permit), "--mode", "retest-first"])
        self.assertEqual(self.calls, [])

    def test_callback_cannot_load_before_recovery_journal(self):
        self.adapter.verify_frozen()
        with self.assertRaisesRegex(ValueError, "ONLY_ONE_MISSING_CONTROL_SEGMENT_CALLBACK"):
            self.adapter._replay_missing(core.SEGMENTS[1])
        self.assertNotIn("price_loader", self.calls)

    def test_completed_segment_callback_forbidden(self):
        self.adapter._recovering = True
        with self.assertRaisesRegex(ValueError, "ONLY_ONE_MISSING_CONTROL_SEGMENT_CALLBACK"):
            self.adapter._replay_missing(core.SEGMENTS[0])
        self.assertNotIn("price_loader", self.calls)

    def test_runtime_replay_failure_stop_preserved_no_automatic_retry(self):
        def fail(*_):
            self.calls.append("synthetic_replay_failure")
            raise RuntimeError("synthetic interruption")
        self.modules.runner._replay = fail
        with self.assertRaises(RuntimeError):
            self.adapter.recover_control()
        after = self.snapshot()
        with self.assertRaises(ValueError):
            self.adapter.recover_control()
        self.assertEqual(self.snapshot(), after)
        self.assertEqual(self.calls.count("price_loader"), 1)
        self.assertEqual(self.checkpoint.read_bytes(), self.first_bytes)
        self.assertTrue((self.runtime / "checkpoint_recovery_v1/STOPPED.json").exists())

    def test_new_adapter_cannot_restart_existing_journal(self):
        self.adapter.recover_control()
        fresh = m.RuntimeAdapter(self.repo, self.runtime, self.pins, self.permit, modules_factory=self.factory, proc=self.proc)
        with self.assertRaises(ValueError):
            fresh.recover_control()
        self.assertEqual(self.calls.count("price_loader"), 1)

    def test_retest_failure_even_after_publication_not_reset_or_retried(self):
        self.adapter.recover_control()
        def fail(binding, **kwargs):
            self.calls.append("failed_retest_gateway")
            core.save_exclusive(Path(kwargs["output_path"]), {"saved": "SYNTHETIC_UNIT_TEST_ONLY"})
            with sqlite3.connect(self.db_path) as db:
                db.execute("UPDATE claims SET state='FAILED',result_json='{}' WHERE identity_key=?", (self.retest,))
                self.event(db, self.retest, "STARTED", {})
                self.event(db, self.retest, "FAILED", {"budget_consumed": True})
            raise RuntimeError("synthetic finish failure after result publication")
        self.modules.compare.run_authorized_comparison = fail
        with self.assertRaises(RuntimeError):
            self.adapter.run_retest_first()
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.adapter.run_retest_first()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.calls.count("failed_retest_gateway"), 1)
        self.assertTrue(core.decode((self.runtime / "retest_first_start_v1/STOPPED.json").read_bytes())["durable_result_present"])

    def test_original_lock_conflict_no_import_or_recovery(self):
        with (self.runtime / "execution.lock").open("r+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.adapter.recover_control()
        self.assertEqual(self.calls, [])

    def test_process_visibility_missing_or_restricted_fail_closed(self):
        (self.proc / "mounts").write_text(f"proc {self.proc} proc rw,hidepid=2 0 0\n")
        with self.assertRaisesRegex(ValueError, "PROCESS_VISIBILITY_RESTRICTED"):
            self.adapter.recover_control()
        self.assertEqual(self.calls, [])
        (self.proc / "mounts").unlink()
        with self.assertRaisesRegex(PermissionError, "VISIBILITY_UNAVAILABLE"):
            self.adapter.inspect()

    def test_foreign_runtime_worker_found_even_old_registry_running_flag_irrelevant(self):
        p = self.proc / "999999"
        p.mkdir()
        (p / "cmdline").write_bytes(str(self.runtime / "worker.py").encode())
        with self.assertRaisesRegex(ValueError, "EXISTING_WORKER_REQUIRES_OBSERVATION"):
            self.adapter.recover_control()
        self.assertEqual(self.calls, [])

    def test_unreadable_live_process_not_assumed_absent(self):
        (self.proc / "999999").mkdir()
        with self.assertRaisesRegex(ValueError, "PROCESS_COMMAND_UNVERIFIABLE"):
            self.adapter.recover_control()
        self.assertEqual(self.calls, [])

    def test_foreign_lock_owner_rejected_but_self_owner_visible(self):
        s = (self.runtime / "execution.lock").stat()
        device = f"{os.major(s.st_dev):02x}:{os.minor(s.st_dev):02x}:{s.st_ino}"
        (self.proc / "locks").write_text(f"1: FLOCK ADVISORY WRITE 999999 {device} 0 EOF\n")
        with self.assertRaisesRegex(ValueError, "FOREIGN_EXECUTION_LOCK_OWNER"):
            self.adapter.inspect()
        (self.proc / "locks").write_text(f"1: FLOCK ADVISORY WRITE {os.getpid()} {device} 0 EOF\n")
        self.adapter.inspect()

    def test_completed_publication_ledger_only_reconciliation_then_retest(self):
        original = core._event
        def fail_completion(db, pins, event, payload):
            if event == "COMPLETED":
                raise RuntimeError("synthetic ledger publication gap")
            return original(db, pins, event, payload)
        with patch.object(core, "_event", fail_completion):
            with self.assertRaises(RuntimeError):
                self.adapter.recover_control()
        stopped = (self.runtime / "checkpoint_recovery_v1/STOPPED.json").read_bytes()
        before_calls = list(self.calls)
        report = self.adapter.reconcile_control(
            expected_intent_sha256=core.sha(self.runtime / "checkpoint_recovery_v1/INTENT.json"),
            expected_result_sha256=core.sha(self.runtime / "results/SR_CONTROL.json"),
            expected_second_checkpoint_sha256=core.sha(self.runtime / "results/SR_CONTROL.common_contiguous_2.checkpoint.json"))
        self.assertTrue(report["reconciliation_performed"])
        self.assertEqual([c for c in self.calls[len(before_calls):] if c == "price_loader" or c.startswith("replay:")], [])
        self.assertEqual((self.runtime / "checkpoint_recovery_v1/STOPPED.json").read_bytes(), stopped)
        self.adapter.run_retest_first()
        self.assertEqual(sum(e["event"] == "STARTED" for e in self.snapshot()["events"]), 2)


if __name__ == "__main__":
    unittest.main()
