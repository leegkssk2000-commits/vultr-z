from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class LaneTemplate:
    projection_epoch_id: str
    exact25_manifest_sha256: str
    strategy_id: str
    exit_policy_id: str
    lane_template_id: str
    state_namespace: str
    cooldown_namespace: str
    skill_set: tuple[str, ...]
    target_r: float | None
    loss_cap_r: float | None
    planned_loss_r: float
    cost_model_ref: str
    observer_only: bool
    runtime_binding_allowed: bool
    execution_authority: str
    order_authority: str


@dataclass(frozen=True)
class ProjectionManifest:
    state: str
    reason_codes: tuple[str, ...]
    projection_epoch_id: str
    exact25_manifest_sha256: str
    strategy_count: int
    exit_policy_count: int
    lane_template_count: int
    projection_sha256: str
    templates: tuple[LaneTemplate, ...]
    runtime_active: bool
    source_event_subscription_allowed: bool
    formal_ledger_write_allowed: bool
    execution_authority: str
    order_authority: str

    def as_payload(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "reason_codes": list(self.reason_codes),
            "projection_epoch_id": self.projection_epoch_id,
            "exact25_manifest_sha256": self.exact25_manifest_sha256,
            "strategy_count": self.strategy_count,
            "exit_policy_count": self.exit_policy_count,
            "lane_template_count": self.lane_template_count,
            "projection_sha256": self.projection_sha256,
            "templates": [asdict(row) | {"skill_set": list(row.skill_set)} for row in self.templates],
            "runtime_active": self.runtime_active,
            "source_event_subscription_allowed": self.source_event_subscription_allowed,
            "formal_ledger_write_allowed": self.formal_ledger_write_allowed,
            "execution_authority": self.execution_authority,
            "order_authority": self.order_authority,
        }


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _template_id(manifest_sha256: str, strategy_id: str, exit_policy_id: str) -> str:
    return "r72.template." + hashlib.sha256(
        f"{manifest_sha256}|{strategy_id}|{exit_policy_id}".encode("utf-8")
    ).hexdigest()


def validate_projection_contract(contract: Mapping[str, Any]) -> tuple[str, ...]:
    errors: list[str] = []
    authority = contract.get("authority", {})
    dependencies = contract.get("dependencies", {})
    rules = contract.get("projection_rules", {})
    gates = contract.get("gates", {})
    if contract.get("schema") != "zos_exact25_raw_100_lane_projection_v1":
        errors.append("PROJECTION_CONTRACT_SCHEMA_INVALID")
    if contract.get("official_stage") != "R7.2":
        errors.append("PROJECTION_CONTRACT_STAGE_INVALID")
    if authority.get("observer_only") is not True:
        errors.append("OBSERVER_ONLY_REQUIRED")
    for key in (
        "runtime_binding_allowed",
        "source_event_subscription_allowed",
        "projection_state_write_allowed",
        "producer_mutation_allowed",
        "writer_mutation_allowed",
        "formal_ledger_mutation_allowed",
        "strategy_mutation_allowed",
        "skill_registry_mutation_allowed",
        "historical_backfill_allowed",
        "provider_invocation_enabled",
        "network_call_enabled",
        "paper_enabled",
        "live_enabled",
        "order_enabled",
        "automatic_promotion_enabled",
    ):
        if authority.get(key) is not False:
            errors.append(f"AUTHORITY_FLAG_INVALID:{key}")
    if authority.get("order_authority") != "blocked":
        errors.append("ORDER_AUTHORITY_INVALID")
    if authority.get("execution_authority") != "none":
        errors.append("EXECUTION_AUTHORITY_INVALID")
    if dependencies.get("exact_strategy_count") != 25:
        errors.append("EXACT25_COUNT_INVALID")
    if dependencies.get("exit_policy_count") != 4:
        errors.append("EXIT_POLICY_COUNT_INVALID")
    if dependencies.get("lane_template_count") != 100:
        errors.append("LANE_TEMPLATE_COUNT_INVALID")
    if dependencies.get("raw_skill_set_required") != []:
        errors.append("RAW_SKILL_SET_MUST_BE_EMPTY")
    if dependencies.get("r64_external_canary_required") is not False:
        errors.append("R64_DEPENDENCY_MUST_BE_FALSE")
    for key in (
        "one_template_per_strategy_exit_pair",
        "templates_are_not_positions",
        "sparse_event_driven_instantiation_required",
        "instantiate_only_after_canonical_source_entry",
        "same_source_entry_across_four_exit_lanes",
        "same_market_path_across_four_exit_lanes",
        "same_fee_slippage_funding_model_across_four_exit_lanes",
        "independent_lane_position_id_required",
        "independent_state_namespace_required",
        "independent_cooldown_namespace_required",
        "cross_lane_state_sharing_forbidden",
        "cross_lane_next_entry_mutation_forbidden",
        "native_exit_is_immutable_control",
    ):
        if rules.get(key) is not True:
            errors.append(f"PROJECTION_RULE_INVALID:{key}")
    if rules.get("fixed_exit_planned_loss_cap_r") != 0.75:
        errors.append("FIXED_EXIT_RISK_CAP_INVALID")
    if gates.get("template_count") != 100 or gates.get("runtime_active") is not False:
        errors.append("PROJECTION_GATE_INVALID")
    return tuple(sorted(set(errors)))


