from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_COMPONENT_PIPELINE_AUDIT_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}
EXPECTED_MODULES = {"bots", "teams", "skills", "advisors"}
OBSERVER_ONLY_SKILLS = {"SK_ADD_DCA", "SK_ADD_AVG_DOWN", "SK_ADD_WATER_ADD", "SK_ENTRY_SHORT_BEAM"}
EXPECTED_TEAMS = {"AlphaTeam", "BetaTeam", "GammaTeam", "DeltaTeam"}
EXPECTED_ROLES = {"ZBOT", "ZICO", "LICO", "ZLICE"}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def finding(code: str, severity: str, detail: str, fix: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "detail": detail, "recommended_fix": fix}


def finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def inspect_source(source_path: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    text = source_path.read_text(encoding="utf-8")
    ast.parse(text)
    rows: list[dict[str, str]] = []
    checks = {
        "short_beam_unchanged_append": "if sid=='SK_ENTRY_SHORT_BEAM': z.append(r); continue" in text,
        "long_beam_removes_beam": "if sid=='SK_ENTRY_LONG_BEAM' and r['beam']: continue" in text,
        "only_sbot_watcher_checked": "('SBot' not in tm['watchers'])" in text and "for watcher in tm['watchers']" not in text,
        "single_bot_profile_reused_for_all_roles": "q={b:botfit(r,b,bb['weight'],bb['warning_cap'])" in text,
        "zlice_fixed_lineage_only": "'zlice_lineage_coverage_pct':100." in text,
        "groq_metadata_false": "'groq_required_this_epoch':False" in text,
    }
    if checks["short_beam_unchanged_append"]:
        rows.append(finding(
            "SHORT_BEAM_FALSE_EXACT_ABLATION", "CRITICAL",
            "SK_ENTRY_SHORT_BEAM copies every long-first trade unchanged while being labelled EXACT_ABLATION.",
            "Reclassify ShortBeam as observer-only until a true short ledger exists; exclude it from executable best-skill selection.",
        ))
    if checks["long_beam_removes_beam"]:
        rows.append(finding(
            "LONG_BEAM_REVERSED_ABLATION_SEMANTICS", "HIGH",
            "SK_ENTRY_LONG_BEAM removes rows already tagged long_beam, so its name and applied direction disagree.",
            "Split LONG_BEAM_ONLY from WITHOUT_LONG_BEAM ablation and retain explicit direction in result schema.",
        ))
    if checks["only_sbot_watcher_checked"]:
        rows.append(finding(
            "TEAM_WATCHERS_PARTIALLY_APPLIED", "HIGH",
            "Team contracts list multiple watchers, but selection logic only gives SBot an operational veto.",
            "Evaluate every watcher with role-specific observe/veto semantics while preserving SBot hard-veto precedence.",
        ))
    if checks["single_bot_profile_reused_for_all_roles"]:
        rows.append(finding(
            "BOT_PROFILE_LEAK_ACROSS_ROLES", "CRITICAL",
            "The best single bot weight/warning-cap is reused for LBot, MBot, OBot and SBot in the full stack.",
            "Select and bind an independent profile per bot role, then assemble the team from those four role-bound profiles.",
        ))
    if checks["zlice_fixed_lineage_only"]:
        rows.append(finding(
            "ZLICE_NOT_ACTUALLY_REPLAYED", "HIGH",
            "Zlice is represented as a constant 100% lineage field and has no cost/slippage/latency counterfactual axis.",
            "Add fee/slippage/latency/partial-fill stress axes and keep evidence-lineage checks independent from economic-cost simulation.",
        ))
    if checks["groq_metadata_false"]:
        rows.append(finding(
            "AI_USAGE_METADATA_STALE", "MEDIUM",
            "Engine output says Groq is not required even though the workflow now performs required per-axis Groq review.",
            "Derive AI usage metadata from the pinned policy and store actual per-axis provider receipt SHAs downstream.",
        ))
    return rows, checks


def audit(
    policy: Mapping[str, Any],
    result: Mapping[str, Any],
    source_path: Path,
    role_path: Path,
    workflow_path: Path,
    diagnostic_path: Path,
) -> dict[str, Any]:
    findings, source_checks = inspect_source(source_path)
    role_text = role_path.read_text(encoding="utf-8")
    workflow_text = workflow_path.read_text(encoding="utf-8")
    ast.parse(role_text)

    for key, expected in SAFETY.items():
        if result.get(key) != expected:
            findings.append(finding("SAFETY_MISMATCH", "CRITICAL", f"result.{key}={result.get(key)!r}, expected {expected!r}", "Fail closed and restore immutable research-only authority."))
        if policy.get("safety", {}).get(key) != expected:
            findings.append(finding("POLICY_SAFETY_MISMATCH", "CRITICAL", f"policy.safety.{key}={policy.get('safety', {}).get(key)!r}", "Repair the single policy SSOT before any replay."))

    modules = set((result.get("module_results") or {}).keys())
    if modules != EXPECTED_MODULES:
        findings.append(finding("MODULE_STAGE_SET_MISMATCH", "CRITICAL", f"module stages={sorted(modules)}", "Require bots, teams, skills and advisors exactly once."))

    teams = set((policy.get("team_search") or {}).get("teams", {}))
    if teams != EXPECTED_TEAMS:
        findings.append(finding("TEAM_CONTRACT_SET_MISMATCH", "CRITICAL", f"teams={sorted(teams)}", "Restore Alpha/Beta/Gamma/Delta contracts."))

    if not all(role in role_text for role in EXPECTED_ROLES):
        findings.append(finding("ROLE_BOUNDARY_INCOMPLETE", "CRITICAL", "One or more ZBot/Zico/Lico/Zlice role contracts are absent.", "Restore all four role contracts and negative authority fixtures."))
    if "PRIVATE_AUTHORITY_ACTION_FORBIDDEN" not in role_text or "SBOT_VETO_PRECEDENCE" not in role_text:
        findings.append(finding("ROLE_BOUNDARY_NEGATIVE_GUARDS_MISSING", "CRITICAL", "Private-action or SBot-precedence guard missing.", "Keep fail-closed role boundary validation in the pipeline preflight."))

    skills = (result.get("module_results") or {}).get("skills", {})
    best_skill = (skills.get("best") or {}).get("skill_id")
    if best_skill in OBSERVER_ONLY_SKILLS or (skills.get("best") or {}).get("loss_direction_observer_only") is True:
        findings.append(finding("OBSERVER_ONLY_SKILL_SELECTED", "CRITICAL", f"best_skill={best_skill}", "Exclude observer-only candidates from executable full-stack selection."))

    no_op_axes: list[str] = []
    for axis, module in (("BOT_POLICY", "bots"), ("TEAM_POLICY", "teams"), ("SKILL_PROFILE", "skills"), ("ADVISOR_PROFILE", "advisors")):
        best = ((result.get("module_results") or {}).get(module) or {}).get("best") or {}
        evidence = best.get("evidence") or {}
        deltas = evidence.get("deltas") or {}
        if not evidence.get("material") and all(abs(finite(deltas.get(name))) <= 1e-12 for name in ("net", "pf", "dd_reduction")):
            no_op_axes.append(axis)
    if no_op_axes:
        findings.append(finding(
            "NO_OP_AXES_SENT_TO_AI", "HIGH",
            f"No-change axes currently eligible for AI review: {no_op_axes}",
            "Skip no-op axes before Groq/Workers/Gemini calls and preserve SKIP_NO_CHANGE receipts.",
        ))

    control_trades = int(finite(((result.get("control") or {}).get("stats") or {}).get("trade_count")))
    full_trades = int(finite(((result.get("full_stack") or {}).get("stats") or {}).get("trade_count")))
    if min(control_trades, full_trades) < 20:
        findings.append(finding(
            "LOW_SAMPLE_PERFORMANCE_CLAIM", "CRITICAL",
            f"control trades={control_trades}, full-stack trades={full_trades}",
            "Force LOW_SAMPLE_HOLD; never call a 4–5 trade result optimized or promotable.",
        ))

    attribution = result.get("component_attribution") or {}
    individual = sum(finite(attribution.get(name)) for name in ("bot_delta_net", "team_delta_net", "skill_delta_net", "advisor_delta_net"))
    full_delta = finite(attribution.get("full_stack_delta_net"))
    residual = full_delta - individual
    if abs(residual) > 0.05:
        findings.append(finding(
            "UNEXPLAINED_COMPONENT_INTERACTION", "HIGH",
            f"full delta={full_delta:.8f}, sum independent={individual:.8f}, residual={residual:.8f}",
            "Run ordered leave-one-out and factorial interaction attribution before retaining a full stack.",
        ))

    if "Required per-axis Groq and Workers AI review" not in workflow_text:
        findings.append(finding("PER_AXIS_AI_GATE_NOT_BOUND", "CRITICAL", "Workflow does not expose the four isolated AI gates.", "Bind BOT/TEAM/SKILL/ADVISOR envelopes independently."))
    if "Build bounded direct-video request receipt" in workflow_text and "GEMINI_API_KEY" not in workflow_text:
        findings.append(finding(
            "GEMINI_REQUEST_ONLY_NOT_EXECUTED", "HIGH",
            "Component workflow emits a Gemini request receipt but does not execute direct-video analysis.",
            "Run direct-video only on convergence/new ledger/new W1, deduplicate by fingerprint, then gate each one-axis hypothesis with Groq+Workers.",
        ))
    if diagnostic_path.exists():
        findings.append(finding("DIAGNOSTIC_WORKFLOW_RESIDUE", "MEDIUM", str(diagnostic_path), "Delete the one-time diagnostic after the permanent gate is verified."))

    severity_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    counts = {severity: sum(row["severity"] == severity for row in findings) for severity in severity_rank}
    max_severity = max((row["severity"] for row in findings), key=lambda value: severity_rank[value], default="NONE")
    state = "PASS_COMPONENT_PIPELINE_AUDIT" if not findings else "HOLD_COMPONENT_PIPELINE_OPTIMIZATION_REQUIRED"
    report = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": state,
        "max_severity": max_severity,
        "finding_counts": counts,
        "finding_count": len(findings),
        "findings": sorted(findings, key=lambda row: (-severity_rank[row["severity"]], row["code"])),
        "graph": ["STRATEGY_EXACT_LEDGER", "BOT_ROLES", "TEAM_LANE", "SKILL", "ADVISORY_GOVERNANCE", "ATTRIBUTION", "SHADOW_INTAKE_BLOCKED"],
        "source_checks": source_checks,
        "metrics": {
            "control_trade_count": control_trades,
            "full_stack_trade_count": full_trades,
            "individual_delta_sum": individual,
            "full_stack_delta": full_delta,
            "interaction_residual": residual,
            "no_op_ai_axes": no_op_axes,
        },
        "next": "FIX_CRITICAL_THEN_HIGH_FINDINGS_WITH_MINIMAL_WRAPPER_CHANGES" if findings else "WAIT_NEW_EXACT_LEDGER_OR_W1",
        **SAFETY,
    }
    report["report_sha256"] = sha(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--role-contract", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--diagnostic-workflow", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = audit(
        read(args.policy), read(args.result), Path(args.source), Path(args.role_contract),
        Path(args.workflow), Path(args.diagnostic_workflow),
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(report["state"], report["finding_count"], report["report_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
