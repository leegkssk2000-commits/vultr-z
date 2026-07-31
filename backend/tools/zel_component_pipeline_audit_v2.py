from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_COMPONENT_PIPELINE_AUDIT_V2"
SAFE = {"research_only": True, "promotion_authority": False, "protected_mutations": 0, "execution_allowed": False, "execution_authority": "NONE", "order_authority": "BLOCKED", "runtime_bound": False}
OBSERVER_ONLY = {"SK_ENTRY_SHORT_BEAM", "SK_ADD_DCA", "SK_ADD_AVG_DOWN", "SK_ADD_WATER_ADD"}


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def stable_sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def read(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def add(rows: list[dict[str, str]], code: str, severity: str, detail: str) -> None:
    rows.append({"code": code, "severity": severity, "detail": detail})


def audit(policy: Mapping[str, Any], result: Mapping[str, Any], source: Path, role_contract: Path, workflow: Path, diagnostic: Path) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    source_text = source.read_text()
    role_text = role_contract.read_text()
    workflow_text = workflow.read_text()
    ast.parse(source_text); ast.parse(role_text)

    for key, expected in SAFE.items():
        if result.get(key) != expected:
            add(findings, "RESULT_SAFETY_MISMATCH", "CRITICAL", f"{key}={result.get(key)!r}")
        if (policy.get("safety") or {}).get(key) != expected:
            add(findings, "POLICY_SAFETY_MISMATCH", "CRITICAL", f"{key}={(policy.get('safety') or {}).get(key)!r}")

    required_source = {
        "ROLE_BOUND_BOT_PROFILES": "best_by_role",
        "ALL_TEAM_WATCHERS": "for watcher in team.get(\"watchers\", [])",
        "SHORT_BEAM_OBSERVER_ONLY": "OBSERVER_ONLY_NO_SHORT_LEDGER",
        "OBSERVER_SELECTION_FLAG": "selection_eligible",
        "LOW_SAMPLE_HOLD": "LOW_SAMPLE_HOLD",
        "ORDERED_ATTRIBUTION": "ORDERED_MARGINAL_EXACT_SUM",
        "ZLICE_LINEAGE_VALIDATION": "lineage_validated",
        "LICO_COST_STRESS": "cost_bps_per_side",
        "NO_OP_AXIS_ELIGIBILITY": "axis_review_eligibility",
    }
    for code, token in required_source.items():
        if token not in source_text:
            add(findings, code + "_MISSING", "CRITICAL", token)

    if set((result.get("module_results") or {}).get("bots", {}).get("best_by_role", {})) != {"LBot", "MBot", "OBot", "SBot"}:
        add(findings, "BOT_ROLE_SET_INVALID", "CRITICAL", "Four independent role profiles required")
    best_skill = ((result.get("module_results") or {}).get("skills") or {}).get("best") or {}
    if best_skill.get("skill_id") in OBSERVER_ONLY or best_skill.get("selection_eligible") is not True:
        add(findings, "OBSERVER_ONLY_SKILL_SELECTED", "CRITICAL", str(best_skill.get("skill_id")))
    if set(((result.get("module_results") or {}).get("skills") or {}).get("observer_only_ids", [])) != OBSERVER_ONLY:
        add(findings, "OBSERVER_ONLY_SET_INVALID", "HIGH", "Observer skill registry mismatch")

    control_count = int(((result.get("control") or {}).get("stats") or {}).get("trade_count", 0))
    full_count = int(((result.get("full_stack") or {}).get("stats") or {}).get("trade_count", 0))
    minimum = int((policy.get("epoch_policy") or {}).get("minimum_trade_count_for_performance_claim", 20))
    if min(control_count, full_count) < minimum and result.get("state") != "LOW_SAMPLE_HOLD":
        add(findings, "LOW_SAMPLE_NOT_HELD", "CRITICAL", f"control={control_count},full={full_count},minimum={minimum}")
    if min(control_count, full_count) >= minimum and result.get("state") == "LOW_SAMPLE_HOLD":
        add(findings, "FALSE_LOW_SAMPLE_HOLD", "HIGH", f"control={control_count},full={full_count}")

    attribution = result.get("component_attribution") or {}
    if attribution.get("method") != "ORDERED_MARGINAL_EXACT_SUM" or abs(float(attribution.get("interaction_residual", 99.0))) > 1e-9:
        add(findings, "ATTRIBUTION_NOT_EXACT", "CRITICAL", canonical(attribution))
    applied = (result.get("full_stack") or {}).get("applied_components") or {}
    if any(axis != "ZLICE" and active and not result.get("axis_review_eligibility", {}).get("TEAM_POLICY" if axis == "TEAM" else "SKILL_PROFILE" if axis == "SKILL" else "ADVISOR_PROFILE", False) for axis, active in applied.items()):
        add(findings, "NON_MATERIAL_STAGE_APPLIED", "CRITICAL", canonical(applied))

    eligibility = result.get("axis_review_eligibility") or {}
    if "axis_review_eligibility" not in workflow_text or "if not eligible: continue" not in workflow_text:
        add(findings, "NO_OP_AI_SKIP_NOT_BOUND", "HIGH", "Workflow must build envelopes only for eligible material axes")
    if "GEMINI_API_KEY" not in workflow_text or "zel_component_gemini_direct_video_v1.py review" not in workflow_text:
        add(findings, "GEMINI_DIRECT_VIDEO_NOT_EXECUTED", "HIGH", "Actual direct-video job missing")
    if "same_fingerprint_repeat_forbidden" not in source_text or (policy.get("ai_policy") or {}).get("same_fingerprint_repeat_forbidden") is not True:
        add(findings, "GEMINI_REPEAT_GUARD_MISSING", "HIGH", "Same fingerprint repeat must be forbidden")
    if diagnostic.exists():
        add(findings, "DIAGNOSTIC_RESIDUE", "MEDIUM", str(diagnostic))
    for token in ("PRIVATE_AUTHORITY_ACTION_FORBIDDEN", "SBOT_VETO_PRECEDENCE", "cross_role_substitution_forbidden"):
        if token not in role_text:
            add(findings, "ROLE_BOUNDARY_GUARD_MISSING", "CRITICAL", token)

    rank = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1}
    report = {
        "schema_version": "2.0", "version": VERSION,
        "state": "PASS_COMPONENT_PIPELINE_AUDIT_V2" if not findings else "HOLD_COMPONENT_PIPELINE_V2_DEFECTS",
        "finding_count": len(findings),
        "finding_counts": {level: sum(row["severity"] == level for row in findings) for level in rank},
        "findings": sorted(findings, key=lambda row: (-rank[row["severity"]], row["code"])),
        "metrics": {"control_trade_count": control_count, "full_stack_trade_count": full_count, "minimum_trade_count": minimum, "eligible_ai_axes": [axis for axis, active in eligibility.items() if active], "applied_components": applied},
        "graph": ["STRATEGY_EXACT_LEDGER", "ROLE_BOUND_BOTS", "FOUR_TEAM_LANES", "SKILL_WITH_OBSERVER_SPLIT", "ZBOT", "ZICO", "LICO", "ZLICE", "ORDERED_ATTRIBUTION", "AI_GATES", "SHADOW_BLOCKED"],
        **SAFE,
    }
    report["report_sha256"] = stable_sha(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True); parser.add_argument("--result", required=True); parser.add_argument("--source", required=True); parser.add_argument("--role-contract", required=True); parser.add_argument("--workflow", required=True); parser.add_argument("--diagnostic", required=True); parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = audit(read(args.policy), read(args.result), Path(args.source), Path(args.role_contract), Path(args.workflow), Path(args.diagnostic))
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True); (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(report["state"], report["finding_count"], report["report_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
