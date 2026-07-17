from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

CONTRACT_OWNER = "backend/contracts/ZOS_EXACT25_SKILL_ADJUSTED_SHADOW_MATRIX_v1.json"
OBSERVER_ONLY = True
RUNTIME_BINDING_ALLOWED = False
FORMAL_LEDGER_WRITE_ALLOWED = False
ORDER_AUTHORITY = "blocked"
EXECUTION_AUTHORITY = "none"


class MatrixContractError(ValueError):
    pass


@dataclass(frozen=True)
class SourceEntry:
    matrix_epoch_id: str
    source_position_id: str
    source_entry_event_id: str
    strategy_id: str
    strategy_source_sha256: str
    method_id: str
    symbol: str
    side: str
    entry_ts: int
    entry_price: float
    market_path_id: str


@dataclass(frozen=True)
class MatrixLane:
    lane_position_id: str
    source_position_id: str
    source_entry_event_id: str
    strategy_id: str
    method_id: str
    exit_policy_id: str
    target_r: float | None
    loss_cap_r: float | None
    skill_set: tuple[str, ...]
    skill_set_hash: str
    planned_loss_r: float
    observer_only: bool
    execution_authority: str
    order_authority: str


@dataclass(frozen=True)
class MatrixPlan:
    state: str
    reason_codes: tuple[str, ...]
    strategy_count: int
    exit_policy_count: int
    lane_count: int
    lanes: tuple[MatrixLane, ...]
    runtime_binding_allowed: bool
    formal_ledger_write_allowed: bool
    execution_authority: str
    order_authority: str


