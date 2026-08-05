from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_CUMULATIVE_INCUMBENT_SSOT_GUARD_V1"
SCHEMA = "zel.cumulative_incumbent.guard.receipt.v1"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def validate(ssot: Mapping[str, Any], proposal: Mapping[str, Any]) -> dict[str, Any]:
    policy = ssot["comparison_policy"]
    raw = ssot["raw_terminal"]
    current = ssot["current_cumulative_baseline"]
    required = [str(item) for item in policy["required_fields"]]
    blockers: list[str] = []
    for field in required:
        if proposal.get(field) in (None, ""):
            blockers.append(f"REQUIRED_FIELD_MISSING:{field}")

    comparison_type = str(proposal.get("comparison_type") or "")
    control_id = str(proposal.get("control_baseline_id") or "")
    control_sha = str(proposal.get("control_ledger_sha256") or "")
    parent_receipt = str(proposal.get("parent_incumbent_receipt_sha256") or "")
    if comparison_type not in set(policy["allowed_comparison_types"]):
        blockers.append("COMPARISON_TYPE_INVALID")

    if comparison_type == "STANDALONE_ABLATION_NOT_INCREMENTAL":
        if control_id != raw["baseline_id"] or control_sha != raw["ledger_sha256"]:
            blockers.append("STANDALONE_RAW_CONTROL_IDENTITY_MISMATCH")
        if proposal.get("cumulative_superiority_claim_allowed") is not False:
            blockers.append("STANDALONE_CUMULATIVE_CLAIM_MUST_BE_FALSE")
    elif comparison_type == "INCREMENTAL_CUMULATIVE_EFFICACY":
        if control_id == raw["baseline_id"] or control_sha == raw["ledger_sha256"]:
            blockers.append("RAW_BASELINE_RESET_FORBIDDEN")
        if control_id != current["baseline_id"]:
            blockers.append("CURRENT_CUMULATIVE_BASELINE_ID_REQUIRED")
        if current["state"] != "READY":
            blockers.append("CUMULATIVE_MATERIALIZATION_NOT_READY")
        if not current.get("ledger_sha256") or control_sha != current.get("ledger_sha256"):
            blockers.append("CUMULATIVE_LEDGER_SHA_MISMATCH")
        if not current.get("receipt_sha256") or parent_receipt != current.get("receipt_sha256"):
            blockers.append("PARENT_INCUMBENT_RECEIPT_MISMATCH")

    passed = not blockers
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "state": "PASS_CUMULATIVE_INCUMBENT_GUARD" if passed else "BLOCK_CUMULATIVE_BASELINE_RESET",
        "comparison_type": comparison_type,
        "control_baseline_id": control_id or None,
        "blockers": sorted(set(blockers)),
        "incremental_claim_allowed": passed and comparison_type == "INCREMENTAL_CUMULATIVE_EFFICACY",
        "standalone_ablation_allowed": passed and comparison_type == "STANDALONE_ABLATION_NOT_INCREMENTAL",
        "raw_baseline_reset_detected": "RAW_BASELINE_RESET_FORBIDDEN" in blockers,
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
    ssot = {
        "raw_terminal": {"baseline_id": "RAW", "ledger_sha256": "a" * 64},
        "current_cumulative_baseline": {
            "baseline_id": "CUM1",
            "state": "READY",
            "ledger_sha256": "b" * 64,
            "receipt_sha256": "c" * 64,
        },
        "comparison_policy": {
            "required_fields": [
                "comparison_type",
                "control_baseline_id",
                "control_ledger_sha256",
                "parent_incumbent_receipt_sha256",
            ],
            "allowed_comparison_types": [
                "STANDALONE_ABLATION_NOT_INCREMENTAL",
                "INCREMENTAL_CUMULATIVE_EFFICACY",
            ],
        },
    }
    standalone = validate(
        ssot,
        {
            "comparison_type": "STANDALONE_ABLATION_NOT_INCREMENTAL",
            "control_baseline_id": "RAW",
            "control_ledger_sha256": "a" * 64,
            "parent_incumbent_receipt_sha256": "standalone",
            "cumulative_superiority_claim_allowed": False,
        },
    )
    assert standalone["state"] == "PASS_CUMULATIVE_INCUMBENT_GUARD", standalone
    cumulative = validate(
        ssot,
        {
            "comparison_type": "INCREMENTAL_CUMULATIVE_EFFICACY",
            "control_baseline_id": "CUM1",
            "control_ledger_sha256": "b" * 64,
            "parent_incumbent_receipt_sha256": "c" * 64,
        },
    )
    assert cumulative["incremental_claim_allowed"] is True, cumulative
    reset = validate(
        ssot,
        {
            "comparison_type": "INCREMENTAL_CUMULATIVE_EFFICACY",
            "control_baseline_id": "RAW",
            "control_ledger_sha256": "a" * 64,
            "parent_incumbent_receipt_sha256": "c" * 64,
        },
    )
    assert reset["state"] == "BLOCK_CUMULATIVE_BASELINE_RESET", reset
    assert reset["raw_baseline_reset_detected"] is True, reset
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ssot", type=Path)
    parser.add_argument("--proposal", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.ssot or not args.proposal:
        parser.error("ssot and proposal required")
    receipt = validate(read_json(args.ssot), read_json(args.proposal))
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0 if receipt["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
