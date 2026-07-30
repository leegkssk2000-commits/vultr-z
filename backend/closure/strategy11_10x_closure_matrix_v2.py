from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from backend.research import strategy11_10x_closure_matrix_v1 as v1

VERSION = "STRATEGY11_10X_CLOSURE_MATRIX_V2"
SCHEMA_VERSION = "strategy11.10x_closure_matrix.v2"


def _replace_required(domain_id: str, required_files: tuple[str, ...]) -> v1.DomainSpec:
    original = next(spec for spec in v1.DOMAIN_SPECS if spec.domain_id == domain_id)
    return v1.DomainSpec(
        domain_id=original.domain_id,
        title=original.title,
        required_files=required_files,
        empirical_gates=original.empirical_gates,
        default_evidence_state=original.default_evidence_state,
    )


D3_REQUIRED = (
    "backend/research/strategy11_synthesis_material_registry_v1.py",
    "backend/research/strategy11_bounded_synthesis_constructor_v1.py",
    "backend/research/strategy11_synthesis_factorial_replay_v1.py",
    "backend/research/strategy11_component_attribution_v1.py",
    "backend/research/strategy11_synthesis_sealer_v1.py",
    "backend/research/strategy11_synthesis_classifier_adapter_v1.py",
)
D4_REQUIRED = (
    "backend/research/strategy11_ensemble_correlation_analyzer_v1.py",
    "backend/research/strategy11_portfolio_governor_v1.py",
    "backend/research/strategy11_attribution_ledger_v1.py",
    "backend/research/strategy11_source_bound_multicandidate_orchestrator_v1.py",
    "backend/research/strategy11_synthesis_portfolio_integration_v1.py",
)

DOMAIN_SPECS: tuple[v1.DomainSpec, ...] = tuple(
    _replace_required("D3_SYNTHESIS_FACTORY", D3_REQUIRED)
    if spec.domain_id == "D3_SYNTHESIS_FACTORY"
    else _replace_required("D4_ENSEMBLE_PORTFOLIO", D4_REQUIRED)
    if spec.domain_id == "D4_ENSEMBLE_PORTFOLIO"
    else spec
    for spec in v1.DOMAIN_SPECS
)


def next_action(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows_list = list(rows)
    for row in rows_list:
        if row.get("structural_state") == v1.IMPLEMENTATION_REQUIRED:
            return {
                "domain_id": row.get("domain_id"),
                "state": v1.IMPLEMENTATION_REQUIRED,
                "reason": (row.get("blockers") or ["REQUIRED_FILES_MISSING"])[0],
            }
    for state in (v1.WAIT_DATA, v1.EXTERNAL_EVIDENCE_REQUIRED, v1.BLOCKED, v1.PASS_STRUCTURAL):
        for row in rows_list:
            if row.get("evidence_state") == state:
                return {
                    "domain_id": row.get("domain_id"),
                    "state": state,
                    "reason": (row.get("blockers") or ["NO_BLOCKER_DETAIL"])[0],
                }
    return {"domain_id": None, "state": v1.PASS_REAL, "reason": "ALL_DOMAINS_PASS_REAL"}


def evaluate(root: Path, data_manifest: Mapping[str, Any] | None = None) -> dict[str, Any]:
    previous_specs = v1.DOMAIN_SPECS
    try:
        v1.DOMAIN_SPECS = DOMAIN_SPECS
        result = v1.evaluate(root, data_manifest)
    finally:
        v1.DOMAIN_SPECS = previous_specs

    result = dict(result)
    result["schema_version"] = SCHEMA_VERSION
    result["version"] = VERSION
    result["supersedes"] = {
        "schema_version": "strategy11.10x_closure_matrix.v1",
        "reason": "Re-census after bounded synthesis, classifier, portfolio integration and post-Shadow observer gate installation.",
    }
    result["next"] = next_action(result["domains"])
    result["action"] = "route_change" if result["counts"]["implementation_required"] else "hold"
    result.pop("matrix_sha", None)
    result["matrix_sha"] = v1.canonical_sha(result)
    return result


def render_markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# Strategy11 / ZEL 10x Closure Matrix V2",
        "",
        f"- Overall: `{result['overall_state']}`",
        f"- Action: `{result['action']}`",
        f"- Structural domain coverage: `{result['structural_domain_coverage_pct']}%`",
        f"- Structural file coverage: `{result['structural_file_coverage_pct']}%`",
        f"- Real-evidence coverage: `{result['real_evidence_coverage_pct']}%`",
        f"- 10/10 claim allowed: `{str(result['score_claim_allowed']).lower()}`",
        f"- Next: `{result['next']['domain_id']} / {result['next']['state']}`",
        f"- Matrix SHA: `{result['matrix_sha']}`",
        "",
        "| Domain | Structural | Real evidence | Effective | Missing files | First blocker |",
        "|---|---|---|---|---:|---|",
    ]
    for row in result["domains"]:
        blocker = (row["blockers"] or ["-"])[0]
        lines.append(
            f"| {row['domain_id']} {row['title']} | `{row['structural_state']}` | "
            f"`{row['evidence_state']}` | `{row['state']}` | {len(row['missing_files'])} | `{blocker}` |"
        )
    lines.extend(
        [
            "",
            "## Authority boundary",
            "",
            "100% structural coverage means every planned executable contract exists and passes its own fixtures. It is not real strategy, Shadow, Paper, Live or capital evidence.",
            "",
            "## Current transition rule",
            "",
            "When structure is complete, the first unresolved real-data gate is selected before downstream capital blockers. No stage is skipped.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--data-manifest")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    manifest = v1.load_json(Path(args.data_manifest)) if args.data_manifest else None
    result = evaluate(root, manifest)
    json_path = Path(args.output_json)
    md_path = Path(args.output_md)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")
    print(
        json.dumps(
            {
                "state": result["overall_state"],
                "structural_domain_coverage_pct": result["structural_domain_coverage_pct"],
                "structural_file_coverage_pct": result["structural_file_coverage_pct"],
                "real_evidence_coverage_pct": result["real_evidence_coverage_pct"],
                "next": result["next"],
                "matrix_sha": result["matrix_sha"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
