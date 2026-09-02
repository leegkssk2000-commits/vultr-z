import importlib.util
import json
from copy import deepcopy
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOD_PATH = HERE / "g5_g14_generation_controller_v1.py"
spec = importlib.util.spec_from_file_location("g5g14ctl", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def load_contract():
    return json.loads((HERE / "g5_g14_shared_validation_contract_v1.json").read_text(encoding="utf-8"))


def synthetic_inputs():
    contract = load_contract()
    manifest = {
        "schema_version": "zel.g5_g14.shared_validation_manifest.v2",
        "source_master_commit": "synthetic",
        "authority_files": {
            "shadow": {"blob_sha": "s", "schema_version": "zel.g5.clean_runner.shadow.v1"},
            "telemetry": {"blob_sha": "t", "schema_version": "zel.g5.clean_runner.telemetry.v1"},
            "data_stale": {"blob_sha": "d", "schema_version": "zel.g5.data_stale.evidence.v1"},
            "cutover": {"blob_sha": "c", "schema_version": "zel.g5.clean_runner.cutover_receipt.v1"},
            "economic_ledger": {"blob_sha": "l", "schema_version": "zel.g5.economic_evidence_row.v1"}
        },
        "terminal_receipt": {"blob_sha": "terminal"}
    }
    records = {
        "shadow": {
            "schema_version": "zel.g5.clean_runner.shadow.v1",
            "state": "CLEAN_RUNNER_SHADOW_PASS",
            "shadow_3bar_pass": True,
            "source_parity": True,
            "child_parity": True,
            "duplicate": 0,
            "lookahead": 0,
            "post_cutover_3bar_pass": True
        },
        "telemetry": {
            "schema_version": "zel.g5.clean_runner.telemetry.v1",
            "missing_tuples": 0,
            "complete_tuples": 84
        },
        "data_stale": {
            "schema_version": "zel.g5.data_stale.evidence.v1",
            "authority_created": True,
            "data_stale_authority_allowed": True,
            "authority_value": 1000,
            "authority_unit": "ms",
            "timestamp_integrity": "PASS"
        },
        "cutover": {
            "schema_version": "zel.g5.clean_runner.cutover_receipt.v1",
            "automatic_cutover": False,
            "executed": True,
            "clean_runner_authority": True,
            "production_ready": True
        }
    }
    hashes = {"shadow": "s", "telemetry": "t", "data_stale": "d", "cutover": "c", "economic_ledger": "l"}
    terminal = {
        "schema_version": "zel.g5.independent_validation.terminal.v1",
        "state": "G5_TERMINAL_PASS",
        "oos_pass": True,
        "walk_forward_pass": True,
        "stress_pass": True,
        "source_owner_parity": True,
        "baseline_economic_digest_parity": True,
        "w1_selection_frozen_through_w3": True,
        "fee_slippage_funding_lineage_complete": True,
        "future_mfe_mae_leakage": False,
        "protected_mutation": False,
        "integrity": {"errors": 0, "duplicate": 0, "censored_open": 0, "unknown_exit": 0},
        "windows": {
            "W1": {"net_r": 1.0, "pf": 1.2, "expectancy": 0.1, "payoff": 1.1, "retention_pct": 60},
            "W2": {"net_r": 1.0, "pf": 1.2, "expectancy": 0.1, "payoff": 1.1, "retention_pct": 60},
            "W3": {"net_r": 1.0, "pf": 1.2, "expectancy": 0.1, "payoff": 1.1, "retention_pct": 60}
        }
    }
    ledger = [{"schema_version": "zel.g5.economic_evidence_row.v1", "production_grade": True}]
    return contract, manifest, records, hashes, terminal, ledger


def test_contract_is_fail_closed_and_maps_g6():
    contract = load_contract()
    assert contract["cutover"]["automatic"] is False
    assert contract["shared_invariants"]["fresh_credit_fail_closed"] is True
    assert contract["generation_unlock_rule"] == "G(n+1)_ALLOWED_IFF_G(n)_TERMINAL_PASS"
    assert contract["stage_authority"]["G6"] == "TRADE_METHOD_STANDALONE"
    assert len(contract["controller_stages"]) == 9


def test_current_pinned_snapshot_is_nonterminal_and_g6_closed():
    receipt = mod.derive()
    assert receipt["state"] == "WAIT_DATA_STALE_AUTHORITY"
    assert receipt["completed_stage_count"] == 5
    assert receipt["next_gate"] == "DATA_STALE_AUTHORITY_VALID"
    assert receipt["g5_terminal_pass"] is False
    assert receipt["g6_allowed"] is False
    assert receipt["authority_created_by_controller"] is False
    assert receipt["fresh_credit_granted"] is False


def test_authority_sha_drift_hard_fails():
    contract, manifest, records, hashes, terminal, ledger = synthetic_inputs()
    hashes = deepcopy(hashes)
    hashes["shadow"] = "drift"
    receipt = mod.evaluate(contract=contract, manifest=manifest, records=records, ledger_rows=ledger,
                           ledger_parse_errors=0, observed_hashes=hashes, terminal=terminal,
                           terminal_blob_sha="terminal")
    assert receipt["state"] == "HARD_FAIL_AUTHORITY_SHA_DRIFT"
    assert receipt["g6_allowed"] is False


def test_terminal_receipt_must_be_pinned():
    contract, manifest, records, hashes, terminal, ledger = synthetic_inputs()
    manifest = deepcopy(manifest)
    manifest["terminal_receipt"]["blob_sha"] = None
    receipt = mod.evaluate(contract=contract, manifest=manifest, records=records, ledger_rows=ledger,
                           ledger_parse_errors=0, observed_hashes=hashes, terminal=terminal,
                           terminal_blob_sha="terminal")
    assert receipt["state"] == "WAIT_G5_TERMINAL_RECEIPT_PIN"
    assert receipt["g6_allowed"] is False


def test_complete_nine_gate_terminal_path_unlocks_g6():
    contract, manifest, records, hashes, terminal, ledger = synthetic_inputs()
    receipt = mod.evaluate(contract=contract, manifest=manifest, records=records, ledger_rows=ledger,
                           ledger_parse_errors=0, observed_hashes=hashes, terminal=terminal,
                           terminal_blob_sha="terminal")
    assert receipt["state"] == "G5_TERMINAL_PASS"
    assert receipt["completed_stage_count"] == 9
    assert receipt["next_gate"] is None
    assert receipt["g6_allowed"] is True
    assert receipt["g6_stage"] == "TRADE_METHOD_STANDALONE"


def main():
    tests = [
        test_contract_is_fail_closed_and_maps_g6,
        test_current_pinned_snapshot_is_nonterminal_and_g6_closed,
        test_authority_sha_drift_hard_fails,
        test_terminal_receipt_must_be_pinned,
        test_complete_nine_gate_terminal_path_unlocks_g6,
    ]
    for test in tests:
        test()
    print(f"REPLAY_TESTS=PASS count={len(tests)}")


if __name__ == "__main__":
    main()
