import importlib.util
import json
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
        "schema_version": "zel.g5_g14.shared_validation_manifest.v3",
        "source_master_commit": "synthetic",
        "lane_identity": {"lane_id":"A", "candidate_id":"test-candidate", "boundary_id":"test-boundary"},
        "authority_files": {
            "shadow": {"pin_policy": "RUNTIME_MUTABLE_SCHEMA_AND_INTERNAL_INTEGRITY", "schema_version": "zel.g5.clean_runner.shadow.v1"},
            "telemetry": {"pin_policy": "RUNTIME_MUTABLE_SCHEMA_AND_INTERNAL_INTEGRITY", "schema_version": "zel.g5.clean_runner.telemetry.v1"},
            "data_stale": {"pin_policy": "RUNTIME_MUTABLE_SCHEMA_AND_INTERNAL_INTEGRITY", "schema_version": "zel.g5.data_stale.evidence.v1"},
            "cutover": {"pin_policy": "RUNTIME_MUTABLE_SCHEMA_AND_INTERNAL_INTEGRITY", "schema_version": "zel.g5.clean_runner.cutover_receipt.v1"},
            "economic_ledger": {"pin_policy": "APPENDABLE_EVIDENCE_SCHEMA_AND_ROW_INTEGRITY", "schema_version": "zel.g5.economic_evidence_row.v1"},
        },
        "terminal_receipt": {"pin_policy": "EXACT_GIT_BLOB_AFTER_INDEPENDENT_REVIEW", "blob_sha": "terminal"},
    }
    records = {
        "shadow": {"schema_version": "zel.g5.clean_runner.shadow.v1", "state": "CLEAN_RUNNER_SHADOW_PASS", "shadow_3bar_pass": True, "source_parity": True, "child_parity": True, "duplicate": 0, "lookahead": 0, "post_cutover_3bar_pass": True},
        "telemetry": {"schema_version": "zel.g5.clean_runner.telemetry.v1", "missing_tuples": 0, "complete_tuples": 84},
        "data_stale": {"schema_version": "zel.g5.data_stale.evidence.v1", "authority_created": True, "data_stale_authority_allowed": True, "authority_value": 1000, "authority_unit": "ms", "timestamp_integrity": "PASS"},
        "cutover": {"schema_version": "zel.g5.clean_runner.cutover_receipt.v1", "automatic_cutover": False, "executed": True, "clean_runner_authority": True, "production_ready": True},
    }
    hashes = {"shadow": "s2", "telemetry": "t2", "data_stale": "d2", "cutover": "c2", "economic_ledger": "l2"}
    terminal = {
        "schema_version": "zel.g5.independent_validation.terminal.v1", "state": "G5_TERMINAL_PASS",
        "oos_pass": True, "walk_forward_pass": True, "stress_pass": True, "source_owner_parity": True,
        "baseline_economic_digest_parity": True, "w1_selection_frozen_through_w3": True,
        "fee_slippage_funding_lineage_complete": True, "future_mfe_mae_leakage": False, "protected_mutation": False,
        "integrity": {"errors": 0, "duplicate": 0, "censored_open": 0, "unknown_exit": 0},
        "windows": {
            "W1": {"net_r": 1.0, "pf": 1.2, "expectancy": 0.1, "payoff": 1.1, "retention_pct": 60},
            "W2": {"net_r": 1.0, "pf": 1.2, "expectancy": 0.1, "payoff": 1.1, "retention_pct": 60},
            "W3": {"net_r": 1.0, "pf": 1.2, "expectancy": 0.1, "payoff": 1.1, "retention_pct": 60},
        },
    }
    terminal.update(manifest["lane_identity"])
    terminal["stage"] = "G5B"
    terminal["independence_audit"] = {"N_raw":1,"N_effective":1,"unique_signal_days":1,"unique_symbols":1,"regime_count":1,"largest_same_window_cluster":1,"validated":True,"source_sha256":"synthetic","cluster_method":"same_bar_and_shock"}
    ledger = [{"schema_version": "zel.g5.economic_evidence_row.v1", "production_grade": True, "economic_origin": "GENUINE_EXECUTION"}]
    ledger[0].update(manifest["lane_identity"])
    return contract, manifest, records, hashes, terminal, ledger


