from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_SKILL_EXTENSION_CONTRACT_V1"
ALLOWED_ACTIONS = {"reduce25", "partial30", "hold", "stop", "route_change", "rollback", "block"}
REQUIRED_NEW = {
    "SK_EXIT_PARTIAL_STOP_30",
    "SK_EXIT_PROFIT_LOCK",
    "SK_RISK_VOLATILITY_REDUCE_25",
    "SK_GUARD_LIQUIDATION_BUFFER",
    "SK_EXIT_STRUCTURE_INVALIDATION",
}
LOSS_ADDS = {"SK_ADD_DCA", "SK_ADD_AVG_DOWN", "SK_ADD_WATER_ADD"}
PROFIT_ADDS = {"SK_ADD_PYRAMIDING", "SK_ADD_PROFITABLE_SCALE_IN"}
SAFE = {
    "research_only": True,
    "selection_authority": False,
    "promotion_authority": False,
    "runtime_binding_allowed": False,
    "shadow_start_allowed": False,
    "paper_enabled": False,
    "live_enabled": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "action": "hold",
}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def stable_sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"NONFINITE:{value}")
    return number


def skill_map(contract: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = contract.get("new_skills") or []
    if not isinstance(rows, list):
        raise RuntimeError("NEW_SKILLS_NOT_LIST")
    result: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise RuntimeError("SKILL_NOT_OBJECT")
        skill_id = str(raw.get("skill_id") or "").strip()
        if not skill_id or skill_id in result:
            raise RuntimeError(f"SKILL_ID_INVALID_OR_DUPLICATE:{skill_id}")
        result[skill_id] = dict(raw)
    return result


def pair_allowed(left: str, right: str, skills: Mapping[str, Mapping[str, Any]]) -> tuple[bool, str]:
    pair = {left, right}
    if left == right:
        return False, "DUPLICATE_SKILL"
    if pair & LOSS_ADDS and pair & PROFIT_ADDS:
        return False, "LOSS_AND_PROFIT_DIRECTION_ADD_CONFLICT"
    if "SK_EXIT_PARTIAL_STOP_30" in pair and pair & LOSS_ADDS:
        return False, "PARTIAL_STOP_WITH_LOSS_DIRECTION_ADD_FORBIDDEN"
    for skill_id in pair:
        row = skills.get(skill_id)
        if row and bool(row.get("observer_only")):
            return False, "OBSERVER_ONLY_SKILL"
        forbidden = set(str(v) for v in (row or {}).get("forbidden_with") or [])
        other = right if skill_id == left else left
        if other in forbidden:
            return False, "EXPLICIT_FORBIDDEN_PAIR"
    return True, "PAIR_ALLOWED_FOR_RESEARCH_AFTER_MAIN_EFFECT"


def validate(contract: Mapping[str, Any]) -> dict[str, Any]:
    if contract.get("schema_version") != "zel.skill_extension.contract.v1":
        raise RuntimeError("SCHEMA_VERSION_INVALID")
    allowed = set(str(value) for value in contract.get("allowed_actions") or [])
    if allowed != ALLOWED_ACTIONS:
        raise RuntimeError(f"ALLOWED_ACTION_SET_INVALID:{sorted(allowed)}")
    safety = dict(contract.get("safety") or {})
    required_safety = {
        "research_only": True,
        "promotion_authority": False,
        "selection_authority": False,
        "runtime_binding_allowed": False,
        "shadow_start_allowed": False,
        "paper_enabled": False,
        "live_enabled": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "canonical_strategy_files_mutated": False,
        "canonical_registry_mutated": False,
        "maximum_active_skills_per_bundle": 2,
        "maximum_add_count": 1,
    }
    failures = {key: {"expected": wanted, "actual": safety.get(key)} for key, wanted in required_safety.items() if safety.get(key) != wanted}
    if failures:
        raise RuntimeError("SAFETY_CONTRACT_INVALID:" + canonical(failures))
    if finite(safety.get("maximum_planned_loss_r")) > 0.75:
        raise RuntimeError("PLANNED_LOSS_CAP_GT_0P75R")

    existing = [str(value) for value in contract.get("existing_skill_ids") or []]
    if len(existing) != len(set(existing)):
        raise RuntimeError("EXISTING_SKILL_DUPLICATE")
    skills = skill_map(contract)
    if set(skills) != REQUIRED_NEW:
        raise RuntimeError(f"NEW_SKILL_SET_INVALID:{sorted(set(skills))}")
    overlap = set(existing).intersection(skills)
    if overlap:
        raise RuntimeError(f"EXISTING_NEW_OVERLAP:{sorted(overlap)}")

    skill_checks: dict[str, dict[str, Any]] = {}
    for skill_id, row in sorted(skills.items()):
        action = str(row.get("action") or "")
        if action not in ALLOWED_ACTIONS:
            raise RuntimeError(f"SKILL_ACTION_INVALID:{skill_id}:{action}")
        required_fields = row.get("required_fields")
        if not isinstance(required_fields, list) or not required_fields:
            raise RuntimeError(f"REQUIRED_FIELDS_INVALID:{skill_id}")
        observer = bool(row.get("observer_only"))
        eligible = bool(row.get("selection_eligible_after_exact_path_replay"))
        if observer and eligible:
            raise RuntimeError(f"OBSERVER_SKILL_SELECTION_ELIGIBLE:{skill_id}")
        if not str(row.get("falsification") or "").strip():
            raise RuntimeError(f"FALSIFICATION_MISSING:{skill_id}")
        skill_checks[skill_id] = {
            "action": action,
            "observer_only": observer,
            "selection_eligible_after_exact_path_replay": eligible,
            "required_field_count": len(required_fields),
            "pass": True,
        }

    logger = set(str(value) for value in contract.get("required_logger_fields") or [])
    required_logger = {
        "skill_applied", "skill_name", "skill_trigger_ts", "skill_context",
        "skill_before_entry", "skill_after_entry", "skill_cost", "skill_delta_r", "skill_exit_role",
    }
    if logger != required_logger:
        raise RuntimeError(f"LOGGER_FIELDS_INVALID:{sorted(logger)}")

    boundaries = dict(contract.get("role_boundaries") or {})
    if set(boundaries) != {"ZICO", "LICO", "ZLICE", "STRATEGY_NATIVE", "PORTFOLIO_RISK"}:
        raise RuntimeError("ROLE_BOUNDARY_SET_INVALID")

    catalog = existing + sorted(skills)
    pair_rows = []
    for left, right in itertools.combinations(catalog, 2):
        allowed_pair, reason = pair_allowed(left, right, skills)
        pair_rows.append({"left": left, "right": right, "allowed": allowed_pair, "reason": reason})
    if any(row["allowed"] for row in pair_rows if row["left"] in LOSS_ADDS and row["right"] in PROFIT_ADDS):
        raise RuntimeError("LOSS_PROFIT_ADD_PAIR_LEAK")

    roadmap = [str(value) for value in contract.get("roadmap") or []]
    expected_prefix = [
        "DATA_B_15M_1M_TERMINAL_AUTHORITY",
        "RISK_MAIN_EFFECT",
        "SKILL_SINGLE_MAIN_EFFECT",
        "STRATEGY_REGIME_COMPATIBILITY",
        "SELECTED_PAIR_INTERACTIONS",
        "STRATEGY_TOP3_SKILL_BUNDLES",
    ]
    if roadmap[: len(expected_prefix)] != expected_prefix:
        raise RuntimeError("ROADMAP_PREFIX_INVALID")

    output = {
        "schema_version": "zel.skill_extension.validation.v1",
        "version": VERSION,
        "state": "PASS_SKILL_EXTENSION_CONTRACT",
        "existing_skill_count": len(existing),
        "new_skill_count": len(skills),
        "catalog_skill_count": len(catalog),
        "new_skill_checks": skill_checks,
        "pair_count": len(pair_rows),
        "allowed_pair_count": sum(bool(row["allowed"]) for row in pair_rows),
        "blocked_pair_count": sum(not bool(row["allowed"]) for row in pair_rows),
        "pair_matrix": pair_rows,
        "maximum_active_skills_per_bundle": 2,
        "maximum_planned_loss_r": finite(safety["maximum_planned_loss_r"]),
        "role_boundaries_proved": True,
        "logger_contract_complete": True,
        "economic_improvement_claim_allowed": False,
        "next": "WAIT_DATA_B_RISK_MAIN_EFFECT_THEN_RUN_SKILL_SINGLE_EFFECT",
        "contract_sha256": stable_sha(contract),
        **SAFE,
    }
    output["receipt_sha256"] = stable_sha(output)
    return output


def self_test() -> None:
    root = Path(__file__).resolve().parents[1]
    contract = read_json(root / "research" / "zel_skill_extension_contract_v1.json")
    result = validate(contract)
    assert result["state"] == "PASS_SKILL_EXTENSION_CONTRACT"
    assert result["new_skill_count"] == 5
    skills = skill_map(contract)
    assert pair_allowed("SK_EXIT_PARTIAL_STOP_30", "SK_ADD_DCA", skills)[0] is False
    assert pair_allowed("SK_EXIT_PROFIT_LOCK", "SK_EXIT_TRAILING_STOP", skills)[0] is True
    assert pair_allowed("SK_GUARD_LIQUIDATION_BUFFER", "SK_EXIT_PROFIT_LOCK", skills)[0] is False
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION, "receipt": result["receipt_sha256"]}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.contract or not args.out:
        parser.error("--contract and --out are required")
    result = validate(read_json(args.contract))
    write_json(args.out, result)
    print(json.dumps({"state": result["state"], "new_skills": result["new_skill_count"], "next": result["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
