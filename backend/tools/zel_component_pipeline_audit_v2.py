from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_COMPONENT_PIPELINE_AUDIT_V2_5"
SAFE = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}
ROLES = {"LBot", "MBot", "OBot", "SBot"}
TEAMS = {"AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"}
ADVISORS = {"ZBOT", "ZICO", "LICO", "ZLICE"}
OBSERVER_ONLY = {"SK_ENTRY_SHORT_BEAM", "SK_ADD_DCA", "SK_ADD_AVG_DOWN", "SK_ADD_WATER_ADD"}
CLAIM_TIERS = {"LOW_SAMPLE", "HYPOTHESIS_ONLY", "COMPONENT_EFFICACY", "INTEGRATED_S_GRADE_SAMPLE"}


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def finding(code: str, severity: str, detail: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "detail": detail}


def audit(
    policy: Mapping[str, Any],
    result: Mapping[str, Any],
    core_path: Path,
    runner_path: Path,
    gemini_path: Path,
    role_path: Path,
    workflow_path: Path,
    diagnostic_path: Path,
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    core_text = core_path.read_text(encoding="utf-8")
    runner_text = runner_path.read_text(encoding="utf-8")
    gemini_text = gemini_path.read_text(encoding="utf-8")
    role_text = role_path.read_text(encoding="utf-8")
    workflow_text = workflow_path.read_text(encoding="utf-8")
    for text in (core_text, runner_text, gemini_text, role_text):
        ast.parse(text)

    for key, expected in SAFE.items():
        if result.get(key) != expected:
            findings.append(finding("RESULT_SAFETY_MISMATCH", "CRITICAL", f"{key}={result.get(key)!r}"))
        if (policy.get("safety") or {}).get(key) != expected:
            findings.append(finding("POLICY_SAFETY_MISMATCH", "CRITICAL", f"{key}={(policy.get('safety') or {}).get(key)!r}"))

    modules = result.get("module_results") or {}
    best_by_role = (modules.get("bots") or {}).get("best_by_role") or {}
    if set(best_by_role) != ROLES:
        findings.append(finding("BOT_ROLE_PROFILE_SET_MISMATCH", "CRITICAL", str(sorted(best_by_role))))
    if 'for watcher in team.get("watchers", [])' not in core_text:
        findings.append(finding("TEAM_WATCHERS_NOT_FULLY_EVALUATED", "CRITICAL", "watcher iteration missing"))
    if set((policy.get("team_search") or {}).get("teams", {})) != TEAMS:
        findings.append(finding("TEAM_SET_MISMATCH", "CRITICAL", str(sorted((policy.get('team_search') or {}).get('teams', {})))))

    skill = (modules.get("skills") or {}).get("best") or {}
    if skill.get("skill_id") in OBSERVER_ONLY or skill.get("selection_eligible") is False:
        findings.append(finding("OBSERVER_ONLY_SKILL_SELECTED", "CRITICAL", str(skill.get("skill_id"))))
    if "EXACT_LEDGER_SUBSET_LONG_BEAM_ONLY" not in core_text:
        findings.append(finding("LONG_BEAM_DIRECTION_NOT_EXPLICIT", "HIGH", "LongBeam subset contract missing"))
    if "OBSERVER_ONLY_NO_SHORT_LEDGER" not in core_text:
        findings.append(finding("SHORT_BEAM_NOT_OBSERVER_ONLY", "CRITICAL", "ShortBeam observer contract missing"))

    advisors = modules.get("advisors") or {}
    if set(advisors) != ADVISORS:
        findings.append(finding("ADVISOR_ROLE_SET_MISMATCH", "CRITICAL", str(sorted(advisors))))
    if "ZLICE_FULL_STACK_LINEAGE_FAILURE" not in runner_text or "PASS_LINEAGE_VALIDATION_NO_ECONOMIC_MUTATION" not in runner_text:
        findings.append(finding("ZLICE_NOT_BOUND_AS_LINEAGE_VALIDATOR", "HIGH", "Zlice validation path incomplete"))
    for token in ("PRIVATE_AUTHORITY_ACTION_FORBIDDEN", "SBOT_VETO_PRECEDENCE", "cross_role_substitution_forbidden"):
        if token not in role_text:
            findings.append(finding("ROLE_BOUNDARY_GUARD_MISSING", "CRITICAL", token))

    decisions = result.get("pipeline_decisions") or {}
    marginal = (result.get("component_attribution") or {}).get("ordered_marginal_delta_net") or {}
    for stage, decision in decisions.items():
        if stage == "ZLICE":
            continue
        if decision.get("applied") is True:
            if (decision.get("evidence") or {}).get("material") is not True:
                findings.append(finding("NON_MATERIAL_STAGE_APPLIED", "CRITICAL", stage))
            if float(marginal.get(stage, 0.0)) < -1e-12:
                findings.append(finding("NEGATIVE_MARGINAL_STAGE_APPLIED", "CRITICAL", stage))
    attribution = result.get("component_attribution") or {}
    if attribution.get("method") != "SEQUENTIAL_MATERIAL_ONLY_EXACT_SUM":
        findings.append(finding("ATTRIBUTION_METHOD_INVALID", "HIGH", str(attribution.get("method"))))
    residual = float(attribution.get("interaction_residual", 0.0))
    if abs(residual) > 1e-9:
        findings.append(finding("ATTRIBUTION_RESIDUAL_NONZERO", "HIGH", str(residual)))

    low_sample = bool((result.get("convergence") or {}).get("low_sample_hold"))
    if low_sample and result.get("state") != "LOW_SAMPLE_HOLD":
        findings.append(finding("LOW_SAMPLE_STATE_NOT_HOLD", "CRITICAL", str(result.get("state"))))
    eligibility = result.get("axis_review_eligibility") or {}
    if low_sample and any(bool(value) for value in eligibility.values()):
        findings.append(finding("LOW_SAMPLE_AXIS_AI_LEAK", "CRITICAL", str(eligibility)))
    for axis, active in eligibility.items():
        if active and axis not in {"BOT_POLICY", "TEAM_POLICY", "SKILL_PROFILE", "ADVISOR_PROFILE"}:
            findings.append(finding("UNKNOWN_AI_AXIS", "HIGH", axis))

    is_v3 = str(result.get("schema_version") or "").startswith("3") or "claim_gate" in result
    claim_gate = result.get("claim_gate") or {}
    claim_tier = claim_gate.get("claim_tier")
    performance_claim_allowed = bool(result.get("performance_claim_allowed", claim_gate.get("performance_claim_allowed", False)))
    exact_skill_replay_required = bool(claim_gate.get("exact_skill_replay_required"))
    interaction = claim_gate.get("interaction_audit") or {}
    statistics = claim_gate.get("statistical_gate") or {}
    if is_v3:
        if not claim_gate:
            findings.append(finding("V3_CLAIM_GATE_MISSING", "CRITICAL", "claim_gate missing"))
        if claim_tier not in CLAIM_TIERS:
            findings.append(finding("V3_CLAIM_TIER_INVALID", "CRITICAL", str(claim_tier)))
        if claim_tier in {"LOW_SAMPLE", "HYPOTHESIS_ONLY"} and performance_claim_allowed:
            findings.append(finding("V3_PREMATURE_PERFORMANCE_CLAIM", "CRITICAL", str(claim_tier)))
        if exact_skill_replay_required and performance_claim_allowed:
            findings.append(finding("V3_SYNTHETIC_SKILL_CLAIM_LEAK", "CRITICAL", "exact replay still required"))
        if claim_tier in {"COMPONENT_EFFICACY", "INTEGRATED_S_GRADE_SAMPLE"}:
            if interaction.get("order_stable") is False and result.get("state") != "HOLD_COMPONENT_INTERACTION_UNSTABLE":
                findings.append(finding("V3_INTERACTION_HOLD_NOT_ENFORCED", "CRITICAL", str(result.get("state"))))
            if interaction.get("order_stable") is True and exact_skill_replay_required and result.get("state") != "HOLD_EXACT_SKILL_REPLAY_REQUIRED":
                findings.append(finding("V3_EXACT_SKILL_REPLAY_HOLD_NOT_ENFORCED", "CRITICAL", str(result.get("state"))))
            if interaction.get("order_stable") is True and not exact_skill_replay_required and statistics.get("pass") is False and result.get("state") != "HOLD_STATISTICAL_GATE":
                findings.append(finding("V3_STATISTICAL_HOLD_NOT_ENFORCED", "CRITICAL", str(result.get("state"))))
        if result.get("shadow_start_allowed") is not False or result.get("paper_allowed") is not False or result.get("live_allowed") is not False:
            findings.append(finding("V3_EXECUTION_SURFACE_LEAK", "CRITICAL", "shadow/paper/live must remain false"))

    per_axis_bindings = (
        "axis-ai-gate:" in workflow_text
        and "Required material per-axis Groq and Workers AI review" in workflow_text
        and "active_axis_count != '0'" in workflow_text
        and "strategy11_groq_redteam.py" in workflow_text
        and "strategy11_workers_ai_guard.py" in workflow_text
        and ("PASS_COMPONENT_AXIS_AI_GATE_V2" in workflow_text or "PASS_COMPONENT_AXIS_AI_GATE_V3" in workflow_text)
    )
    if not per_axis_bindings:
        findings.append(finding("PER_AXIS_AI_GATE_NOT_BOUND", "CRITICAL", "material single-axis Groq/Workers workflow binding missing"))
    if "GEMINI_API_KEY" not in workflow_text or "zel_component_gemini_v2.py" not in workflow_text:
        findings.append(finding("GEMINI_DIRECT_VIDEO_NOT_EXECUTED", "CRITICAL", "actual Gemini execution missing"))
    gemini_router_fields = all(
        token in gemini_text
        for token in ("call_direct_video", "public_urls", "independent_channels", "run_id", "input_sha", "prompt_sha", "response_sha")
    ) and "strategy11_ai_review_router.py" in workflow_text
    if not gemini_router_fields:
        findings.append(finding("GEMINI_ROUTER_ARTIFACT_SCHEMA_INCOMPLETE", "CRITICAL", "router-compatible source and lineage fields missing"))
    gemini_dedup = (
        "same_fingerprint_repeat_forbidden" in gemini_text
        and "SKIP_UNCHANGED_COMPONENT_FINGERPRINT" in workflow_text
        and "GEMINI_PREVIOUSLY_USED" in workflow_text
        and "previous_used" in workflow_text
    )
    if not gemini_dedup:
        findings.append(finding("GEMINI_FINGERPRINT_DEDUP_NOT_BOUND", "HIGH", "persistent repeat guard missing"))
    if diagnostic_path.exists():
        findings.append(finding("DIAGNOSTIC_WORKFLOW_RESIDUE", "MEDIUM", str(diagnostic_path)))

    rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    counts = {severity: sum(row["severity"] == severity for row in findings) for severity in rank}
    report = {
        "schema_version": "2.5",
        "version": VERSION,
        "state": "PASS_COMPONENT_PIPELINE_AUDIT_V2" if not findings else "HOLD_COMPONENT_PIPELINE_V2_REPAIR_REQUIRED",
        "finding_count": len(findings),
        "finding_counts": counts,
        "findings": sorted(findings, key=lambda row: (-rank[row["severity"]], row["code"])),
        "graph": [
            "EXACT_STRATEGY_LEDGER",
            "ROLE_BOUND_BOTS",
            "ALL_WATCHER_TEAM",
            "SELECTION_SAFE_SKILL",
            "ZBOT",
            "ZICO",
            "LICO",
            "ZLICE_LINEAGE",
            "ORDERED_ATTRIBUTION",
            "V3_CLAIM_GATES",
            "MATERIAL_AXIS_AI",
            "ROUTER_COMPATIBLE_GEMINI_DIRECT_VIDEO",
            "PERSISTENT_FINGERPRINT_DEDUP",
            "SHADOW_BLOCKED",
        ],
        "metrics": {
            "control_trade_count": int(((result.get("control") or {}).get("stats") or {}).get("trade_count", 0)),
            "full_stack_trade_count": int(((result.get("full_stack") or {}).get("stats") or {}).get("trade_count", 0)),
            "low_sample_hold": low_sample,
            "claim_tier": claim_tier,
            "performance_claim_allowed": performance_claim_allowed,
            "exact_skill_replay_required": exact_skill_replay_required,
            "order_stable": interaction.get("order_stable"),
            "statistical_gate_pass": statistics.get("pass"),
            "eligible_ai_axes": sorted(axis for axis, active in eligibility.items() if active),
            "interaction_residual": residual,
            "per_axis_gate_bound": per_axis_bindings,
            "gemini_router_fields_bound": gemini_router_fields,
            "gemini_dedup_bound": gemini_dedup,
        },
        "next": "WAIT_NEW_EXACT_LEDGER_OR_W1" if not findings else "FIX_FINDINGS_BEFORE_MERGE",
        **SAFE,
    }
    report["report_sha256"] = stable_sha(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--core", required=True)
    parser.add_argument("--runner", required=True)
    parser.add_argument("--gemini", required=True)
    parser.add_argument("--role-contract", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--diagnostic-workflow", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = audit(
        read_json(args.policy), read_json(args.result), Path(args.core), Path(args.runner), Path(args.gemini),
        Path(args.role_contract), Path(args.workflow), Path(args.diagnostic_workflow),
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(report["state"], report["finding_count"], report["report_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