def run_eval(contract, manifest, records, hashes, terminal, ledger, terminal_sha="terminal"):
    return mod.evaluate(contract=contract, manifest=manifest, records=records, ledger_rows=ledger, ledger_parse_errors=0, observed_hashes=hashes, terminal=terminal, terminal_blob_sha=terminal_sha)


def test_contract_is_fail_closed_and_maps_g6():
    contract = load_contract()
    assert contract["cutover"]["automatic"] is False
    assert contract["shared_invariants"]["fresh_credit_fail_closed"] is True
    assert contract["generation_unlock_rule"] == mod.UNLOCK_RULE
    assert contract["stage_authority"]["G6"] == "TRADE_METHOD_STANDALONE"


def test_runtime_evidence_sha_change_does_not_fail_static_manifest():
    contract, manifest, records, hashes, terminal, ledger = synthetic_inputs()
    hashes["shadow"] = "new_runtime_blob"
    receipt = run_eval(contract, manifest, records, hashes, terminal, ledger)
    assert receipt["state"] == "G5_TERMINAL_PASS"


def test_unknown_binding_policy_hard_fails():
    contract, manifest, records, hashes, terminal, ledger = synthetic_inputs()
    manifest["authority_files"]["shadow"]["pin_policy"] = "UNKNOWN"
    receipt = run_eval(contract, manifest, records, hashes, terminal, ledger)
    assert receipt["state"] == "HARD_FAIL_AUTHORITY_BINDING_POLICY"
    assert receipt["g6_allowed"] is False


def test_manifest_schema_drift_hard_fails():
    contract, manifest, records, hashes, terminal, ledger = synthetic_inputs()
    manifest["schema_version"] = "drift"
    receipt = run_eval(contract, manifest, records, hashes, terminal, ledger)
    assert receipt["state"] == "HARD_FAIL_CONTRACT_OR_MANIFEST"
    assert receipt["g6_allowed"] is False


def test_proxy_row_never_counts_as_genuine_t():
    contract, manifest, records, hashes, terminal, ledger = synthetic_inputs()
    ledger[0]["economic_origin"] = "REPLAY_CURRENT_PROXY"
    receipt = run_eval(contract, manifest, records, hashes, terminal, ledger)
    assert receipt["state"] == "WAIT_GENUINE_ECONOMIC_T"
    assert receipt["genuine_economic_rows"] == 0
    assert receipt["g6_allowed"] is False


def test_terminal_receipt_must_be_pinned():
    contract, manifest, records, hashes, terminal, ledger = synthetic_inputs()
    manifest["terminal_receipt"]["blob_sha"] = None
    receipt = run_eval(contract, manifest, records, hashes, terminal, ledger)
    assert receipt["state"] == "WAIT_G5_TERMINAL_RECEIPT_PIN"
    assert receipt["g6_allowed"] is False


def test_terminal_receipt_pin_policy_must_be_exact_review():
    contract, manifest, records, hashes, terminal, ledger = synthetic_inputs()
    manifest["terminal_receipt"]["pin_policy"] = "RUNTIME_MUTABLE_SCHEMA_AND_INTERNAL_INTEGRITY"
    receipt = run_eval(contract, manifest, records, hashes, terminal, ledger)
    assert receipt["state"] == "HARD_FAIL_G5_TERMINAL_PIN_POLICY"


def test_terminal_blob_sha_drift_hard_fails():
    contract, manifest, records, hashes, terminal, ledger = synthetic_inputs()
    receipt = run_eval(contract, manifest, records, hashes, terminal, ledger, terminal_sha="drift")
    assert receipt["state"] == "HARD_FAIL_G5_TERMINAL_SHA_DRIFT"
    assert receipt["g6_allowed"] is False