def _canonical_hash(values: Sequence[str]) -> str:
    raw = json.dumps(sorted(values), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _lane_id(entry: SourceEntry, exit_policy_id: str, skill_set_hash: str) -> str:
    raw = "|".join(
        (
            entry.matrix_epoch_id,
            entry.source_position_id,
            entry.source_entry_event_id,
            entry.strategy_id,
            entry.method_id,
            exit_policy_id,
            skill_set_hash,
        )
    ).encode("utf-8")
    return "matrix." + hashlib.sha256(raw).hexdigest()


def _require(condition: bool, code: str, errors: list[str]) -> None:
    if not condition:
        errors.append(code)


def validate_contract(contract: Mapping[str, Any], registry: Mapping[str, Any]) -> tuple[str, ...]:
    errors: list[str] = []
    authority = contract.get("authority", {})
    dependency = contract.get("dependency_contract", {})
    matrix_rules = contract.get("matrix_rules", {})
    risk = contract.get("risk_budget_contract", {})
    partitions = contract.get("skill_partitions", {})
    exits = contract.get("exit_policy_lanes", [])
    skills = registry.get("skills", [])

    _require(contract.get("schema") == "zos_exact25_skill_adjusted_shadow_matrix_v1", "CONTRACT_SCHEMA_INVALID", errors)
    _require(contract.get("official_stage") == "R7.1", "CONTRACT_STAGE_INVALID", errors)
    _require(authority.get("observer_only") is True, "OBSERVER_ONLY_REQUIRED", errors)
    for key in (
        "runtime_binding_allowed",
        "strategy_mutation_allowed",
        "skill_registry_mutation_allowed",
        "producer_mutation_allowed",
        "writer_mutation_allowed",
        "formal_ledger_mutation_allowed",
        "historical_backfill_allowed",
        "paper_enabled",
        "live_enabled",
        "order_enabled",
        "provider_invocation_enabled",
        "same_epoch_auto_promotion",
    ):
        _require(authority.get(key) is False, f"AUTHORITY_FLAG_INVALID:{key}", errors)
    _require(authority.get("order_authority") == "blocked", "ORDER_AUTHORITY_INVALID", errors)
    _require(authority.get("execution_authority") == "none", "EXECUTION_AUTHORITY_INVALID", errors)
    _require(dependency.get("exact_strategy_count") == 25, "EXACT25_COUNT_INVALID", errors)
    _require(dependency.get("method_profile_count") == 6, "METHOD_COUNT_INVALID", errors)
    _require(dependency.get("skill_count") == 18, "SKILL_COUNT_INVALID", errors)
    _require(dependency.get("r64_external_canary_required_for_shadow_matrix") is False, "R64_DEPENDENCY_MUST_BE_FALSE", errors)
    _require(dependency.get("failure_learning_or_ml_light_allowed") is False, "ML_LIGHT_MUST_REMAIN_DISABLED", errors)

    exit_ids = [str(row.get("exit_policy_id")) for row in exits if isinstance(row, Mapping)]
    _require(len(exit_ids) == 4 and len(set(exit_ids)) == 4, "EXIT_POLICY_COUNT_INVALID", errors)
    _require(set(exit_ids) == {"EXIT_NATIVE", "EXIT_FIXED_1P5_L0P75", "EXIT_FIXED_2P0_L0P75", "EXIT_FIXED_2P5_L0P75"}, "EXIT_POLICY_SET_INVALID", errors)
    fixed = {str(row.get("exit_policy_id")): row for row in exits if isinstance(row, Mapping)}
    for key, target in (("EXIT_FIXED_1P5_L0P75", 1.5), ("EXIT_FIXED_2P0_L0P75", 2.0), ("EXIT_FIXED_2P5_L0P75", 2.5)):
        row = fixed.get(key, {})
        _require(row.get("target_r") == target, f"TARGET_R_INVALID:{key}", errors)
        _require(row.get("loss_cap_r") == -0.75, f"LOSS_CAP_INVALID:{key}", errors)

    registry_ids = {
        str(row.get("skill_id"))
        for row in skills
        if isinstance(row, Mapping) and row.get("skill_id")
    }
    entry = set(map(str, partitions.get("entry_ablation_skills", [])))
    management = set(map(str, partitions.get("single_skill_management_candidates", [])))
    guards = set(map(str, partitions.get("mandatory_guardrail_skills", [])))
    _require(len(entry) == 2, "ENTRY_SKILL_PARTITION_INVALID", errors)
    _require(len(management) == 12, "MANAGEMENT_SKILL_PARTITION_INVALID", errors)
    _require(len(guards) == 4, "GUARDRAIL_SKILL_PARTITION_INVALID", errors)
    _require(not (entry & management or entry & guards or management & guards), "SKILL_PARTITIONS_OVERLAP", errors)
    _require(entry | management | guards == registry_ids, "SKILL_PARTITIONS_DO_NOT_COVER_REGISTRY", errors)

    _require(matrix_rules.get("single_skill_ablation_before_combinations") is True, "SINGLE_SKILL_ABLATION_REQUIRED", errors)
    _require(matrix_rules.get("maximum_candidate_skills_per_combination") == 2, "MAX_SKILL_COMBINATION_INVALID", errors)
    _require(matrix_rules.get("lane_state_sharing_forbidden") is True, "LANE_STATE_ISOLATION_REQUIRED", errors)
    _require(matrix_rules.get("cross_lane_cooldown_sharing_forbidden") is True, "CROSS_LANE_COOLDOWN_FORBIDDEN", errors)
    _require(matrix_rules.get("no_full_25x6x18_preinstantiation") is True, "SPARSE_MATRIX_REQUIRED", errors)
    _require(risk.get("research_total_planned_loss_cap_r") == 0.75, "RESEARCH_RISK_CAP_INVALID", errors)
    _require(risk.get("all_legs_included_in_loss_cap") is True, "ALL_LEGS_RISK_REQUIRED", errors)
    _require(risk.get("single_skill_ablation_max_add_count") == 1, "SINGLE_ABLATION_ADD_COUNT_INVALID", errors)
    _require(risk.get("loss_direction_adds_mutually_exclusive") is True, "LOSS_ADD_EXCLUSIVITY_REQUIRED", errors)
    return tuple(sorted(set(errors)))


def validate_skill_set(skill_set: Iterable[str], contract: Mapping[str, Any]) -> tuple[str, ...]:
    values = tuple(sorted(set(map(str, skill_set))))
    reasons: list[str] = []
    partitions = contract["skill_partitions"]
    management = set(partitions["single_skill_management_candidates"])
    loss_adds = {"SK_ADD_DCA", "SK_ADD_AVG_DOWN", "SK_ADD_WATER_ADD"}
    profit_adds = {"SK_ADD_PYRAMIDING", "SK_ADD_PROFITABLE_SCALE_IN"}
    max_count = int(contract["matrix_rules"]["maximum_candidate_skills_per_combination"])
    if len(values) > max_count:
        reasons.append("SKILL_COMBINATION_TOO_LARGE")
    if not set(values).issubset(management):
        reasons.append("SKILL_NOT_MANAGEMENT_CANDIDATE")
    if len(set(values) & loss_adds) > 1:
        reasons.append("LOSS_DIRECTION_ADDS_MUTUALLY_EXCLUSIVE")
    if set(values) & loss_adds and set(values) & profit_adds:
        reasons.append("LOSS_AND_PROFIT_ADD_COMBINATION_FORBIDDEN")
    return tuple(sorted(set(reasons)))


def build_raw_baseline_plan(
    entries: Sequence[SourceEntry],
    contract: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> MatrixPlan:
    reasons = list(validate_contract(contract, registry))
    if len(entries) != 25:
        reasons.append("SOURCE_ENTRY_COUNT_NOT_25")
    strategy_ids = [entry.strategy_id for entry in entries]
    if len(strategy_ids) != len(set(strategy_ids)):
        reasons.append("DUPLICATE_STRATEGY_ENTRY")
    for entry in entries:
        if not entry.matrix_epoch_id or not entry.source_position_id or not entry.source_entry_event_id:
            reasons.append("SOURCE_ENTRY_IDENTITY_MISSING")
        if entry.entry_ts < 0 or entry.entry_price <= 0:
            reasons.append("SOURCE_ENTRY_VALUE_INVALID")
        if not entry.strategy_source_sha256.startswith("sha256:"):
            reasons.append("STRATEGY_SOURCE_DIGEST_INVALID")
        if entry.side not in {"long", "short"}:
            reasons.append("SOURCE_SIDE_INVALID")

    lanes: list[MatrixLane] = []
    empty_hash = _canonical_hash(())
    if not reasons:
        for entry in entries:
            for policy in contract["exit_policy_lanes"]:
                exit_policy_id = str(policy["exit_policy_id"])
                loss_cap = policy.get("loss_cap_r")
                planned_loss = abs(float(loss_cap)) if loss_cap is not None else 0.0
                lanes.append(
                    MatrixLane(
                        lane_position_id=_lane_id(entry, exit_policy_id, empty_hash),
                        source_position_id=entry.source_position_id,
                        source_entry_event_id=entry.source_entry_event_id,
                        strategy_id=entry.strategy_id,
                        method_id=entry.method_id,
                        exit_policy_id=exit_policy_id,
                        target_r=float(policy["target_r"]) if policy.get("target_r") is not None else None,
                        loss_cap_r=float(loss_cap) if loss_cap is not None else None,
                        skill_set=(),
                        skill_set_hash=empty_hash,
                        planned_loss_r=planned_loss,
                        observer_only=True,
                        execution_authority="none",
                        order_authority="blocked",
                    )
                )
    lane_ids = [lane.lane_position_id for lane in lanes]
    if len(lane_ids) != len(set(lane_ids)):
        reasons.append("DUPLICATE_LANE_POSITION_ID")
    if lanes and len(lanes) != 100:
        reasons.append("RAW_BASELINE_LANE_COUNT_NOT_100")
    state = "PLAN_READY" if not reasons else "HOLD"
    return MatrixPlan(
        state=state,
        reason_codes=tuple(sorted(set(reasons))) if reasons else ("RAW_100_LANE_MATRIX_READY",),
        strategy_count=len(set(strategy_ids)),
        exit_policy_count=len(contract.get("exit_policy_lanes", [])),
        lane_count=len(lanes),
        lanes=tuple(lanes),
        runtime_binding_allowed=False,
        formal_ledger_write_allowed=False,
        execution_authority="none",
        order_authority="blocked",
    )


def validate_planned_loss(planned_loss_r: float, contract: Mapping[str, Any]) -> tuple[str, ...]:
    cap = float(contract["risk_budget_contract"]["research_total_planned_loss_cap_r"])
    if planned_loss_r < 0:
        return ("PLANNED_LOSS_R_NEGATIVE",)
    if planned_loss_r > cap:
        return ("AGGREGATE_PLANNED_LOSS_CAP_EXCEEDED",)
    return ()
