from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
REBUILD = ROOT / "backend/research/rebuild"
PREP = ROOT / "backend/research/prep"
INVENTORY = REBUILD / "strategy25_structural_inventory_v2.json"
LEDGER = REBUILD / "a1_exact25_disposition_ledger_v1.json"
CONTRACT = PREP / "g4_improvement_prep_contract_v1.json"
INDEX = PREP / "g4_exact25_evidence_index_v1.json"
RECEIPT = PREP / "g4_improvement_prep_ready_v1.json"

FORBIDDEN_ECON_KEYS = {
    "net_pnl_bps", "net_expectancy_bps", "gross_expectancy_bps", "profit_factor",
    "payoff", "win_rate", "drawdown_bps", "completed_trades", "event_count", "intent_count",
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_authority(obj: dict[str, Any]) -> None:
    a = obj.get("authority", obj)
    assert a.get("selection_authority") is False
    assert a.get("promotion_authority") is False
    assert a.get("execution_authority") == "NONE"
    assert a.get("order_authority") == "BLOCKED"
    assert a.get("live_trade_authority") == "BLOCKED"
    assert int(a.get("protected_mutations", 0)) == 0


def build_index(root: Path = ROOT) -> dict[str, Any]:
    inventory = load(root / INVENTORY.relative_to(ROOT))
    ledger = load(root / LEDGER.relative_to(ROOT))
    assert_authority(inventory)
    assert_authority(ledger)
    strategies = inventory["strategies"]
    assert len(strategies) == 25
    assert int(inventory["identity_count"]) == 25
    assert int(inventory["complete_policy_count"]) == 25

    out: dict[str, Any] = {}
    for sid, spec in sorted(strategies.items()):
        l = ledger["strategies"][sid]
        # G4 prep may consume only immutable identity/lineage fields; never baseline economics.
        assert not (FORBIDDEN_ECON_KEYS & {k for k in l if k.startswith("selected_")})
        policy_rel = spec["policy_owner"]
        packet_rel = spec["evidence_packet"]
        policy = root / policy_rel
        packet = root / packet_rel
        assert policy.exists(), policy_rel
        assert packet.exists(), packet_rel
        config_sha = l.get("config_sha")
        assert isinstance(config_sha, str) and len(config_sha) >= 40, f"missing frozen config_sha:{sid}"
        evidence_sha = l.get("evidence_sha")
        assert isinstance(evidence_sha, str) and len(evidence_sha) >= 40, f"missing frozen evidence_sha:{sid}"
        out[sid] = {
            "policy_path": policy_rel,
            "policy_file_sha256": file_sha256(policy),
            "policy_authority_sha": l.get("policy_sha"),
            "config_sha": config_sha,
            "evidence_packet_path": packet_rel,
            "evidence_packet_sha256": file_sha256(packet),
            "evidence_authority_sha": evidence_sha,
            "source_ids": [packet_rel],
            "baseline_generation": int(l.get("generation", 1)),
        }
    assert len(out) == 25
    return {
        "schema_version": "zel.g4_exact25_evidence_index.v1",
        "state": "G4_EXACT25_EVIDENCE_INDEX_READY",
        "research_only": True,
        "authority": {
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "protected_mutations": 0,
        },
        "identity_count": 25,
        "economic_outcomes_consumed": False,
        "strategies": out,
    }


def validate_contract(contract: dict[str, Any]) -> None:
    assert_authority(contract)
    assert contract["attempt_budget"]["same_strategy_axis_data_sha_max"] == 1
    assert float(contract["attempt_budget"]["semantic_duplicate_cosine_gt"]) == 0.85
    assert contract["attempt_budget"]["meta_audit_after_distinct_strategies_failed"] == 3
    assert contract["attempt_budget"]["meta_audit_after_architecture_attempts_failed"] == 6
    assert contract["incumbent_contract"]["promote_new_incumbent_only_after_deterministic_pass"] is True
    assert contract["incumbent_contract"]["failed_attempt_retains_previous_incumbent"] is True
    assert contract["incumbent_contract"]["rollback_to_previous_incumbent_on_fail"] is True
    assert contract["external_evidence"]["sealed_a1_economics_may_be_exposed"] is False
    assert contract["a1_authority"]["generation2_before_25_terminal"] == "FORBIDDEN"
    for fp, axes in contract["failure_fingerprints"].items():
        assert axes, fp
        for axis in axes:
            assert axis in contract["causal_axes"], (fp, axis)


def build_ready_receipt(index: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    validate_contract(contract)
    assert index["identity_count"] == 25
    assert index["economic_outcomes_consumed"] is False
    return {
        "schema_version": "zel.g4_improvement_prep_ready.v1",
        "state": "G4_IMPROVEMENT_PREP_READY",
        "research_only": True,
        "authority": index["authority"],
        "exact25_evidence_index_count": 25,
        "fingerprint_taxonomy_ready": True,
        "causal_axis_registry_ready": True,
        "autopsy_preregistration_template_ready": True,
        "cumulative_incumbent_rollback_contract_ready": True,
        "meta_audit_contract_ready": True,
        "semantic_dedup_cosine_gt": 0.85,
        "same_strategy_axis_data_sha_max": 1,
        "generation2_evaluator_created": False,
        "a1_mutated": False,
        "economic_outcomes_consumed": False,
        "index_sha256": hashlib.sha256(json.dumps(index, sort_keys=True).encode()).hexdigest(),
        "contract_sha256": hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    index = build_index()
    contract = load(CONTRACT)
    receipt = build_ready_receipt(index, contract)
    if args.write:
        INDEX.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
        RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
