"""Current TrendRider receipt-binding tests; no signals or price-path replay.

Mutation tests use copies of archived JSON in memory or temporary archives.
The one native observer demonstration extracts only its five pure functions.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping
import unittest
import zipfile


BASE = Path(__file__).resolve().parent
OBSERVER_SHA256 = "299ab590afe63972e73094051f99135a94351838c2c76213e45290d8e68428a1"
GUARD_PATH = BASE / "receipt_guard.py"


def load_guard():
    spec = importlib.util.spec_from_file_location("work_d_current_receipt_guard", GUARD_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def validate(guard, bundle, pin):
    return guard.validate_bundle(bundle["receipt"], bundle["hardening"],
                                 bundle["parent"], bundle["native_parent"], pin)


def isolated_observer_build(source: Path):
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != OBSERVER_SHA256:
        raise ValueError("OBSERVER_SOURCE_SHA256_MISMATCH")
    tree = ast.parse(raw.decode(), filename=str(source))
    names = {"stable", "authority_guard", "validate_inputs", "extract_hardening", "build"}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in functions} != names:
        raise ValueError("OBSERVER_PURE_FUNCTION_SET_MISMATCH")
    if any(isinstance(node, (ast.Import, ast.ImportFrom)) for function in functions for node in ast.walk(function)):
        raise ValueError("UNEXPECTED_IMPORT_IN_OBSERVER_FUNCTION")
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in {"SCHEMA", "CANDIDATE", "PARENT", "ROADMAP_POSITION"}:
                constants[name] = ast.literal_eval(node.value)
    namespace = {
        "__builtins__": {"dict": dict, "list": list, "str": str, "int": int, "bool": bool,
                         "isinstance": isinstance, "len": len, "sorted": sorted, "RuntimeError": RuntimeError},
        "Any": Any, "Mapping": Mapping, "json": json, "hashlib": hashlib, **constants,
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), "pinned-observer-pure-functions", "exec"), namespace)
    return namespace["build"], {
        "source_sha256": OBSERVER_SHA256,
        "compiled_functions": sorted(names),
        "native_module_imported": False,
        "native_main_read_or_write_executed": False,
        "build_line_start": next(node.lineno for node in functions if node.name == "build"),
        "build_line_end": next(node.end_lineno for node in functions if node.name == "build"),
    }


def observer_mixing_counterexample(guard=None):
    """One forged-PASS hardening example; published archived states are untouched."""
    guard = guard or load_guard()
    pins = json.loads((BASE / "PINNED_INPUTS.json").read_text())
    current = guard.load_pinned_bundle(BASE, "current255")
    later = guard.load_pinned_bundle(BASE, "later256")
    forged = copy.deepcopy(later["hardening"])
    forged["h4_receipt"]["state"] = "PASS_H4_PLACEBO_NEGATIVE_CONTROLS"
    forged["h5_receipt"]["state"] = "PASS_CONCENTRATION_FRAGILITY"
    forged["candidate_integrity"]["state"] = "PASS"
    # Self hashes do not authenticate lineage. Make those hashes internally current
    # so the new guard must still honor its archived pins and cross-receipt bindings.
    for key in ("h4_receipt", "h5_receipt"):
        forged[key]["receipt_sha256"] = guard.canonical_sha(forged[key])
    forged["receipt_sha256"] = guard.canonical_sha(forged)
    build, provenance = isolated_observer_build(BASE / "source" / "a1_trend_rider_prospective_observer_v1.py")
    legacy = {
        "candidate_id": "trend_rider_delayed_fill_long_only_v1", "parent_strategy_id": "trend_rider",
        "pre_shadow_ready": False, "state": "SYNTHETIC_LEGACY_METADATA_ONLY",
        "selection_authority": False, "promotion_authority": False, "execution_authority": "NONE",
        "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False, "protected_mutations": 0,
    }
    original_result = build(legacy, current["receipt"], forged)
    rejected = None
    try:
        mixed = dict(current, hardening=forged)
        validate(guard, mixed, pins["cohorts"]["current255"])
    except guard.GuardError as exc:
        rejected = str(exc)
    if original_result["state"] != "A1_PROSPECTIVE_EVIDENCE_READY" or rejected is None:
        raise AssertionError("OBSERVER_MIXING_COUNTEREXAMPLE_NOT_CONFIRMED")
    return {
        "classification": "SYNTHETIC_FORGED_PASS_BINDING_COUNTEREXAMPLE_NO_ECONOMIC_RUN",
        "provenance": provenance,
        "authentic_fresh_trade_count": current["receipt"]["completed_trades"],
        "mismatched_hardening_original_trade_count": later["hardening"]["candidate_trade_count"],
        "authentic_fresh_receipt_sha256": current["receipt"]["receipt_sha256"],
        "mismatched_hardening_candidate_receipt_sha256": forged["candidate_receipt_sha256"],
        "synthetic_mutations": ["h4 state PASS", "h5 state PASS", "candidate integrity PASS", "self hashes recalculated"],
        "original_observer_state": original_result["state"],
        "original_observer_full_h4_h5_evidence_ready": original_result["full_h4_h5_evidence_ready"],
        "original_order_authority": original_result["order_authority"],
        "original_canonical_shadow_entry_granted": original_result["canonical_shadow_entry_granted"],
        "guard_rejected": True, "guard_error": rejected,
        "actual_archived_h4_unchanged": current["hardening"]["h4_receipt"]["state"],
        "actual_archived_h5_unchanged": current["hardening"]["h5_receipt"]["state"],
        "new_economic_full_runs": 0, "orders": 0,
    }


class CurrentReceiptGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = load_guard()
        cls.pins = json.loads((BASE / "PINNED_INPUTS.json").read_text())
        cls.bundles = {name: cls.guard.load_pinned_bundle(BASE, name)
                       for name in ("current255", "later256")}

    def fresh(self, name="current255"):
        return copy.deepcopy(self.bundles[name]), copy.deepcopy(self.pins["cohorts"][name])

    def reseal(self, bundle, pin, role):
        """Synthetic expected canonical pin, used only to reach deeper invariant checks."""
        bundle[role]["receipt_sha256"] = self.guard.canonical_sha(bundle[role])
        pin["members"][role]["receipt_sha256"] = bundle[role]["receipt_sha256"]

    def reseal_receipt_and_hardening(self, bundle, pin):
        self.reseal(bundle, pin, "receipt")
        bundle["hardening"]["candidate_receipt_sha256"] = bundle["receipt"]["receipt_sha256"]
        self.reseal(bundle, pin, "hardening")

    def mutate_matching_child_and_delayed_parent(self, bundle, pin, mutation, mutate_native=False):
        child = bundle["receipt"]["trades"][0]
        match = next(row for row in bundle["parent"]["trades"] if row["intent_sha"] == child["intent_sha"])
        if mutate_native:
            native = next(row for row in bundle["native_parent"]["trades"]
                          if row["intent_sha"] == child["parent_intent_sha"])
            mutation(native)
            self.reseal(bundle, pin, "native_parent")
        mutation(child)
        mutation(match)
        self.reseal(bundle, pin, "parent")
        bundle["receipt"]["parent_receipt_sha256"] = bundle["parent"]["receipt_sha256"]
        self.reseal_receipt_and_hardening(bundle, pin)

    def assert_rejected(self, bundle, pin):
        with self.assertRaises(self.guard.GuardError):
            validate(self.guard, bundle, pin)

    def test_true_archived_cohorts_validate_separately_without_child_or_authority(self):
        for name, count in (("current255", 255), ("later256", 256)):
            with self.subTest(cohort=name):
                bundle, pin = self.fresh(name)
                self.assertEqual(bundle["receipt"]["completed_trades"], count)
                audit = validate(self.guard, bundle, pin)
                self.assertEqual(audit["integrity"], "PASS_PINNED_RECEIPT_BINDING")
                self.assertEqual(audit["source_feature_gate"], "SOURCE_FEATURE_BLOCKED")
                self.assertEqual(audit["terminal"], "CURRENT_TRENDRIDER_NO_CAUSAL_CHILD")
                self.assertIsNone(audit["candidate_child"])
                self.assertEqual(audit["execution_authority"], "NONE")
                self.assertEqual(audit["order_authority"], "BLOCKED")

    def test_later256_hardening_cannot_attach_to_current255_even_same_strategy(self):
        bundle, pin = self.fresh()
        bundle["hardening"] = copy.deepcopy(self.bundles["later256"]["hardening"])
        self.assertEqual(bundle["hardening"]["strategy_id"], bundle["receipt"]["strategy_id"])
        # Admit its genuine independent self hash at the synthetic pin layer;
        # the cross-receipt relation must still reject the 256 vs 255 mixture.
        pin["members"]["hardening"]["receipt_sha256"] = bundle["hardening"]["receipt_sha256"]
        self.assert_rejected(bundle, pin)

    def test_unrelated47_hardening_same_strategy_name_is_rejected(self):
        bundle, pin = self.fresh()
        bundle["hardening"] = json.loads((BASE / "inputs" / "trend_rider_hardening_latest.json").read_text())
        self.assertEqual(bundle["hardening"]["candidate_trade_count"], 47)
        self.assertEqual(bundle["hardening"]["strategy_id"], bundle["receipt"]["strategy_id"])
        pin["members"]["hardening"]["receipt_sha256"] = bundle["hardening"]["receipt_sha256"]
        self.assert_rejected(bundle, pin)

    def test_wr80_and_unified_zero_are_separate_lanes(self):
        wr80 = json.loads((BASE / "inputs" / "a1_trend_rider_wr80_us_chase_cooling_forward_latest.json").read_text())
        unified = json.loads((BASE / "inputs" / "TOP5_G5A_PHASE1_STATUS_V1.json").read_text())["lanes"]["TrendRider Unified"]
        self.assertEqual(wr80["candidate_id"], "trend_rider_wr80_us_chase_cooling_v1")
        self.assertEqual(unified["fresh_closed_T"], 0)
        for wrong in (wr80, unified):
            with self.subTest(lane=wrong.get("candidate_id", wrong.get("rule_id"))):
                bundle, pin = self.fresh()
                bundle["receipt"] = copy.deepcopy(wrong)
                self.assert_rejected(bundle, pin)

    def test_stale_self_hash_is_rejected(self):
        bundle, pin = self.fresh()
        bundle["receipt"]["metrics"]["net_pnl_bps"] += 1
        self.assert_rejected(bundle, pin)

    def test_self_rehashed_raw_tamper_fails_archive_and_member_pins(self):
        bundle, pin = self.fresh()
        bundle["receipt"]["metrics"]["net_pnl_bps"] += 1
        bundle["receipt"]["receipt_sha256"] = self.guard.canonical_sha(bundle["receipt"])
        self.assertEqual(self.guard.canonical_sha(bundle["receipt"]), bundle["receipt"]["receipt_sha256"])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "inputs").mkdir()
            archive = root / pin["path"]
            target_member = pin["members"]["receipt"]["name"]
            with zipfile.ZipFile(BASE / pin["path"]) as source, zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as out:
                for item in source.infolist():
                    content = (json.dumps(bundle["receipt"], sort_keys=True).encode()
                               if item.filename == target_member else source.read(item.filename))
                    out.writestr(item.filename, content)
            manifest = copy.deepcopy(self.pins)
            (root / "PINNED_INPUTS.json").write_text(json.dumps(manifest))
            with self.assertRaises(self.guard.GuardError):
                self.guard.load_pinned_bundle(root, "current255")
            # Synthetic archive-hash update alone cannot bless altered member bytes.
            manifest["cohorts"]["current255"]["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
            manifest["cohorts"]["current255"]["archive_bytes"] = archive.stat().st_size
            (root / "PINNED_INPUTS.json").write_text(json.dumps(manifest))
            with self.assertRaises(self.guard.GuardError):
                self.guard.load_pinned_bundle(root, "current255")

    def test_development_record_cannot_be_relabelled_fresh(self):
        bundle, pin = self.fresh()
        with zipfile.ZipFile(BASE / self.pins["cohorts"]["later256"]["path"]) as archive:
            development = json.loads(archive.read("long_only_development.json"))
        self.assertEqual(development["evaluation_mode"], "development")
        development["evaluation_mode"] = "prospective"
        development["prospective_boundary_utc"] = pin["boundary_utc"]
        bundle["receipt"] = development
        self.reseal_receipt_and_hardening(bundle, pin)
        self.assert_rejected(bundle, pin)

    def test_hardening_boundary_mismatch_survives_self_rehash_but_is_rejected(self):
        bundle, pin = self.fresh()
        bundle["hardening"]["boundary_utc"] = "2026-08-23T09:55:34Z"
        self.reseal(bundle, pin, "hardening")
        self.assert_rejected(bundle, pin)

    def test_different_true_parent_cannot_be_substituted(self):
        for role in ("parent", "native_parent"):
            with self.subTest(role=role):
                bundle, pin = self.fresh()
                bundle[role] = copy.deepcopy(self.bundles["later256"][role])
                pin["members"][role]["receipt_sha256"] = bundle[role]["receipt_sha256"]
                self.assert_rejected(bundle, pin)

    def test_hardening_cost_authority_mismatch_is_rejected(self):
        bundle, pin = self.fresh()
        bundle["hardening"]["cost_authority_sha256"] = "0" * 64
        self.reseal(bundle, pin, "hardening")
        self.assert_rejected(bundle, pin)

    def test_trade_cost_snapshot_mismatch_is_rejected(self):
        bundle, pin = self.fresh()
        self.mutate_matching_child_and_delayed_parent(bundle, pin, lambda row: row.update(cost_snapshot_sha="0" * 64))
        self.assert_rejected(bundle, pin)

    def test_malformed_trade_economics_and_time_are_rejected(self):
        mutations = (
            ("net_arithmetic", lambda row: row.update(net_bps=row["net_bps"] + 1), False, "NET_ARITHMETIC_MISMATCH"),
            ("negative_cost", lambda row: row.update(realized_cost_bps=-1), True, "NEGATIVE_STORED_COST"),
            ("gross_arithmetic", lambda row: row.update(gross_bps=row["gross_bps"] + 1), False, "GROSS_ARITHMETIC_MISMATCH"),
            ("bad_time", lambda row: row.update(exit_ts=row["entry_ts"] - 1), False, None),
            ("null_net", lambda row: row.update(net_bps=None), False, None),
            ("string_price", lambda row: row.update(entry="not-a-number"), False, None),
            ("string_nan_gross", lambda row: row.update(gross_bps="NaN"), False, None),
        )
        for label, mutation, mutate_native, expected in mutations:
            with self.subTest(case=label):
                bundle, pin = self.fresh()
                self.mutate_matching_child_and_delayed_parent(bundle, pin, mutation, mutate_native=mutate_native)
                if expected:
                    with self.assertRaisesRegex(self.guard.GuardError, expected):
                        validate(self.guard, bundle, pin)
                else:
                    self.assert_rejected(bundle, pin)

    def test_feature_digests_do_not_substitute_for_entry_time_feature_bodies(self):
        bundle, pin = self.fresh()
        self.assertTrue(all(row.get("feature_sha") for row in bundle["receipt"]["trades"]))
        self.assertTrue(all("feature_body" not in row for row in bundle["receipt"]["trades"]))
        audit = validate(self.guard, bundle, pin)
        self.assertEqual(audit["source_feature_gate"], "SOURCE_FEATURE_BLOCKED")
        self.assertIsNone(audit["candidate_child"])

    def test_economic_authority_cannot_be_opened_by_valid_self_hash(self):
        fields = {"selection_authority": True, "promotion_authority": True,
                  "execution_authority": "LIVE", "order_authority": "ALLOWED",
                  "live_trade_authority": "ALLOWED", "exchange_order_submitted": True,
                  "protected_mutations": 1}
        for field, value in fields.items():
            with self.subTest(field=field):
                bundle, pin = self.fresh()
                bundle["receipt"][field] = value
                self.reseal_receipt_and_hardening(bundle, pin)
                self.assert_rejected(bundle, pin)

    def test_original_observer_accepts_one_forged_pass_mixture_new_guard_rejects(self):
        proof = observer_mixing_counterexample(self.guard)
        self.assertEqual(proof["authentic_fresh_trade_count"], 255)
        self.assertEqual(proof["mismatched_hardening_original_trade_count"], 256)
        self.assertNotEqual(proof["authentic_fresh_receipt_sha256"], proof["mismatched_hardening_candidate_receipt_sha256"])
        self.assertTrue(proof["original_observer_full_h4_h5_evidence_ready"])
        self.assertEqual(proof["original_observer_state"], "A1_PROSPECTIVE_EVIDENCE_READY")
        self.assertTrue(proof["guard_rejected"])
        self.assertFalse(proof["original_canonical_shadow_entry_granted"])
        self.assertEqual(proof["original_order_authority"], "BLOCKED")
        self.assertEqual(proof["actual_archived_h4_unchanged"], "NO_PROVEN_EDGE")
        self.assertEqual(proof["actual_archived_h5_unchanged"], "HOLD_CONCENTRATION_FRAGILITY")


if __name__ == "__main__":
    unittest.main()
