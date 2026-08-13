from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_EVENT_CORPUS_STRESS_USE_GATE_V1"
SCHEMA = "zel.event_corpus.stress_use.gate.receipt.v1"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("JSON_OBJECT_REQUIRED")
    return value


def validate(contract: Mapping[str, Any], proposal: Mapping[str, Any]) -> dict[str, Any]:
    admission = contract["admission"]
    dataset = contract["dataset"]
    blockers: list[str] = []
    for field in admission["required_candidate_fields"]:
        if proposal.get(field) in (None, ""):
            blockers.append(f"CANDIDATE_FIELD_MISSING:{field}")
    if proposal.get("candidate_selected_before_dataset_access") is not True:
        blockers.append("CANDIDATE_NOT_SELECTED_BEFORE_EVENT_ACCESS")
    if proposal.get("candidate_frozen_before_dataset_access") is not True:
        blockers.append("CANDIDATE_NOT_FROZEN_BEFORE_EVENT_ACCESS")
    if proposal.get("event_labels_used_for_parameter_tuning") is not False:
        blockers.append("EVENT_LABEL_TUNING_FORBIDDEN")
    if proposal.get("w1_ranking_mutated_after_event_access") is not False:
        blockers.append("W1_RANKING_MUTATION_FORBIDDEN")
    if proposal.get("dataset_sha256") != dataset["dataset_sha256"]:
        blockers.append("EVENT_DATASET_SHA_MISMATCH")
    if proposal.get("dataset_receipt_sha256") != dataset["receipt_sha256"]:
        blockers.append("EVENT_DATASET_RECEIPT_MISMATCH")
    if proposal.get("source_unavailable_synthesized") is not False:
        blockers.append("SOURCE_UNAVAILABLE_SYNTHESIS_FORBIDDEN")
    passed = not blockers
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "state": "PASS_EVENT_CORPUS_STRESS_USE_GATE" if passed else "BLOCK_EVENT_CORPUS_STRESS_USE",
        "blockers": sorted(set(blockers)),
        "stress_execution_allowed": passed,
        "parameter_tuning_allowed": False,
        "economic_superiority_claim_allowed": False,
        "protected_mutations": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold" if passed else "block",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def self_test() -> int:
    contract = {
        "dataset": {"dataset_sha256": "a" * 64, "receipt_sha256": "b" * 64},
        "admission": {"required_candidate_fields": ["candidate_id", "candidate_source_sha256", "candidate_config_sha256", "selection_receipt_sha256", "control_baseline_id", "control_ledger_sha256"]},
    }
    good = {
        "candidate_id": "c1", "candidate_source_sha256": "c" * 64, "candidate_config_sha256": "d" * 64,
        "selection_receipt_sha256": "e" * 64, "control_baseline_id": "cum1", "control_ledger_sha256": "f" * 64,
        "candidate_selected_before_dataset_access": True, "candidate_frozen_before_dataset_access": True,
        "event_labels_used_for_parameter_tuning": False, "w1_ranking_mutated_after_event_access": False,
        "dataset_sha256": "a" * 64, "dataset_receipt_sha256": "b" * 64, "source_unavailable_synthesized": False,
    }
    assert validate(contract, good)["state"] == "PASS_EVENT_CORPUS_STRESS_USE_GATE"
    bad = dict(good, event_labels_used_for_parameter_tuning=True)
    assert validate(contract, bad)["state"] == "BLOCK_EVENT_CORPUS_STRESS_USE"
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--proposal", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.contract or not args.proposal:
        parser.error("contract and proposal required")
    receipt = validate(read_json(args.contract), read_json(args.proposal))
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0 if receipt["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
