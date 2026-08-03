from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

VERSION = "ZEL_AUTONOMY_GOVERNANCE_VALIDATOR_V1"
SCHEMA = "zel.autonomy.governance.receipt.v1"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def stable_sha(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_policy(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    authority = policy.get("authority") or {}
    gemini = policy.get("gemini_contract") or {}
    ledger = policy.get("ai_value_ledger") or {}
    survivor = policy.get("economic_survivor_gate") or {}
    top3 = policy.get("top3_entry_gate") or {}
    objective = policy.get("optimization_objective") or {}
    resource = policy.get("resource_policy") or {}

    for key in (
        "canonical_mutation",
        "registry_mutation",
        "runtime_mutation",
        "formal_ledger_mutation",
        "selection_authority",
        "promotion_authority",
    ):
        if authority.get(key) is not False:
            errors.append(f"AUTHORITY_NOT_FAIL_CLOSED:{key}")
    if authority.get("execution_authority") != "NONE":
        errors.append("EXECUTION_AUTHORITY_NOT_NONE")
    if authority.get("order_authority") != "BLOCKED":
        errors.append("ORDER_AUTHORITY_NOT_BLOCKED")
    if authority.get("deterministic_gate_overrides_ai") is not True:
        errors.append("DETERMINISTIC_GATE_NOT_AUTHORITATIVE")

    designer = set(gemini.get("designer_models") or [])
    redteam = set(gemini.get("redteam_models") or [])
    if not designer or not redteam:
        errors.append("GEMINI_MODEL_POOL_EMPTY")
    if designer & redteam:
        errors.append("GEMINI_MODEL_POOLS_OVERLAP")
    if gemini.get("redteam_dissent_is_fail_closed") is not True:
        errors.append("GEMINI_DISSENT_NOT_FAIL_CLOSED")
    if gemini.get("deterministic_fallback_cannot_convert_failed_experiment_to_pass") is not True:
        errors.append("DETERMINISTIC_FALLBACK_CAN_PROMOTE_FAILURE")
    for privacy_key in (
        "raw_trade_rows_sent",
        "raw_prices_sent",
        "private_code_sent",
        "credentials_sent",
    ):
        if gemini.get(privacy_key) is not False:
            errors.append(f"GEMINI_PRIVACY_BOUNDARY_INVALID:{privacy_key}")

    if ledger.get("required") is not True or ledger.get("one_row_per_epoch") is not True:
        errors.append("AI_VALUE_LEDGER_NOT_REQUIRED")
    required_ledger = set(ledger.get("required_fields") or [])
    for key in (
        "ai_proposed_axis",
        "deterministic_axis",
        "selected_axis",
        "w1_delta_net_R",
        "w2_delta_net_R",
        "w3_delta_net_R",
        "false_positive",
        "receipt_sha256",
    ):
        if key not in required_ledger:
            errors.append(f"AI_VALUE_LEDGER_FIELD_MISSING:{key}")

    for key, expected in (
        ("net_R_gt", 0.0),
        ("profit_factor_gte", 1.0),
        ("expectancy_R_gt", 0.0),
        ("payoff_ratio_gte", 1.0),
        ("minimum_retention_pct", 60.0),
        ("error_count_max", 0),
        ("duplicate_count_max", 0),
        ("censored_open_count_max", 0),
    ):
        if survivor.get(key) != expected:
            errors.append(f"SURVIVOR_GATE_MISMATCH:{key}")
    if survivor.get("w1_selected_config_frozen_for_w2_w3") is not True:
        errors.append("W2_W3_RETUNING_ALLOWED")
    if survivor.get("future_MFE_MAE_forbidden") is not True:
        errors.append("FUTURE_INFORMATION_NOT_FORBIDDEN")

    if top3.get("minimum_exact_source_survivors") != 3:
        errors.append("TOP3_SURVIVOR_COUNT_NOT_3")
    if top3.get("minimum_reserve_candidates") != 2:
        errors.append("TOP3_RESERVE_COUNT_NOT_2")
    if objective.get("promotion_method") != "LEXICOGRAPHIC_PARETO":
        errors.append("PROMOTION_METHOD_NOT_PARETO")
    for key in (
        "do_not_optimize_win_rate_alone",
        "do_not_optimize_payoff_alone",
        "do_not_optimize_entry_count_alone",
    ):
        if objective.get(key) is not True:
            errors.append(f"SINGLE_METRIC_OPTIMIZATION_ALLOWED:{key}")
    if resource.get("maximum_concurrent_heavy_vps_replays") != 1:
        errors.append("HEAVY_VPS_CONCURRENCY_NOT_ONE")
    return errors


def validate_gemini_review(
    policy: dict[str, Any],
    review: dict[str, Any],
    evidence_receipt_sha256: str | None,
) -> list[str]:
    errors: list[str] = []
    contract = policy["gemini_contract"]
    accepted = {str(v).upper() for v in contract["accepted_verdicts"]}
    verdict = str(
        review.get("verdict")
        or (review.get("response") or {}).get("verdict")
        or ""
    ).upper()
    model = str(review.get("model") or "")
    if verdict not in accepted:
        errors.append(f"GEMINI_DISSENT:{verdict or 'MISSING'}")
    if model not in set(contract["redteam_models"]):
        errors.append(f"REDTEAM_MODEL_NOT_ALLOWED:{model or 'MISSING'}")
    response = review.get("response") if isinstance(review.get("response"), dict) else review
    for key in ("reason", "hidden_failure"):
        if not str(response.get(key) or "").strip():
            errors.append(f"GEMINI_REVIEW_FIELD_MISSING:{key}")
    bound = review.get("evidence_receipt_sha256") or review.get("screen_receipt_sha256")
    if evidence_receipt_sha256 and bound != evidence_receipt_sha256:
        errors.append("GEMINI_REVIEW_EVIDENCE_SHA_MISMATCH")
    for key in ("selection_authority", "promotion_authority"):
        if review.get(key) is not False:
            errors.append(f"GEMINI_AUTHORITY_INVALID:{key}")
    if review.get("execution_authority") != "NONE":
        errors.append("GEMINI_EXECUTION_AUTHORITY_INVALID")
    if review.get("order_authority") != "BLOCKED":
        errors.append("GEMINI_ORDER_AUTHORITY_INVALID")
    return errors


def self_test() -> int:
    policy = {
        "authority": {
            "canonical_mutation": False,
            "registry_mutation": False,
            "runtime_mutation": False,
            "formal_ledger_mutation": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "deterministic_gate_overrides_ai": True,
        },
        "gemini_contract": {
            "designer_models": ["gemini-designer"],
            "redteam_models": ["gemini-redteam"],
            "redteam_dissent_is_fail_closed": True,
            "deterministic_fallback_cannot_convert_failed_experiment_to_pass": True,
            "raw_trade_rows_sent": False,
            "raw_prices_sent": False,
            "private_code_sent": False,
            "credentials_sent": False,
            "accepted_verdicts": ["ACCEPT"],
        },
        "ai_value_ledger": {
            "required": True,
            "one_row_per_epoch": True,
            "required_fields": [
                "ai_proposed_axis", "deterministic_axis", "selected_axis",
                "w1_delta_net_R", "w2_delta_net_R", "w3_delta_net_R",
                "false_positive", "receipt_sha256",
            ],
        },
        "economic_survivor_gate": {
            "net_R_gt": 0.0,
            "profit_factor_gte": 1.0,
            "expectancy_R_gt": 0.0,
            "payoff_ratio_gte": 1.0,
            "minimum_retention_pct": 60.0,
            "error_count_max": 0,
            "duplicate_count_max": 0,
            "censored_open_count_max": 0,
            "w1_selected_config_frozen_for_w2_w3": True,
            "future_MFE_MAE_forbidden": True,
        },
        "top3_entry_gate": {
            "minimum_exact_source_survivors": 3,
            "minimum_reserve_candidates": 2,
        },
        "optimization_objective": {
            "promotion_method": "LEXICOGRAPHIC_PARETO",
            "do_not_optimize_win_rate_alone": True,
            "do_not_optimize_payoff_alone": True,
            "do_not_optimize_entry_count_alone": True,
        },
        "resource_policy": {"maximum_concurrent_heavy_vps_replays": 1},
    }
    assert not validate_policy(policy)
    good = {
        "model": "gemini-redteam",
        "verdict": "ACCEPT",
        "reason": "metrics and protocol agree",
        "hidden_failure": "none found",
        "evidence_receipt_sha256": "a" * 64,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }
    assert not validate_gemini_review(policy, good, "a" * 64)
    bad = dict(good, verdict="REJECT")
    assert validate_gemini_review(policy, bad, "a" * 64)
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--gemini-review", type=Path)
    parser.add_argument("--evidence-receipt", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.policy or not args.out:
        parser.error("--policy and --out are required")
    policy = read_json(args.policy)
    errors = validate_policy(policy)
    evidence_sha: str | None = None
    if args.evidence_receipt:
        evidence = read_json(args.evidence_receipt)
        evidence_sha = str(evidence.get("receipt_sha256") or "") or None
    if args.gemini_review:
        review = read_json(args.gemini_review)
        errors.extend(validate_gemini_review(policy, review, evidence_sha))
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "state": "PASS_AUTONOMY_GOVERNANCE" if not errors else "HOLD_AUTONOMY_GOVERNANCE",
        "errors": sorted(set(errors)),
        "error_count": len(set(errors)),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": receipt["state"], "error_count": receipt["error_count"]}, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