def build_projection_manifest(
    strategy_ids: Sequence[str],
    exact25_manifest_sha256: str,
    matrix_contract: Mapping[str, Any],
    r71_status: Mapping[str, Any],
    projection_contract: Mapping[str, Any],
    *,
    projection_epoch_id: str = "q4.shadow.r72.raw100.template.v1",
    cost_model_ref: str = "q4r3.shared.execution_cost_model.v1",
) -> ProjectionManifest:
    reasons = list(validate_projection_contract(projection_contract))
    if r71_status.get("state") != "PASS" or r71_status.get("blockers"):
        reasons.append("R71_PASS_NOT_PROVEN")
    report = r71_status.get("report", {})
    if report.get("strategy_count") != 25 or report.get("raw_baseline_lane_count") != 100:
        reasons.append("R71_MATRIX_COUNTS_INVALID")
    if len(strategy_ids) != 25 or len(set(strategy_ids)) != 25:
        reasons.append("UNIQUE_EXACT25_NOT_PROVEN")
    if len(exact25_manifest_sha256) != 64:
        reasons.append("EXACT25_MANIFEST_DIGEST_INVALID")
    exits = matrix_contract.get("exit_policy_lanes", [])
    exit_ids = [str(row.get("exit_policy_id")) for row in exits if isinstance(row, Mapping)]
    if len(exit_ids) != 4 or len(set(exit_ids)) != 4:
        reasons.append("MATRIX_EXIT_POLICY_SET_INVALID")
    if not projection_epoch_id or not cost_model_ref:
        reasons.append("PROJECTION_IDENTITY_INVALID")

    templates: list[LaneTemplate] = []
    if not reasons:
        for strategy_id in sorted(strategy_ids):
            for row in exits:
                exit_policy_id = str(row["exit_policy_id"])
                lane_template_id = _template_id(exact25_manifest_sha256, strategy_id, exit_policy_id)
                loss_cap = row.get("loss_cap_r")
                planned_loss = abs(float(loss_cap)) if loss_cap is not None else 0.0
                templates.append(
                    LaneTemplate(
                        projection_epoch_id=projection_epoch_id,
                        exact25_manifest_sha256="sha256:" + exact25_manifest_sha256,
                        strategy_id=strategy_id,
                        exit_policy_id=exit_policy_id,
                        lane_template_id=lane_template_id,
                        state_namespace=lane_template_id + ".state",
                        cooldown_namespace=lane_template_id + ".cooldown",
                        skill_set=(),
                        target_r=float(row["target_r"]) if row.get("target_r") is not None else None,
                        loss_cap_r=float(loss_cap) if loss_cap is not None else None,
                        planned_loss_r=planned_loss,
                        cost_model_ref=cost_model_ref,
                        observer_only=True,
                        runtime_binding_allowed=False,
                        execution_authority="none",
                        order_authority="blocked",
                    )
                )

    template_ids = [row.lane_template_id for row in templates]
    states = [row.state_namespace for row in templates]
    cooldowns = [row.cooldown_namespace for row in templates]
    pairs = [(row.strategy_id, row.exit_policy_id) for row in templates]
    if templates and len(templates) != 100:
        reasons.append("RAW_100_TEMPLATE_COUNT_INVALID")
    if len(template_ids) != len(set(template_ids)):
        reasons.append("DUPLICATE_TEMPLATE_ID")
    if len(states) != len(set(states)):
        reasons.append("STATE_NAMESPACE_COLLISION")
    if len(cooldowns) != len(set(cooldowns)):
        reasons.append("COOLDOWN_NAMESPACE_COLLISION")
    if len(pairs) != len(set(pairs)):
        reasons.append("DUPLICATE_STRATEGY_EXIT_PAIR")
    if any(row.skill_set for row in templates):
        reasons.append("RAW_SKILL_CONTAMINATION")
    by_strategy = {strategy_id: 0 for strategy_id in strategy_ids}
    for row in templates:
        by_strategy[row.strategy_id] = by_strategy.get(row.strategy_id, 0) + 1
    if templates and set(by_strategy.values()) != {4}:
        reasons.append("FOUR_EXIT_COVERAGE_PER_STRATEGY_INVALID")

    canonical_templates = [asdict(row) | {"skill_set": list(row.skill_set)} for row in templates]
    projection_sha256 = _digest(canonical_templates) if templates else ""
    state = "PROJECTION_READY" if not reasons else "HOLD"
    return ProjectionManifest(
        state=state,
        reason_codes=("RAW_100_LANE_PROJECTION_READY",) if not reasons else tuple(sorted(set(reasons))),
        projection_epoch_id=projection_epoch_id,
        exact25_manifest_sha256="sha256:" + exact25_manifest_sha256 if len(exact25_manifest_sha256) == 64 else "",
        strategy_count=len(set(strategy_ids)),
        exit_policy_count=len(set(exit_ids)),
        lane_template_count=len(templates),
        projection_sha256=projection_sha256,
        templates=tuple(templates),
        runtime_active=False,
        source_event_subscription_allowed=False,
        formal_ledger_write_allowed=False,
        execution_authority="none",
        order_authority="blocked",
    )
