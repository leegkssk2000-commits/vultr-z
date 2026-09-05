#!/usr/bin/env python3
"""Shared fail-closed governance validator for ZEL G5..G14.

This module creates no trading authority. It validates generation boundaries,
statistical checkpoint semantics, fresh-credit separation, interaction gating,
controlled-live locks, and the append-only experiment lineage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.research.rebuild import g5_g14_generation_controller_v1 as controller
REBUILD = ROOT / "backend" / "research" / "rebuild"
CONTRACT_PATH = REBUILD / "g5_g14_governance_contract_v1.json"
LINEAGE_PATH = REBUILD / "g5_g14_experiment_lineage_v1.jsonl"
OUT = REBUILD / "g5_g14_governance_validation_receipt_v1.json"

EXPECTED_STAGES = {
    "G5": "INDEPENDENT_OOS_WALK_FORWARD_STRESS_VALIDATION",
    "G6": "TRADE_METHOD_STANDALONE",
    "G7": "SKILL_STANDALONE",
    "G8": "BOT_ADVISOR_STANDALONE",
    "G9": "SELECTED_INTERACTIONS_AND_STRATEGY_TOP3_BUNDLES",
    "G10": "BINGX_EXECUTION_COST_CALIBRATION",
    "G11": "PORTFOLIO_JOINT_RISK_AND_ROLLBACK",
    "G12": "SHADOW_200C_300C_PARITY",
    "G13": "PAPER_30D_CANARY",
    "G14": "CONTROLLED_LIVE_READINESS",
}
RESEARCH_T_GENERATIONS = set(range(5, 12))


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_no} must contain an object")
        rows.append(value)
    return rows


def canonical_record_sha256(row: dict[str, Any]) -> str:
    payload = {k: v for k, v in row.items() if k != "record_sha256"}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_contract(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if contract.get("schema_version") != "zel.g5_g14.governance_contract.v1":
        errors.append("CONTRACT_SCHEMA")
    scope = contract.get("scope", {})
    if scope.get("from_generation") != 5 or scope.get("to_generation") != 14:
        errors.append("GENERATION_SCOPE")
    if scope.get("reuse_required") is not True or scope.get("rebuild_per_generation_forbidden") is not True:
        errors.append("SHARED_VALIDATOR_REUSE")
    current = contract.get("effective_development_objective", {})
    if current.get("primary") != "EXISTING_TOP5_CUMULATIVE_IMPROVEMENT" or current.get("alpha_factory_required") is not False:
        errors.append("CURRENT_TOP5_OBJECTIVE")
    for key in ("risk", "stop", "cost", "integrity", "explicit_live_approval"):
        if key not in current.get("never_exempt", []): errors.append("SAFETY_CHECK_EXEMPTED:"+key)

    generations = contract.get("generation_contract", {})
    if list(generations.keys()) != list(EXPECTED_STAGES.keys()):
        errors.append("GENERATION_ORDER_OR_SET")
    for key, stage in EXPECTED_STAGES.items():
        if generations.get(key, {}).get("roadmap_stage") != stage:
            errors.append(f"{key}_ROADMAP_STAGE")

    g5 = generations.get("G5", {})
    if g5.get("responsibility") != "EDGE_QUALIFICATION":
        errors.append("G5_NOT_EDGE_QUALIFICATION")
    if g5.get("rr_lifecycle_policy") != "OBSERVE_PARALLEL_NO_CREDIT":
        errors.append("G5_RR_NOT_NO_CREDIT")

    g6 = generations.get("G6", {})
    if g6.get("responsibility") != "TRADE_METHOD_EXIT_LIFECYCLE_ROBUSTNESS":
        errors.append("G6_NOT_TRADE_METHOD")
    if not g6.get("fresh_candidate_freeze_required") or not g6.get("fresh_boundary_required"):
        errors.append("G6_FRESH_BOUNDARY_NOT_REQUIRED")
    if g6.get("g5_rr_observations_inherited_as_formal_credit") is not False:
        errors.append("G6_INHERITS_G5_RR")
    g7 = generations.get("G7", {})
    exit_ops = {"SL_STOP_POLICY", "TP_PAYOFF_POLICY", "TIME_DECAY_EXIT", "VOLATILITY_ADAPTIVE_EXIT", "PARTIAL_EXIT", "TRAILING", "MFE_RUNNER", "REGIME_CONDITIONED_EXIT", "TRADE_LIFECYCLE_MONEY_EXTRACTION"}
    position_ops = {"SCALE_IN", "PYRAMIDING", "CONDITIONAL_DCA", "RISK_NORMALIZED_SIZING", "POSITION_CONSTRUCTION"}
    if set(g6.get("owned_operations", [])) != exit_ops or set(g7.get("owned_operations", [])) != position_ops:
        errors.append("G6_G7_OWNERSHIP")
    progression = contract.get("lane_progression", {})
    if contract.get("authority", {}).get("generation_unlock_rule") != controller.UNLOCK_RULE:
        errors.append("LANE_UNLOCK_RULE")
    if any(progression.get(k) is not False for k in ("other_lane_wait_or_fail_blocks", "g5a_development_pass_unlocks_g6", "t6_continue_unlocks_g6", "t12_qualification_unlocks_g6")):
        errors.append("LANE_UNLOCK_BOUNDARY")
    if progression.get("lane_local_through") != "G8" or progression.get("global_join_begins_at") != "G9":
        errors.append("LANE_GLOBAL_JOIN")

    stats = contract.get("statistics_contract", {})
    if stats.get("sample_unit") != "GENUINE_PRODUCTION_GRADE_CLOSED_T":
        errors.append("STAT_SAMPLE_UNIT")
    if stats.get("diagnostic_checkpoint_t") != 6:
        errors.append("STAT_6T")
    if stats.get("qualification_checkpoint_t") != 12:
        errors.append("STAT_12T")
    if stats.get("qualification_checkpoint_is_terminal") is not False:
        errors.append("STAT_12T_AUTO_TERMINAL")
    if stats.get("terminal_requires_explicit_terminal_receipt") is not True:
        errors.append("STAT_TERMINAL_RECEIPT")
    audit = stats.get("independence_audit", {})
    if set(audit.get("required_fields", [])) != set(controller.INDEPENDENCE_FIELDS) or audit.get("missing_or_unvalidated_audit") != "BLOCK_TERMINAL":
        errors.append("STAT_INDEPENDENCE_AUDIT")
    if audit.get("N_effective_terminal_threshold") is not None and not audit.get("threshold_authority"):
        errors.append("STAT_UNAUTHORIZED_EFFECTIVE_THRESHOLD")

    credit = contract.get("credit_contract", {})
    if credit.get("generation_credit_inheritance_forbidden") is not True:
        errors.append("CREDIT_INHERITANCE")
    if credit.get("g5_rr_formal_credit") != 0:
        errors.append("G5_RR_FORMAL_CREDIT")
    if "FRESH_POST_FREEZE_BOUNDARY" not in credit.get("g6_rr_formal_credit_requires", []):
        errors.append("G6_RR_FRESH_REQUIREMENT")

    g9 = generations.get("G9", {})
    if g9.get("pass_x_pass_required") is not True:
        errors.append("G9_PASS_X_PASS")
    if g9.get("all_components_standalone_terminal_pass_required") is not False:
        errors.append("G9_COMPONENT_PASS")
    if g9.get("pass_x_pass_scope") != "ALPHA_PRODUCERS" or g9.get("component_type_gates") != {
        "ALPHA_PRODUCER": "STANDALONE_TERMINAL_ECONOMIC_PASS",
        "TRADE_MODIFIER": "SAME_BASELINE_INCREMENTAL_AB_PASS",
        "RISK_OR_ADVISOR": "NO_NET_EXPECTANCY_DAMAGE_AND_DD_CVAR_ERROR_COST_IMPROVEMENT",
    }:
        errors.append("G9_TYPED_COMPONENT_GATE")
    if g9.get("component_credit_inheritance_forbidden") is not True:
        errors.append("G9_CREDIT_INHERITANCE")

    g14 = generations.get("G14", {})
    if g14.get("terminal_pass_grants_readiness_only") is not True:
        errors.append("G14_READINESS_ONLY")
    if g14.get("order_authority_default") != "BLOCKED" or g14.get("live_authority_default") != "BLOCKED":
        errors.append("G14_DEFAULT_AUTHORITY")
    if g14.get("automatic_live_forbidden") is not True or g14.get("explicit_user_approval_required") is not True:
        errors.append("G14_AUTO_LIVE")

    invariants = contract.get("shared_invariants", {})
    expected_authority = {
        "selection_authority_default": False,
        "promotion_authority_default": False,
        "execution_authority_default": "NONE",
        "order_authority_default": "BLOCKED",
        "live_authority_default": "BLOCKED",
    }
    for key, expected in expected_authority.items():
        if invariants.get(key) != expected:
            errors.append(f"DEFAULT_AUTHORITY_{key}")
    return errors


def validate_lineage(rows: list[dict[str, Any]], contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    lineage = contract.get("experiment_lineage", {})
    schema = lineage.get("schema_version")
    identity_keys = lineage.get("duplicate_identity", [])
    seen: set[tuple[Any, ...]] = set()
    previous_sha: str | None = None

    for idx, row in enumerate(rows):
        if row.get("schema_version") != schema:
            errors.append(f"LINEAGE_SCHEMA:{idx}")
        if row.get("seq") != idx:
            errors.append(f"LINEAGE_SEQ:{idx}")
        if row.get("prev_sha256") != previous_sha:
            errors.append(f"LINEAGE_PREV:{idx}")
        observed = row.get("record_sha256")
        computed = canonical_record_sha256(row)
        if observed != computed:
            errors.append(f"LINEAGE_HASH:{idx}")
        generation = row.get("generation")
        if not isinstance(generation, int) or isinstance(generation, bool) or not 5 <= generation <= 14:
            errors.append(f"LINEAGE_GENERATION:{idx}")
        identity = tuple(row.get(key) for key in identity_keys)
        if None in identity or "" in identity:
            errors.append(f"LINEAGE_IDENTITY_MISSING:{idx}")
        elif identity in seen:
            errors.append(f"LINEAGE_DUPLICATE:{idx}")
        else:
            seen.add(identity)

        if row.get("selection_authority") is not False:
            errors.append(f"LINEAGE_SELECTION_AUTHORITY:{idx}")
        if row.get("promotion_authority") is not False:
            errors.append(f"LINEAGE_PROMOTION_AUTHORITY:{idx}")
        if row.get("execution_authority") != "NONE":
            errors.append(f"LINEAGE_EXECUTION_AUTHORITY:{idx}")
        if row.get("order_authority") != "BLOCKED":
            errors.append(f"LINEAGE_ORDER_AUTHORITY:{idx}")
        if row.get("live_authority") != "BLOCKED":
            errors.append(f"LINEAGE_LIVE_AUTHORITY:{idx}")
        previous_sha = observed if isinstance(observed, str) else None
    return errors


def check_append_only(current_lines: list[str], base_lines: list[str]) -> list[str]:
    current = [line for line in current_lines if line.strip()]
    base = [line for line in base_lines if line.strip()]
    if len(current) < len(base):
        return ["LINEAGE_TRUNCATED"]
    if current[:len(base)] != base:
        return ["LINEAGE_REWRITE"]
    return []


def checkpoint_state(generation: int, closed_t: int, *, explicit_terminal_pass: bool = False) -> str:
    if generation not in RESEARCH_T_GENERATIONS:
        return "STAGE_SPECIFIC_GATE"
    if closed_t < 0:
        return "INVALID_T"
    if explicit_terminal_pass:
        return "TERMINAL_PASS"
    if closed_t < 6:
        return "COLLECT"
    if closed_t < 12:
        return "DIAGNOSTIC_6T_NO_TERMINAL"
    return "QUALIFICATION_12T_NOT_TERMINAL"


def optional_stage_applicability(generation: int, evidence: dict[str, Any] | None) -> dict[str, Any]:
    """Review requirements only: no terminal PASS, generation skip, or authority.

    An absence claim alone is insufficient. Bind the inactive/no-coupling check
    to reviewed code/config and an equal baseline-versus-disabled behaviour hash.
    """
    e = evidence or {}
    hashes = (e.get('code_sha256'), e.get('config_sha256'), e.get('baseline_behaviour_sha256'), e.get('disabled_behaviour_sha256'))
    valid_hashes = all(isinstance(h,str) and len(h)==64 and all(c in '0123456789abcdef' for c in h) for h in hashes)
    excluded = (generation in (7,8,9) and e.get('enabled') is False and e.get('bindings') == []
                and e.get('reviewed') is True and valid_hashes and hashes[2] == hashes[3]
                and all(e.get('safety_checks',{}).get(k) is True for k in ('risk','stop','cost','integrity','explicit_live_approval')))
    return {'state':'NOT_APPLICABLE_DISABLED_UNBOUND_PARITY' if excluded else 'REQUIRED_OR_EVIDENCE_MISSING',
            'implementation_required':not excluded, 'formal_pass':False, 'generation_advance_authorized':False,
            'execution_authority':'NONE', 'order_authority':'BLOCKED', 'live_trade_authority':'BLOCKED'}


def validate_transition(current_generation: int, next_generation: int, current_terminal_pass: bool,
                        *, terminal: dict[str, Any] | None = None, lane_identity: dict[str, Any] | None = None,
                        gate: dict[str, Any] | None = None, reviewed_blob_sha: str | None = None,
                        observed_blob_sha: str | None = None, global_bundle_pass: bool = False) -> list[str]:
    errors: list[str] = []
    if current_generation < 5 or current_generation >= 14:
        errors.append("TRANSITION_CURRENT_RANGE")
    if next_generation != current_generation + 1:
        errors.append("TRANSITION_ORDER")
    if current_terminal_pass is not True:
        errors.append("TRANSITION_WITHOUT_TERMINAL_PASS")
    if current_generation in (5, 6, 7):
        stage = "G5B" if current_generation == 5 else f"G{current_generation}"
        errors.extend(controller.lane_terminal_errors(terminal, lane_identity=lane_identity or {},
                      stage=stage, gate=gate or {}, reviewed_blob_sha=reviewed_blob_sha,
                      observed_blob_sha=observed_blob_sha))
    elif next_generation >= 9 and global_bundle_pass is not True:
        errors.append("GLOBAL_BUNDLE_INTEGRATION_REQUIRED")
    return errors


def validate_credit_claim(claim: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    generation = claim.get("generation")
    axis = str(claim.get("axis", "")).upper()
    formal_credit = claim.get("formal_credit", 0)
    inherited = claim.get("inherited_formal_credit", 0)
    credit = contract.get("credit_contract", {})

    if inherited not in (0, False, None):
        errors.append("GENERATION_CREDIT_INHERITANCE")

    g5_rr_axes = {str(x).upper() for x in credit.get("g5_rr_axes", [])}
    if generation == 5 and axis in g5_rr_axes and formal_credit not in (0, False):
        errors.append("G5_RR_NO_CREDIT_VIOLATION")

    if generation == 6 and axis in g5_rr_axes and formal_credit not in (0, False):
        if claim.get("g5_terminal_pass") is not True:
            errors.append("G6_RR_WITHOUT_G5_TERMINAL")
        if claim.get("candidate_frozen") is not True:
            errors.append("G6_RR_WITHOUT_CANDIDATE_FREEZE")
        if claim.get("fresh_after_freeze_boundary") is not True:
            errors.append("G6_RR_PREBOUNDARY_CREDIT")
        if claim.get("g6_own_qualification") is not True:
            errors.append("G6_RR_WITHOUT_OWN_QUALIFICATION")
        if claim.get("g6_terminal_receipt") is not True:
            errors.append("G6_RR_WITHOUT_TERMINAL_RECEIPT")
    return errors


def validate_g9_bundle(bundle: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    components = bundle.get("components")
    if not isinstance(components, list) or len(components) < 2:
        return ["G9_COMPONENT_COUNT"]
    for component in components:
        if not isinstance(component, dict):
            errors.append("G9_COMPONENT_TYPE_REQUIRED")
            continue
        kind = component.get("component_type")
        if kind == "ALPHA_PRODUCER":
            if component.get("standalone_terminal_pass") is not True or not component.get("terminal_receipt_sha"):
                errors.append("G9_PASS_X_PASS_REQUIRED")
        elif kind in ("TRADE_MODIFIER", "RISK_OR_ADVISOR"):
            proof = component.get("incremental_receipt") or {}
            if (not proof.get("receipt_sha") or not bundle.get("baseline_sha") or
                proof.get("baseline_sha") != bundle["baseline_sha"] or not bundle.get("evaluation_data_sha") or
                proof.get("evaluation_data_sha") != bundle["evaluation_data_sha"]):
                errors.append("G9_INCREMENTAL_BASELINE_OR_DATA_PARITY")
            if kind == "TRADE_MODIFIER" and proof.get("incremental_ab_pass") is not True:
                errors.append("G9_MODIFIER_INCREMENTAL_AB_REQUIRED")
            if kind == "RISK_OR_ADVISOR":
                if proof.get("net_expectancy_not_worse") is not True or not any(proof.get(k) is True for k in ("dd_improved", "cvar_improved", "error_cost_improved")):
                    errors.append("G9_RISK_INCREMENTAL_PASS_REQUIRED")
        else:
            errors.append("G9_COMPONENT_TYPE_REQUIRED")
    if bundle.get("fresh_interaction_boundary") is not True:
        errors.append("G9_FRESH_BOUNDARY")
    if bundle.get("component_formal_credit_inherited", 0) not in (0, False):
        errors.append("G9_COMPONENT_CREDIT_INHERITANCE")
    return errors


def validate_g14_readiness(receipt: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if receipt.get("order_authority", "BLOCKED") != "BLOCKED":
        errors.append("G14_ORDER_AUTHORITY_MUST_REMAIN_BLOCKED")
    if receipt.get("live_authority", "BLOCKED") != "BLOCKED":
        errors.append("G14_LIVE_AUTHORITY_MUST_REMAIN_BLOCKED")
    if receipt.get("automatic_live", False) is not False:
        errors.append("G14_AUTOMATIC_LIVE_FORBIDDEN")
    if receipt.get("controller_created_order_authority", False) is not False:
        errors.append("G14_CONTROLLER_ORDER_AUTHORITY_FORBIDDEN")
    return errors


def read_git_file(ref: str, path: Path) -> list[str] | None:
    rel = path.relative_to(ROOT).as_posix()
    proc = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=ROOT, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.splitlines()


def derive(*, base_ref: str | None = None, root: Path = ROOT) -> dict[str, Any]:
    rebuild = root / "backend" / "research" / "rebuild"
    contract_path = rebuild / "g5_g14_governance_contract_v1.json"
    lineage_path = rebuild / "g5_g14_experiment_lineage_v1.jsonl"
    try:
        contract = load_json(contract_path)
        rows = load_jsonl(lineage_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"schema_version": "zel.g5_g14.governance_validation_receipt.v1", "state": "HARD_FAIL_PARSE", "errors": [str(exc)], "generation_range": [5, 14], "formal_credit_granted": False, "order_authority": "BLOCKED", "live_authority": "BLOCKED"}

    errors = validate_contract(contract)
    roadmap = load_json(root / "backend/research/contracts/g5a_g5b_lane_local_profit_roadmap_v1.json")
    shared = load_json(rebuild / "g5_g14_shared_validation_contract_v1.json")
    if shared.get("lane_progression") != contract.get("lane_progression"):
        errors.append("SHARED_LANE_CONTRACT_PARITY")
    if any(roadmap.get("progression_model", {}).get(k) != v for k, v in contract.get("lane_progression", {}).items()):
        errors.append("ROADMAP_LANE_CONTRACT_PARITY")
    if roadmap.get("g5b_edge_qualification", {}).get("checkpoints", {}).get("T12") != "PROVISIONAL_QUALIFICATION":
        errors.append("ROADMAP_T12_NOT_TERMINAL")
    errors.extend(validate_lineage(rows, contract))
    append_only_checked = False
    if base_ref:
        base_lines = read_git_file(base_ref, lineage_path)
        if base_lines is not None:
            append_only_checked = True
            errors.extend(check_append_only(lineage_path.read_text(encoding="utf-8").splitlines(), base_lines))

    receipt = {
        "schema_version": "zel.g5_g14.governance_validation_receipt.v1",
        "state": "PASS_G5_G14_GOVERNANCE_LOCK" if not errors else "HARD_FAIL_G5_G14_GOVERNANCE",
        "errors": errors,
        "generation_range": [5, 14],
        "generation_count": 10,
        "lineage_records": len(rows),
        "append_only_checked_against_base": append_only_checked,
        "diagnostic_checkpoint_t": contract.get("statistics_contract", {}).get("diagnostic_checkpoint_t"),
        "qualification_checkpoint_t": contract.get("statistics_contract", {}).get("qualification_checkpoint_t"),
        "qualification_is_terminal": contract.get("statistics_contract", {}).get("qualification_checkpoint_is_terminal"),
        "g5_responsibility": contract.get("generation_contract", {}).get("G5", {}).get("responsibility"),
        "g5_rr_formal_credit": contract.get("credit_contract", {}).get("g5_rr_formal_credit"),
        "g6_responsibility": contract.get("generation_contract", {}).get("G6", {}).get("responsibility"),
        "g9_pass_x_pass_required": contract.get("generation_contract", {}).get("G9", {}).get("pass_x_pass_required"),
        "g14_auto_live_forbidden": contract.get("generation_contract", {}).get("G14", {}).get("automatic_live_forbidden"),
        "formal_credit_granted": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED", "exchange_order_submitted": False,
        "lane_scoped_unlock": not any("LANE" in e for e in errors),
        "effective_development_objective": contract.get("effective_development_objective"),
        "g6_owned_operations": contract.get("generation_contract", {}).get("G6", {}).get("owned_operations"),
        "g7_owned_operations": contract.get("generation_contract", {}).get("G7", {}).get("owned_operations"),
        "g9_component_type_gates": contract.get("generation_contract", {}).get("G9", {}).get("component_type_gates"),
        "source_files_sha256": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in [
            contract_path, rebuild / "g5_g14_shared_validation_contract_v1.json",
            root / "backend/research/contracts/g5a_g5b_lane_local_profit_roadmap_v1.json",
            rebuild / "g5_g14_generation_controller_v1.py", rebuild / "g5_g14_governance_validator_v1.py", lineage_path]},
    }
    receipt["receipt_sha256"] = hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    receipt = derive(base_ref=args.base_ref)
    text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.write:
        OUT.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if receipt["state"] == "PASS_G5_G14_GOVERNANCE_LOCK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
