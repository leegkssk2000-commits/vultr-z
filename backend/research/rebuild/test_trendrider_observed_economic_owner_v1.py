"""Synthetic boundary, once-only dispatch, and final attribution regressions."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import trendrider_observed_economic_owner_v1 as owner
from backend.research.rebuild import trendrider_common_source_v1 as source_v1


REPO = Path("/workspace/scratch/aa33da84ee6a/vultr-z-observed")


def _raw(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(owner.canonical(value))
    return sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path, *, semantic_path: Path | None = None):
    scope = root / "research/development_evidence" / owner.SCOPE
    old = json.loads((REPO / owner.OLD_CONTRACT).read_bytes())
    paths = set(old["source_authority_hashes"]) | set(owner.REQUIRED_CODE)
    code = {}
    for relative in paths:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((Path(owner.__file__) if relative == owner.OWNER_PATH else REPO / relative).read_bytes())
        code[relative] = sha256(target.read_bytes()).hexdigest()
    prior_sha = _raw(root / owner.OLD_CONTRACT, old)
    contract = deepcopy(old)
    contract["scope_key"] = owner.SCOPE
    contract_sha = _raw(scope / "CONTRACT.json", contract)
    rows = [{"ts_ms": stamp, "open": 100.0, "high": 101.0, "low": 99.0,
             "close": 100.0, "volume": 5.0}
            for stamp in range(1784448000000, 1788048000000, 3_600_000)]
    normalized = {}
    records = {}
    for symbol in ("BTC-USDT", "ETH-USDT"):
        path = scope / "source_data/sources" / (symbol + ".json")
        value_sha = _raw(path, rows)
        normalized[symbol] = {"path": str(path.relative_to(root)), "sha256": value_sha}
        records[symbol] = {"path": "sources/" + symbol + ".json", "sha256": value_sha}
    calibration_path = scope / "calibration/OBSERVED_WS_REST_TIMESTAMP_RECEIPT.json"
    if semantic_path is None:
        calibration_sha = _raw(calibration_path, {
            "schema": "trendrider.observed.ws.rest.timestamp.receipt.v1", "state": "PASS",
            "supported_canonical_lane": "OBJECT_TIME_OPEN",
            "canonical_open_transform": "IDENTITY_NATIVE_OBJECT_TIME_MS",
            "open_ts_rule": "native_T", "close_ts_rule": "open_ts + 1h",
            "provider_native_close_claim": False, "outcome_independent": True,
            "hour_ms": 3_600_000, "timestamp_adjustment_ms": 0})
    else:
        assert semantic_path == calibration_path
        calibration_sha = sha256(calibration_path.read_bytes()).hexdigest()
    calibration = json.loads(calibration_path.read_bytes())
    source_authorization_path = scope / "SOURCE_AUTHORIZATION.json"
    source_authorization_sha = _raw(source_authorization_path, source_v1._sealed({
        "schema": "trendrider.common.source.authorization.v6", "scope_key": owner.SCOPE, "state": "AUTHORIZED_SOURCE_ONCE",
        "contract_sha256": contract_sha, "timestamp_semantic_receipt_sha256": calibration_sha,
        "dataset_fetch_attempts": 1, "max_pages_per_symbol": 3, "max_http_requests": 6,
        "retry_authorized": False}))
    data = {"schema": "trendrider.common.source.freeze.v6",
            "state": "FROZEN_COMMON_HISTORICAL_DEV", "normalized": records,
            "timestamp_semantic_receipt_sha256": calibration_sha,
            "source_authorization_sha256": source_authorization_sha,
            "supported_canonical_lane": calibration["supported_canonical_lane"],
            "canonical_open_transform": calibration["canonical_open_transform"],
            "canonical_close_rule": ("IDENTITY_NATIVE_ARRAY_CLOSE_MS"
                if calibration["supported_canonical_lane"] == "ARRAY_OPEN_CLOSE"
                else "OPEN_PLUS_HOUR_MINUS_1_MS"),
            "canonical_close_metadata_role": "LEGACY_SOURCE_SERIALIZATION_ONLY",
            "economic_close_delta_ms": 3_600_000,
            "canonical_timestamp_offset_ms": 0,
            "provider_native_close_claim": False,
            "open_ts_rule": calibration["open_ts_rule"],
            "close_ts_rule": calibration["close_ts_rule"],
            "dataset_sha256": sha256(source_v1.canonical_bytes(records)).hexdigest()}
    data_sha = _raw(scope / "source_data/DATA_FREEZE_V6.json", data)
    manifest = {"scope_key": owner.SCOPE, "code_files": code,
                "calibration_receipt": {"path": str(calibration_path.relative_to(root)), "sha256": calibration_sha},
                "source_authorization": {"path": str(source_authorization_path.relative_to(root)), "sha256": source_authorization_sha},
                "contract": {"path": str((scope / "CONTRACT.json").relative_to(root)), "sha256": contract_sha},
                "prior_contract": {"path": owner.OLD_CONTRACT, "sha256": prior_sha},
                "data_freeze": {"path": str((scope / "source_data/DATA_FREEZE_V6.json").relative_to(root)), "sha256": data_sha},
                "normalized_files": normalized}
    manifest_path = scope / "OWNER_INPUT_FREEZE.json"
    manifest_sha = _raw(manifest_path, manifest)
    return scope, manifest_path, manifest_sha, manifest


def _synthetic_semantic(root: Path, schema: str, close_delta: int) -> Path:
    from backend.research.rebuild.test_trendrider_observed_timestamp_v1 import write_synthetic_witness
    source = write_synthetic_witness(root / "synthetic_input", schema, close_delta=close_delta)
    target = root / "research/development_evidence" / owner.SCOPE / "calibration"
    shutil.copytree(source.parent, target)
    return target / source.name


class SemanticIntegrationTests(unittest.TestCase):
    def test_actual_raw_linked_object_and_array_receipts_enter_owner_without_mock(self):
        for schema, close_delta in (("object", 3_599_999), ("array", 3_599_999), ("array", 3_600_000)):
            with self.subTest(schema=schema, close_delta=close_delta), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                semantic_path = _synthetic_semantic(root, schema, close_delta)
                scope, path, digest, _ = _fixture(root, semantic_path=semantic_path)
                value = owner.Owner(root, scope, path, digest)
                self.assertEqual(len(value.bars["BTC-USDT"]), 1000)
                self.assertEqual(value.calibration["open_ts_rule"], "native_T")
                self.assertEqual(value.calibration["close_ts_rule"], "open_ts + 1h")
                self.assertEqual(value.budget()["control_runs"], 0)
                self.assertEqual(value.budget()["child_FULL_runs"], 0)

    def test_tampered_archived_frame_rejected_before_normalized_decode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            semantic_path = _synthetic_semantic(root, "object", 3_599_999)
            scope, path, digest, manifest = _fixture(root, semantic_path=semantic_path)
            receipt = json.loads(semantic_path.read_bytes())
            (semantic_path.parent / receipt["stored_pr1283"]["frame_raw"]["path"]).write_bytes(b"tampered wire")
            (root / manifest["data_freeze"]["path"]).write_bytes(b"not json")
            with self.assertRaisesRegex(source_v1.SourceIntegrityError, "OBSERVED_ARCHIVED_PR1283_HASH"):
                owner.Owner(root, scope, path, digest)
            self.assertFalse((scope / "reservations").exists())


def _minimal(root: Path):
    instance = owner.Owner.__new__(owner.Owner)
    instance.root = root
    instance.freeze_sha = "f" * 64
    return instance


def _trade(stamp, net, *, p_core=True, completed=True):
    return {"symbol": "BTC-USDT", "signal_ts": stamp, "side": "long", "entry": 100,
            "status": "COMPLETED" if completed else "OPEN_CENSORED",
            "net_bps": net if completed else None, "terminal_net_bps": net,
            "cost_bps": 14, "cost2_terminal_net_bps": net - 14,
            "quantity_normalized": 1, "p_core": p_core, "b_only": not p_core}


def _result(rows):
    return {"campaigns": rows, "metrics": {"terminal_net_bps": sum(r["terminal_net_bps"] for r in rows)}}


class FreezeTests(unittest.TestCase):
    def setUp(self):
        # Receipt raw-chain validation has independent semantic-module tests.
        # These tests isolate the owner's consumption and hash bindings.
        self.semantic_patch = patch.object(owner, "_semantic_receipt",
            side_effect=lambda path, expected: json.loads(owner.read_hashed(path, expected)))
        self.semantic_patch.start()
        self.addCleanup(self.semantic_patch.stop)

    def test_exact_owner_source_and_data_binding_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope, manifest_path, manifest_sha, _ = _fixture(root)
            value = owner.Owner(root, scope, manifest_path, manifest_sha)
            self.assertEqual(len(value.bars["BTC-USDT"]), 1000)
            self.assertFalse((scope / "reservations").exists())

    def test_tampered_market_bytes_fail_before_decode_or_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope, path, manifest_sha, manifest = _fixture(root)
            (root / manifest["normalized_files"]["BTC-USDT"]["path"]).write_bytes(b"not json")
            with self.assertRaisesRegex(ValueError, "OWNER_RAW_HASH_MISMATCH"):
                owner.Owner(root, scope, path, manifest_sha)
            self.assertFalse((scope / "reservations").exists())

    def test_rehashed_cost_change_still_rejected_by_prior_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope, path, _, manifest = _fixture(root)
            contract_path = root / manifest["contract"]["path"]
            contract = json.loads(contract_path.read_bytes())
            contract["common_cost"]["fee_bps"] = 9
            contract["common_cost_sha256"] = owner.digest(contract["common_cost"])
            manifest["contract"]["sha256"] = _raw(contract_path, contract)
            manifest_sha = _raw(path, manifest)
            with self.assertRaisesRegex(ValueError, "FROZEN_ECONOMIC_SEMANTICS_CHANGED"):
                owner.Owner(root, scope, path, manifest_sha)

    def test_formal_credit_and_runtime_are_frozen_contract_sections(self):
        self.assertEqual(len(owner.ECONOMIC_CONTRACT_KEYS), 16)
        for section, changed in (("formal_credit", False),
                                 ("runtime", {"python_major_minor": "3.13"})):
            with self.subTest(section=section), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                scope, path, _, manifest = _fixture(root)
                contract_path = root / manifest["contract"]["path"]
                contract = json.loads(contract_path.read_bytes())
                contract[section] = changed
                manifest["contract"]["sha256"] = _raw(contract_path, contract)
                manifest_sha = _raw(path, manifest)
                with self.assertRaisesRegex(ValueError, "FROZEN_ECONOMIC_SEMANTICS_CHANGED"):
                    owner.Owner(root, scope, path, manifest_sha)

    def test_modified_economic_owner_code_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope, path, manifest_sha, _ = _fixture(root)
            with (root / owner.OWNER_PATH).open("ab") as handle:
                handle.write(b"\n# changed after freeze\n")
            with self.assertRaisesRegex(ValueError, "OWNER_RAW_HASH_MISMATCH"):
                owner.Owner(root, scope, path, manifest_sha)

    def test_calibration_nonidentity_timestamp_rejected_even_if_rehashed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope, path, _, manifest = _fixture(root)
            calibration_path = root / manifest["calibration_receipt"]["path"]
            calibration = json.loads(calibration_path.read_bytes())
            calibration["timestamp_adjustment_ms"] = 3_600_000
            manifest["calibration_receipt"]["sha256"] = _raw(calibration_path, calibration)
            manifest_sha = _raw(path, manifest)
            # Calibration authority must fail before any source/market decode.
            (root / manifest["data_freeze"]["path"]).write_bytes(b"not json")
            with self.assertRaisesRegex(ValueError, "OWNER_CALIBRATION_NOT_REST_WS_PASS"):
                owner.Owner(root, scope, path, manifest_sha)
            self.assertFalse((scope / "reservations").exists())

    def test_stale_calibration_binding_in_data_freeze_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope, path, _, manifest = _fixture(root)
            data_path = root / manifest["data_freeze"]["path"]
            data = json.loads(data_path.read_bytes())
            data["timestamp_semantic_receipt_sha256"] = "0" * 64
            manifest["data_freeze"]["sha256"] = _raw(data_path, data)
            manifest_sha = _raw(path, manifest)
            with self.assertRaisesRegex(ValueError, "OWNER_SOURCE_CALIBRATION_BINDING"):
                owner.Owner(root, scope, path, manifest_sha)

    def test_failed_semantic_receipt_blocks_historical_decode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope, path, _, manifest = _fixture(root)
            calibration_path = root / manifest["calibration_receipt"]["path"]
            value = json.loads(calibration_path.read_bytes())
            value["state"] = "BLOCKED_REST_WS_TIMESTAMP_WITNESS"
            manifest["calibration_receipt"]["sha256"] = _raw(calibration_path, value)
            manifest_sha = _raw(path, manifest)
            (root / manifest["data_freeze"]["path"]).write_bytes(b"not json")
            with self.assertRaisesRegex(ValueError, "OWNER_CALIBRATION_NOT_REST_WS_PASS"):
                owner.Owner(root, scope, path, manifest_sha)

    def test_stale_source_authorization_binding_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope, path, _, manifest = _fixture(root)
            data_path = root / manifest["data_freeze"]["path"]
            data = json.loads(data_path.read_bytes())
            data["source_authorization_sha256"] = "0" * 64
            manifest["data_freeze"]["sha256"] = _raw(data_path, data)
            manifest_sha = _raw(path, manifest)
            with self.assertRaisesRegex(ValueError, "OWNER_SOURCE_CALIBRATION_BINDING"):
                owner.Owner(root, scope, path, manifest_sha)

    def test_rehashed_source_authorization_cannot_grant_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope, path, _, manifest = _fixture(root)
            auth_path = root / manifest["source_authorization"]["path"]
            auth = json.loads(auth_path.read_bytes())
            auth.pop("receipt_sha256")
            auth["retry_authorized"] = True
            manifest["source_authorization"]["sha256"] = _raw(auth_path, source_v1._sealed(auth))
            manifest_sha = _raw(path, manifest)
            (root / manifest["data_freeze"]["path"]).write_bytes(b"not json")
            with self.assertRaisesRegex(ValueError, "OWNER_SOURCE_AUTHORIZATION_BINDING"):
                owner.Owner(root, scope, path, manifest_sha)

    def test_v2_data_cannot_enter_new_scope_even_if_rehashed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope, path, _, manifest = _fixture(root)
            old_path = root / manifest["data_freeze"]["path"]
            new_path = old_path.with_name("DATA_FREEZE_V2.json")
            old_path.rename(new_path)
            manifest["data_freeze"]["path"] = str(new_path.relative_to(root))
            manifest_sha = _raw(path, manifest)
            with self.assertRaisesRegex(ValueError, "OWNER_DATA_FREEZE_V6_REQUIRED"):
                owner.Owner(root, scope, path, manifest_sha)

    def test_combined_dataset_digest_is_recomputed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope, path, _, manifest = _fixture(root)
            data_path = root / manifest["data_freeze"]["path"]
            data = json.loads(data_path.read_bytes())
            expected = sha256(source_v1.canonical_bytes(data["normalized"])).hexdigest()
            self.assertEqual(data["dataset_sha256"], expected)
            # Owner file formatting is not the source collector's wire format.
            data["dataset_sha256"] = sha256(owner.canonical(data["normalized"])).hexdigest()
            self.assertNotEqual(data["dataset_sha256"], expected)
            manifest["data_freeze"]["sha256"] = _raw(data_path, data)
            manifest_sha = _raw(path, manifest)
            with self.assertRaisesRegex(ValueError, "OWNER_DATASET_HASH_DRIFT"):
                owner.Owner(root, scope, path, manifest_sha)


    def test_provider_native_close_claim_rejected_before_source_decode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope, path, _, manifest = _fixture(root)
            calibration_path = root / manifest["calibration_receipt"]["path"]
            calibration = json.loads(calibration_path.read_bytes())
            calibration["provider_native_close_claim"] = True
            manifest["calibration_receipt"]["sha256"] = _raw(calibration_path, calibration)
            manifest_sha = _raw(path, manifest)
            (root / manifest["data_freeze"]["path"]).write_bytes(b"not json")
            with self.assertRaisesRegex(ValueError, "OWNER_CALIBRATION_NOT_REST_WS_PASS"):
                owner.Owner(root, scope, path, manifest_sha)

    def test_native_open_rule_is_required_before_source_decode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope, path, _, manifest = _fixture(root)
            calibration_path = root / manifest["calibration_receipt"]["path"]
            calibration = json.loads(calibration_path.read_bytes())
            calibration["open_ts_rule"] = "native_T - 1h"
            manifest["calibration_receipt"]["sha256"] = _raw(calibration_path, calibration)
            manifest_sha = _raw(path, manifest)
            (root / manifest["data_freeze"]["path"]).write_bytes(b"not json")
            with self.assertRaisesRegex(ValueError, "OWNER_CALIBRATION_NOT_REST_WS_PASS"):
                owner.Owner(root, scope, path, manifest_sha)

    def test_economic_close_boundary_cannot_use_legacy_close_delta(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope, path, _, manifest = _fixture(root)
            data_path = root / manifest["data_freeze"]["path"]
            data = json.loads(data_path.read_bytes())
            data["economic_close_delta_ms"] = 3_599_999
            manifest["data_freeze"]["sha256"] = _raw(data_path, data)
            manifest_sha = _raw(path, manifest)
            with self.assertRaisesRegex(ValueError, "OWNER_SOURCE_INTERVAL_BOUNDARY_DRIFT"):
                owner.Owner(root, scope, path, manifest_sha)


class DispatchTests(unittest.TestCase):
    def test_uncompleted_reservation_counts_once_and_prevents_success(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = _minimal(Path(directory))
            owner.reserve(instance.root, "CONTROL", "DEV_A__B_COMMON", instance.freeze_sha)
            budget = instance.budget()
            self.assertEqual(budget["control_runs"], 1)
            self.assertEqual(budget["reserved_incomplete_runs"], 1)
            self.assertEqual(budget["failed_runs"], 0)
            with self.assertRaisesRegex(ValueError, "OWNER_INCOMPLETE_EXECUTION"):
                instance.final()
            with self.assertRaises(FileExistsError):
                instance.run("CONTROL", "DEV_A__B_COMMON", "controls/b.json",
                             lambda: self.fail("interrupted reservation retried"))

    def test_reservation_exists_before_dispatch_and_second_call_never_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = _minimal(Path(directory))
            calls = []
            def actual():
                self.assertTrue((instance.root / "reservations/CONTROL__DEV_A__B_COMMON.json").exists())
                calls.append(1)
                return {"synthetic": True}
            instance.run("CONTROL", "DEV_A__B_COMMON", "controls/a.json", actual)
            with self.assertRaises(FileExistsError):
                instance.run("CONTROL", "DEV_A__B_COMMON", "controls/a.json", actual)
            self.assertEqual(len(calls), 1)

    def test_failed_run_remains_consumed_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = _minimal(Path(directory))
            def failure():
                raise RuntimeError("synthetic failure")
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                instance.run("CONTROL", "DEV_A__P_COMMON", "controls/p.json", failure)
            with self.assertRaises(FileExistsError):
                instance.run("CONTROL", "DEV_A__P_COMMON", "controls/p.json", lambda: {})
            self.assertEqual(instance.budget()["control_runs"], 1)
            self.assertEqual(instance.budget()["failed_runs"], 1)

    def test_concurrent_attempt_cannot_enter_economics(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = _minimal(Path(directory))
            def outer():
                with self.assertRaises(FileExistsError):
                    instance.run("CONTROL", "DEV_A__P_COMMON", "controls/p.json",
                                 lambda: self.fail("parallel economics entered"))
                return {}
            instance.run("CONTROL", "DEV_A__B_COMMON", "controls/b.json", outer)
            self.assertEqual(instance.budget()["control_runs"], 1)

    def test_confirmation_budget_max_two_even_with_distinct_gene_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            owner.reserve(root, "CONFIRM_B", "G2", "f" * 64)
            owner.reserve(root, "CONFIRM_B", "G3", "f" * 64)
            with self.assertRaisesRegex(ValueError, "OWNER_BUDGET_EXHAUSTED"):
                owner.reserve(root, "CONFIRM_B", "G4", "f" * 64)

    def test_no_remote_a_freeze_blocks_before_b_load(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = _minimal(Path(directory))
            instance.load = lambda _: self.fail("DEV_B data read before remote A seal")
            with self.assertRaisesRegex(ValueError, "BARRIER_REQUIRED"):
                instance.stage1b(None)

    def test_remote_receipt_cannot_bind_changed_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = _minimal(Path(directory))
            expected = _raw(instance.root / "SELECTION_A.json", {"ordered_survivors": ["G2"]})
            receipt = {"stage": "A_SELECTION", "readback_verified": True,
                       "verified_commit_sha": "a" * 40, "input_freeze_sha256": instance.freeze_sha,
                       "files": {"SELECTION_A.json": expected}}
            _raw(instance.root / "remote.json", receipt)
            _raw(instance.root / "SELECTION_A.json", {"ordered_survivors": ["G3"]})
            with self.assertRaisesRegex(ValueError, "OWNER_RAW_HASH_MISMATCH"):
                instance.barrier(instance.root / "remote.json", "A_SELECTION", "SELECTION_A.json")

    def test_dev_a_selection_does_not_read_dev_b_saved_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = _minimal(Path(directory))
            instance.save("STAGE0_RECEIPT.json", {"control_runs": 4})
            instance.save("SIGNALS.json", [])
            instance.save("controls/DEV_A__B_COMMON.json", {"partition": "DEV_A", "start_index": 64,
                          "end_exclusive": 532, "campaigns": [], "events": []})
            real_load = instance.load
            def guarded(relative):
                self.assertNotIn("DEV_B", relative)
                return real_load(relative)
            instance.load = guarded
            result = instance.stage1a()
            self.assertEqual(result["ordered_survivors"], [])
            self.assertEqual(instance.budget()["DEV_A_screens"], 6)
            self.assertEqual(instance.budget()["DEV_B_confirmations"], 0)

    def test_b_confirmation_preserves_a_order_and_builds_only_orthogonal_and(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = _minimal(Path(directory))
            genes = owner._genes()
            first, second = "G3_ST_GAP_EXPANDING", "G5_ATR_EXPANDING"
            selection = {"ordered_survivors": [first, second], "receipt_sha": "a" * 64}
            instance.save("SELECTION_A.json", selection)
            instance.save("SIGNALS.json", [])
            instance.save("controls/DEV_B__B_COMMON.json", {"partition": "DEV_B"})
            receipt = {"stage": "A_SELECTION", "readback_verified": True,
                       "verified_commit_sha": "a" * 40, "input_freeze_sha256": instance.freeze_sha,
                       "files": {"SELECTION_A.json": sha256((instance.root / "SELECTION_A.json").read_bytes()).hexdigest()}}
            _raw(instance.root / "remote.json", receipt)
            seen = []
            def synthetic_screen(saved, signals, partition, gene):
                seen.append((partition, gene))
                return {"partition": partition, "gene_id": gene, "integrity": "PASS",
                        "metrics": {"expectancy_bps": 5 if gene == first else 50,
                            "PF_infinite": False, "PF": 2, "payoff_infinite": False,
                            "payoff": 2, "closed_cost2_net_bps": 10},
                        "ordinary_winner_retention": .7, "top10_winner_retention": .8,
                        "receipt_sha": owner.digest(gene)}
            with patch.object(genes, "screen", side_effect=synthetic_screen):
                identities = instance.stage1b(instance.root / "remote.json")
            self.assertEqual(seen, [("DEV_B", first), ("DEV_B", second)])
            self.assertEqual(identities["candidates"], {
                "U1": {"gene_ids": [first], "operator": "AND"},
                "U2": {"gene_ids": [first, second], "operator": "AND"}})
            self.assertEqual(instance.budget()["DEV_B_confirmations"], 2)
            self.assertEqual(instance.budget()["child_FULL_runs"], 0)
            # Candidate existence does not remove the second remote barrier.
            with self.assertRaisesRegex(ValueError, "BARRIER_REQUIRED"):
                instance.stage2(None)


class AttributionTests(unittest.TestCase):
    def test_gain_on_one_winner_cannot_mask_removed_winner(self):
        baseline = _result([_trade(1, 100), _trade(2, 100)])
        child = _result([_trade(1, 1000)])
        result = owner.winner_retention(baseline, child)
        self.assertEqual(result["ordinary"]["retention"], .5)
        self.assertEqual(result["ordinary"]["uncapped_retention"], 5)
        self.assertEqual(result["top10"]["retention"], 1)

    def test_open_mark_does_not_receive_closed_winner_retention(self):
        baseline = _result([_trade(1, 100)])
        child = _result([_trade(1, 120, completed=False)])
        self.assertEqual(owner.winner_retention(baseline, child)["ordinary"]["retention"], 0)

    def test_donor_displacement_bridge_and_added_b_only_are_separate(self):
        baseline = _result([_trade(1, 100), _trade(2, -50)])
        child = _result([_trade(1, 100), _trade(3, 30, p_core=False), _trade(4, -20)])
        result = owner.path_attribution(baseline, child)
        self.assertEqual(result["same_key_path_integrity"], "PASS")
        self.assertEqual(result["added_B_only_terminal_bps"], 30)
        self.assertEqual(result["recovered_P_core_terminal_bps"], -20)
        self.assertEqual(result["displaced_reference_terminal_effect_bps"], 50)
        self.assertEqual(result["terminal_net_delta_bps"], 60)
        self.assertEqual(result["bridge_residual_bps"], 0)

    def test_same_signal_changed_entry_is_integrity_failure(self):
        baseline = _result([_trade(1, 100)])
        changed = deepcopy(baseline)
        changed["campaigns"][0]["entry"] = 101
        self.assertEqual(owner.path_attribution(baseline, changed)["same_key_path_integrity"], "FAIL")

    def test_empty_winner_denominator_fails_closed(self):
        self.assertIsNone(owner.winner_retention(_result([_trade(1, -20)]), _result([]))["ordinary"]["retention"])

    def test_final_uses_worst_window_pareto_after_both_window_hard_gates(self):
        def window(expectancy, *, passed=True):
            return {"pass": passed, "metrics": {
                "expectancy_bps": expectancy, "PF": 2, "PF_infinite": False,
                "WR": .6, "loss_tail_10pct_mean_bps": -20,
                "marked_DD_bps": 30, "top1_positive_contribution_fraction": .3},
                "P_retention": {"ordinary": {"retention": .8}, "top10": {"retention": .8}}}
        candidates = {
            "U1": {"gene_ids": ["G3_ST_GAP_EXPANDING"],
                   "windows": {"DEV_A": window(100), "DEV_B": window(2)}},
            "U2": {"gene_ids": ["G3_ST_GAP_EXPANDING", "G5_ATR_EXPANDING"],
                   "windows": {"DEV_A": window(5), "DEV_B": window(5)}}}
        self.assertEqual(owner.choose_final(candidates)["selected_candidate"], "U2")
        candidates["U2"]["windows"]["DEV_B"]["pass"] = False
        self.assertEqual(owner.choose_final(candidates)["selected_candidate"], "U1")
        candidates["U1"]["windows"].pop("DEV_B")
        self.assertIsNone(owner.choose_final(candidates)["selected_candidate"])


if __name__ == "__main__":
    unittest.main()
