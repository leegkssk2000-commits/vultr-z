import importlib.util
import json
from copy import deepcopy
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOD_PATH = HERE / "g5_g14_governance_validator_v1.py"
spec = importlib.util.spec_from_file_location("g5g14gov", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def load_contract():
    return json.loads((HERE / "g5_g14_governance_contract_v1.json").read_text(encoding="utf-8"))


def load_lineage():
    return [json.loads(line) for line in (HERE / "g5_g14_experiment_lineage_v1.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def valid_g6_claim():
    return {"generation": 6, "axis": "RR", "formal_credit": 1, "inherited_formal_credit": 0, "g5_terminal_pass": True, "candidate_frozen": True, "fresh_after_freeze_boundary": True, "g6_own_qualification": True, "g6_terminal_receipt": True}


def valid_g9_bundle():
    return {"components": [{"id": "a", "standalone_terminal_pass": True}, {"id": "b", "standalone_terminal_pass": True}], "fresh_interaction_boundary": True, "component_formal_credit_inherited": 0}


def test_01_contract_passes():
    assert mod.validate_contract(load_contract()) == []


def test_02_generation_set_exact_g5_g14():
    assert list(load_contract()["generation_contract"]) == [f"G{i}" for i in range(5, 15)]


def test_03_g5_is_edge_qualification():
    assert load_contract()["generation_contract"]["G5"]["responsibility"] == "EDGE_QUALIFICATION"


def test_04_g6_is_trade_method_exit_lifecycle():
    assert load_contract()["generation_contract"]["G6"]["responsibility"] == "TRADE_METHOD_EXIT_LIFECYCLE_ROBUSTNESS"


def test_05_six_t_is_diagnostic_only():
    assert mod.checkpoint_state(5, 6) == "DIAGNOSTIC_6T_NO_TERMINAL"


def test_06_eleven_t_still_diagnostic():
    assert mod.checkpoint_state(6, 11) == "DIAGNOSTIC_6T_NO_TERMINAL"


def test_07_twelve_t_is_qualification_not_terminal():
    assert mod.checkpoint_state(7, 12) == "QUALIFICATION_12T_NOT_TERMINAL"


def test_08_large_t_does_not_auto_terminal():
    assert mod.checkpoint_state(8, 120) == "QUALIFICATION_12T_NOT_TERMINAL"


def test_09_explicit_terminal_pass_is_separate():
    assert mod.checkpoint_state(9, 12, explicit_terminal_pass=True) == "TERMINAL_PASS"


def test_10_g12_uses_stage_specific_gate():
    assert mod.checkpoint_state(12, 12) == "STAGE_SPECIFIC_GATE"


def test_11_negative_t_invalid():
    assert mod.checkpoint_state(5, -1) == "INVALID_T"


def test_12_transition_requires_terminal_pass():
    assert "TRANSITION_WITHOUT_TERMINAL_PASS" in mod.validate_transition(5, 6, False)


def test_13_transition_cannot_skip_generation():
    assert "TRANSITION_ORDER" in mod.validate_transition(5, 7, True)


def test_14_valid_transition_passes():
    assert mod.validate_transition(5, 6, True) == []


def test_15_g5_rr_zero_credit_is_valid():
    assert mod.validate_credit_claim({"generation": 5, "axis": "RR", "formal_credit": 0, "inherited_formal_credit": 0}, load_contract()) == []


def test_16_g5_rr_formal_credit_rejected():
    errors = mod.validate_credit_claim({"generation": 5, "axis": "MFE", "formal_credit": 1, "inherited_formal_credit": 0}, load_contract())
    assert "G5_RR_NO_CREDIT_VIOLATION" in errors


def test_17_generation_credit_inheritance_rejected():
    errors = mod.validate_credit_claim({"generation": 6, "axis": "RR", "formal_credit": 0, "inherited_formal_credit": 1}, load_contract())
    assert "GENERATION_CREDIT_INHERITANCE" in errors


def test_18_g6_rr_preboundary_credit_rejected():
    claim = valid_g6_claim(); claim["fresh_after_freeze_boundary"] = False
    assert "G6_RR_PREBOUNDARY_CREDIT" in mod.validate_credit_claim(claim, load_contract())


def test_19_g6_rr_without_candidate_freeze_rejected():
    claim = valid_g6_claim(); claim["candidate_frozen"] = False
    assert "G6_RR_WITHOUT_CANDIDATE_FREEZE" in mod.validate_credit_claim(claim, load_contract())


def test_20_g6_rr_without_g5_terminal_rejected():
    claim = valid_g6_claim(); claim["g5_terminal_pass"] = False
    assert "G6_RR_WITHOUT_G5_TERMINAL" in mod.validate_credit_claim(claim, load_contract())


def test_21_g6_rr_without_own_qualification_rejected():
    claim = valid_g6_claim(); claim["g6_own_qualification"] = False
    assert "G6_RR_WITHOUT_OWN_QUALIFICATION" in mod.validate_credit_claim(claim, load_contract())


def test_22_g6_rr_without_terminal_receipt_rejected():
    claim = valid_g6_claim(); claim["g6_terminal_receipt"] = False
    assert "G6_RR_WITHOUT_TERMINAL_RECEIPT" in mod.validate_credit_claim(claim, load_contract())


def test_23_g6_fresh_formal_path_valid():
    assert mod.validate_credit_claim(valid_g6_claim(), load_contract()) == []


def test_24_g9_pass_x_pass_valid():
    assert mod.validate_g9_bundle(valid_g9_bundle()) == []


def test_25_g9_one_failed_component_rejected():
    bundle = valid_g9_bundle(); bundle["components"][1]["standalone_terminal_pass"] = False
    assert "G9_PASS_X_PASS_REQUIRED" in mod.validate_g9_bundle(bundle)


def test_26_g9_needs_fresh_boundary():
    bundle = valid_g9_bundle(); bundle["fresh_interaction_boundary"] = False
    assert "G9_FRESH_BOUNDARY" in mod.validate_g9_bundle(bundle)


def test_27_g9_component_credit_inheritance_rejected():
    bundle = valid_g9_bundle(); bundle["component_formal_credit_inherited"] = 1
    assert "G9_COMPONENT_CREDIT_INHERITANCE" in mod.validate_g9_bundle(bundle)


def test_28_g14_readiness_keeps_authority_blocked():
    assert mod.validate_g14_readiness({"order_authority": "BLOCKED", "live_authority": "BLOCKED", "automatic_live": False}) == []


def test_29_g14_order_enable_rejected():
    assert "G14_ORDER_AUTHORITY_MUST_REMAIN_BLOCKED" in mod.validate_g14_readiness({"order_authority": "ENABLED"})


def test_30_g14_live_enable_rejected():
    assert "G14_LIVE_AUTHORITY_MUST_REMAIN_BLOCKED" in mod.validate_g14_readiness({"live_authority": "ENABLED"})


def test_31_g14_auto_live_rejected():
    assert "G14_AUTOMATIC_LIVE_FORBIDDEN" in mod.validate_g14_readiness({"automatic_live": True})


def test_32_g14_controller_cannot_create_order_authority():
    assert "G14_CONTROLLER_ORDER_AUTHORITY_FORBIDDEN" in mod.validate_g14_readiness({"controller_created_order_authority": True})


def test_33_lineage_genesis_valid():
    assert mod.validate_lineage(load_lineage(), load_contract()) == []


def test_34_lineage_hash_tamper_rejected():
    rows = load_lineage(); rows[0]["axis_id"] = "tampered"
    assert any(e.startswith("LINEAGE_HASH") for e in mod.validate_lineage(rows, load_contract()))


def test_35_lineage_prev_tamper_rejected():
    rows = load_lineage(); row2 = deepcopy(rows[0]); row2["seq"] = 1; row2["experiment_id"] = "second"; row2["axis_id"] = "second"; row2["prev_sha256"] = "wrong"; row2["record_sha256"] = mod.canonical_record_sha256(row2)
    assert "LINEAGE_PREV:1" in mod.validate_lineage(rows + [row2], load_contract())


def test_36_lineage_duplicate_identity_rejected():
    rows = load_lineage(); row2 = deepcopy(rows[0]); row2["seq"] = 1; row2["experiment_id"] = "different_name_same_identity"; row2["prev_sha256"] = rows[0]["record_sha256"]; row2["record_sha256"] = mod.canonical_record_sha256(row2)
    assert "LINEAGE_DUPLICATE:1" in mod.validate_lineage(rows + [row2], load_contract())


def test_37_lineage_authority_unblock_rejected():
    rows = load_lineage(); rows[0]["order_authority"] = "ENABLED"; rows[0]["record_sha256"] = mod.canonical_record_sha256(rows[0])
    assert "LINEAGE_ORDER_AUTHORITY:0" in mod.validate_lineage(rows, load_contract())


def test_38_append_only_identical_prefix_valid():
    assert mod.check_append_only(["a", "b", "c"], ["a", "b"]) == []


def test_39_append_only_rewrite_rejected():
    assert mod.check_append_only(["a", "X", "c"], ["a", "b"]) == ["LINEAGE_REWRITE"]


def test_40_append_only_truncation_rejected():
    assert mod.check_append_only(["a"], ["a", "b"]) == ["LINEAGE_TRUNCATED"]


def test_41_governance_derive_passes_repository_files():
    receipt = mod.derive()
    assert receipt["state"] == "PASS_G5_G14_GOVERNANCE_LOCK", receipt
    assert receipt["g5_rr_formal_credit"] == 0
    assert receipt["qualification_is_terminal"] is False
    assert receipt["g9_pass_x_pass_required"] is True
    assert receipt["g14_auto_live_forbidden"] is True
    assert receipt["order_authority"] == "BLOCKED"
    assert receipt["live_authority"] == "BLOCKED"


def main():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"GOVERNANCE_TESTS=PASS count={len(tests)}")


if __name__ == "__main__":
    main()