def test_malformed_terminal_metric_fails_closed():
    contract, manifest, records, hashes, terminal, ledger = synthetic_inputs()
    terminal["windows"]["W2"]["pf"] = None
    receipt = run_eval(contract, manifest, records, hashes, terminal, ledger)
    assert receipt["state"] == "WAIT_G5_TERMINAL_PASS"
    assert receipt["g6_allowed"] is False


def test_complete_nine_gate_terminal_path_unlocks_g6_but_not_credit():
    contract, manifest, records, hashes, terminal, ledger = synthetic_inputs()
    receipt = run_eval(contract, manifest, records, hashes, terminal, ledger)
    assert receipt["state"] == "G5_TERMINAL_PASS"
    assert receipt["completed_stage_count"] == 9
    assert receipt["g6_allowed"] is True
    assert receipt["g5_rr_formal_credit_allowed"] is False
    assert receipt["g6_fresh_formal_credit_required"] is True
    assert receipt["fresh_credit_granted"] is False


def test_current_repository_snapshot_never_hard_fails_from_runtime_blob_churn():
    receipt = mod.derive()
    assert not receipt["state"].startswith("HARD_FAIL"), receipt
    assert receipt["fresh_credit_granted"] is False
    assert receipt["authority_created_by_controller"] is False
    assert receipt["g5_rr_formal_credit_allowed"] is False
    if receipt["g5_terminal_pass"] is False:
        assert receipt["g6_allowed"] is False



def test_lane_a_pass_does_not_wait_for_lane_b():
    from copy import deepcopy
    c,m,r,h,t,l=synthetic_inputs()
    a=dict(contract=c,manifest=m,records=r,observed_hashes=h,terminal=t,ledger_rows=l,ledger_parse_errors=0,terminal_blob_sha="terminal")
    b=deepcopy(a); b["manifest"]["lane_identity"]["lane_id"]="B"; b["ledger_rows"]=[]; b["terminal"]=None
    result=mod.evaluate_lanes({"A":a,"B":b})
    assert result["A"]["g6_allowed"] is True
    assert result["B"]["g6_allowed"] is False
    assert result["A"]["order_authority"]==result["B"]["order_authority"]=="BLOCKED"


def test_g5a_t6_and_t12_never_substitute_for_terminal():
    for state in ("G5A_DEVELOPMENT_PASS", "EARLY_KILL_OR_CONTINUE", "PROVISIONAL_QUALIFICATION"):
        c,m,r,h,t,l=synthetic_inputs(); t["state"]=state
        assert run_eval(c,m,r,h,t,l)["g6_allowed"] is False
    c,m,r,h,t,l=synthetic_inputs()
    assert run_eval(c,m,r,h,None,l)["g6_allowed"] is False


def test_another_lane_terminal_cannot_unlock_current_lane():
    c,m,r,h,t,l=synthetic_inputs(); t["lane_id"]="B"
    assert run_eval(c,m,r,h,t,l)["g6_allowed"] is False


def test_missing_independence_or_inflated_correlated_t_blocks_terminal():
    c,m,r,h,t,l=synthetic_inputs(); del t["independence_audit"]
    assert run_eval(c,m,r,h,t,l)["g6_allowed"] is False
    c,m,r,h,t,l=synthetic_inputs()
    t["independence_audit"].update(N_raw=6,N_effective=6,largest_same_window_cluster=6)
    assert run_eval(c,m,r,h,t,l)["g6_allowed"] is False


def test_unscoped_legacy_terminal_no_longer_unlocks_global_g6():
    c,m,r,h,t,l=synthetic_inputs(); del m["lane_identity"]
    assert run_eval(c,m,r,h,t,l)["g6_allowed"] is False


def main():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"CONTROLLER_TESTS=PASS count={len(tests)}")


if __name__ == "__main__":
    main()
