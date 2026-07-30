from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "STRATEGY11_10X_CLOSURE_MATRIX_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}

PASS_REAL = "PASS_REAL"
PASS_STRUCTURAL = "PASS_STRUCTURAL"
WAIT_DATA = "WAIT_DATA"
IMPLEMENTATION_REQUIRED = "IMPLEMENTATION_REQUIRED"
EXTERNAL_EVIDENCE_REQUIRED = "EXTERNAL_EVIDENCE_REQUIRED"
BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class DomainSpec:
    domain_id: str
    title: str
    required_files: tuple[str, ...]
    empirical_gates: tuple[str, ...]
    default_evidence_state: str


DOMAIN_SPECS: tuple[DomainSpec, ...] = (
    DomainSpec(
        "D1_RESEARCH_DATA",
        "Research and data authority",
        (
            "backend/tools/r7a4d_strategy11_continuous_data_collector_v1.py",
            ".github/workflows/r7a4d-strategy11-continuous-data-v1.yml",
            "backend/tools/strategy11_famous_indicator_autonomy_v1.py",
            ".github/workflows/r7a4d-strategy11-famous-indicator-autonomy-v1.yml",
        ),
        (
            "five-symbol OHLCV/funding parity",
            "480 complete non-overlap W1 bars",
            "W1 one-shot receipt",
        ),
        WAIT_DATA,
    ),
    DomainSpec(
        "D2_INDIVIDUAL_STRATEGY",
        "Individual strategy OOS validation",
        (
            "backend/contracts/strategy11_strategy_proposal_contract_v1.py",
            "backend/research/strategy11_global_candidate_classifier_v1.py",
            "backend/tools/strategy11_w1_one_shot_gate_v1.py",
            ".github/workflows/r7a4d-strategy11-w1-native-orchestrator-v1.yml",
        ),
        (
            "real W1",
            "real W2",
            "real W3",
            "new untouched sealed holdback",
        ),
        WAIT_DATA,
    ),
    DomainSpec(
        "D3_SYNTHESIS_FACTORY",
        "Bounded synthesis factory",
        (
            "backend/research/strategy11_synthesis_material_registry_v1.py",
            "backend/research/strategy11_bounded_synthesis_constructor_v1.py",
            "backend/research/strategy11_synthesis_factorial_replay_v1.py",
            "backend/research/strategy11_component_attribution_v1.py",
            "backend/research/strategy11_synthesis_sealer_v1.py",
        ),
        (
            "real sealed leaf materials",
            "W2 first OOS synthesis validation",
            "W3 repeatability",
            "new untouched synthesis seal",
        ),
        WAIT_DATA,
    ),
    DomainSpec(
        "D4_ENSEMBLE_PORTFOLIO",
        "Ensemble and portfolio intelligence",
        (
            "backend/research/strategy11_ensemble_correlation_analyzer_v1.py",
            "backend/research/strategy11_portfolio_governor_v1.py",
            "backend/research/strategy11_attribution_ledger_v1.py",
            "backend/research/strategy11_source_bound_multicandidate_orchestrator_v1.py",
        ),
        (
            "two or more real CORE/SYNTHESIS candidates",
            "real correlation and joint-DD evidence",
            "real attribution and leave-one-out evidence",
        ),
        EXTERNAL_EVIDENCE_REQUIRED,
    ),
    DomainSpec(
        "D5_EVOLUTION_LOOP",
        "Evidence-driven strategy evolution",
        (
            "backend/research/strategy11_evidence_optimize_closed_loop_v1.py",
            "backend/research/strategy11_trade_path_enricher_v1.py",
            "backend/research/strategy11_pre_shadow_path_optimize_planner_v1_1.py",
            ".github/workflows/r7a4d-strategy11-generation7-quota-state-machine-v1.yml",
        ),
        (
            "real source-bound trade paths",
            "bounded completed replays",
            "no duplicate strategy-axis-data generations",
        ),
        EXTERNAL_EVIDENCE_REQUIRED,
    ),
    DomainSpec(
        "D6_SHADOW_OBSERVER",
        "Shadow and observer qualification",
        (
            "backend/research/strategy11_shadow20_readonly_canary_v1.py",
            "backend/research/strategy11_shadow200_readonly_accumulator_v1.py",
            "backend/research/strategy11_shadow300_readonly_completion_v1.py",
            "backend/research/strategy11_post_shadow_observer_gate_v1.py",
        ),
        (
            "real Shadow20",
            "real Shadow200",
            "real Shadow300",
            "ML-Light/failure-learning observer 100C burn-in",
        ),
        EXTERNAL_EVIDENCE_REQUIRED,
    ),
    DomainSpec(
        "D7_ADAPTIVE_EXECUTION",
        "Adaptive execution preview",
        (
            "backend/contracts/strategy11_adaptive_execution_contract_v1.py",
        ),
        (
            "real BingX paper fill evidence",
            "partial-fill/idempotency evidence",
            "fee/slippage/funding/latency reconciliation",
        ),
        EXTERNAL_EVIDENCE_REQUIRED,
    ),
    DomainSpec(
        "D8_SELF_HEALING_RUNTIME",
        "Self-healing and runtime parity",
        (
            "backend/contracts/strategy11_self_healing_operations_contract_v1.py",
        ),
        (
            "Git master to VPS byte parity",
            "single STATE/LEDGER/DISPLAY writer authority",
            "ledger-PnL-Telegram-View-ALIMI parity",
            "verified rollback drill",
        ),
        EXTERNAL_EVIDENCE_REQUIRED,
    ),
    DomainSpec(
        "D9_DIGITAL_TWIN_GOVERNANCE",
        "Digital twin and human governance",
        (
            "backend/contracts/strategy11_market_digital_twin_contract_v1.py",
            "backend/contracts/strategy11_human_governed_capital_contract_v1.py",
            "backend/tools/strategy11_human_governed_autonomy_chain_fixture_v1.py",
        ),
        (
            "real portfolio scenario evidence",
            "real policy and risk-budget SSOT",
            "valid human approval scope and expiry",
        ),
        EXTERNAL_EVIDENCE_REQUIRED,
    ),
    DomainSpec(
        "D10_CONTROLLED_CAPITAL",
        "Controlled capital operation",
        (
            "backend/contracts/strategy11_adaptive_execution_contract_v1.py",
            "backend/contracts/strategy11_market_digital_twin_contract_v1.py",
            "backend/contracts/strategy11_human_governed_capital_contract_v1.py",
        ),
        (
            "30D Paper PASS",
            "human capital preflight PASS",
            "separate external manual enable",
            "minimum-capital single-strategy live canary",
            "error-budget-controlled scaling",
        ),
        BLOCKED,
    ),
)


class ClosureMatrixError(ValueError):
    pass


def canonical_sha(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ClosureMatrixError(f"OBJECT_REQUIRED:{path}")
    return dict(value)


def missing_files(root: Path, paths: Iterable[str]) -> list[str]:
    return sorted(path for path in paths if not (root / path).is_file())


def _data_state(manifest: Mapping[str, Any] | None) -> tuple[str, list[str], dict[str, Any]]:
    if manifest is None:
        return EXTERNAL_EVIDENCE_REQUIRED, ["DATA_MANIFEST_MISSING"], {}
    blockers = manifest.get("blockers")
    if not isinstance(blockers, list):
        return BLOCKED, ["DATA_BLOCKERS_NOT_LIST"], {}
    bars = manifest.get("available_non_overlap_bars")
    missing = manifest.get("missing_to_w1_480")
    symbols = manifest.get("symbols")
    details = {
        "manifest_state": manifest.get("state"),
        "available_non_overlap_bars": bars,
        "missing_to_w1_480": missing,
        "latest_closed_end": manifest.get("latest_closed_end"),
        "symbol_count": len(symbols) if isinstance(symbols, list) else 0,
        "w1_ready": manifest.get("w1_ready"),
    }
    integrity_ok = (
        manifest.get("state") == "PASS"
        and blockers == []
        and manifest.get("canonical_mutated") is False
        and manifest.get("registry_mutated") is False
        and manifest.get("protected_mutations") == 0
        and manifest.get("execution_allowed") is False
        and manifest.get("order_authority") == "BLOCKED"
        and isinstance(symbols, list)
        and len(symbols) == 5
        and len({row.get("rows") for row in symbols if isinstance(row, Mapping)}) == 1
        and len({row.get("last_timestamp_ms") for row in symbols if isinstance(row, Mapping)}) == 1
    )
    if not integrity_ok:
        return BLOCKED, ["DATA_INTEGRITY_OR_AUTHORITY_MISMATCH"], details
    if bars == 480 and missing == 0 and manifest.get("w1_ready") is True:
        return PASS_STRUCTURAL, ["W1_EXECUTION_RECEIPT_NOT_INSPECTED"], details
    return WAIT_DATA, ["W1_480_NOT_COMPLETE"], details


def evaluate(root: Path, data_manifest: Mapping[str, Any] | None = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    data_state, data_blockers, data_details = _data_state(data_manifest)
    total_required_files = 0
    total_present_files = 0

    for spec in DOMAIN_SPECS:
        missing = missing_files(root, spec.required_files)
        present_count = len(spec.required_files) - len(missing)
        total_required_files += len(spec.required_files)
        total_present_files += present_count
        structural_state = PASS_STRUCTURAL if not missing else IMPLEMENTATION_REQUIRED
        evidence_state = spec.default_evidence_state
        blockers: list[str] = []
        details: dict[str, Any] = {
            "required_file_count": len(spec.required_files),
            "present_file_count": present_count,
        }

        if missing:
            blockers.append("REQUIRED_FILES_MISSING")
        if spec.domain_id == "D1_RESEARCH_DATA":
            evidence_state = data_state
            blockers.extend(data_blockers)
            details.update(data_details)
        elif spec.domain_id in {"D2_INDIVIDUAL_STRATEGY", "D3_SYNTHESIS_FACTORY"}:
            blockers.append("REAL_W1_W2_W3_NEW_SEALED_NOT_PROVEN")
        elif spec.domain_id in {"D4_ENSEMBLE_PORTFOLIO", "D5_EVOLUTION_LOOP", "D6_SHADOW_OBSERVER", "D7_ADAPTIVE_EXECUTION", "D9_DIGITAL_TWIN_GOVERNANCE"}:
            blockers.append("REAL_OPERATIONAL_EVIDENCE_NOT_PROVEN")
        elif spec.domain_id == "D8_SELF_HEALING_RUNTIME":
            blockers.append("VPS_AND_RUNTIME_EVIDENCE_REQUIRED")
        elif spec.domain_id == "D10_CONTROLLED_CAPITAL":
            blockers.append("UPSTREAM_REAL_GATES_NOT_COMPLETE")

        effective_state = structural_state if structural_state == IMPLEMENTATION_REQUIRED else evidence_state
        rows.append(
            {
                "domain_id": spec.domain_id,
                "title": spec.title,
                "state": effective_state,
                "structural_state": structural_state,
                "evidence_state": evidence_state,
                "missing_files": missing,
                "blockers": sorted(set(blockers)),
                "empirical_gates": list(spec.empirical_gates),
                "details": details,
            }
        )

    structural_pass_count = sum(row["structural_state"] == PASS_STRUCTURAL for row in rows)
    real_pass_count = sum(row["evidence_state"] == PASS_REAL for row in rows)
    implementation_required_count = sum(row["structural_state"] == IMPLEMENTATION_REQUIRED for row in rows)
    waiting_count = sum(row["evidence_state"] in {WAIT_DATA, EXTERNAL_EVIDENCE_REQUIRED} for row in rows)
    blocked_count = sum(row["evidence_state"] == BLOCKED for row in rows)

    score_claim_allowed = real_pass_count == len(rows) and implementation_required_count == 0
    overall_state = "PASS_REAL_10X_CLOSURE" if score_claim_allowed else "HOLD_10X_CLOSURE_INCOMPLETE"
    action = "route_change" if implementation_required_count else "hold"

    result = {
        "schema_version": "strategy11.10x_closure_matrix.v1",
        "version": VERSION,
        "overall_state": overall_state,
        "action": action,
        "score_claim_allowed": score_claim_allowed,
        "structural_domain_coverage_pct": round(structural_pass_count / len(rows) * 100.0, 3),
        "structural_file_coverage_pct": round(total_present_files / max(total_required_files, 1) * 100.0, 3),
        "real_evidence_coverage_pct": round(real_pass_count / len(rows) * 100.0, 3),
        "counts": {
            "domain_count": len(rows),
            "pass_real": real_pass_count,
            "pass_structural": structural_pass_count,
            "implementation_required": implementation_required_count,
            "waiting_external_or_data": waiting_count,
            "blocked": blocked_count,
        },
        "domains": rows,
        "next": next_action(rows),
        **SAFETY,
    }
    result["matrix_sha"] = canonical_sha(result)
    return result


def next_action(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows_list = list(rows)
    for row in rows_list:
        if row.get("structural_state") == IMPLEMENTATION_REQUIRED:
            return {
                "domain_id": row.get("domain_id"),
                "state": IMPLEMENTATION_REQUIRED,
                "reason": (row.get("blockers") or ["REQUIRED_FILES_MISSING"])[0],
            }
    for state in (BLOCKED, WAIT_DATA, EXTERNAL_EVIDENCE_REQUIRED, PASS_STRUCTURAL):
        for row in rows_list:
            if row.get("evidence_state") == state:
                return {
                    "domain_id": row.get("domain_id"),
                    "state": state,
                    "reason": (row.get("blockers") or ["NO_BLOCKER_DETAIL"])[0],
                }
    return {"domain_id": None, "state": PASS_REAL, "reason": "ALL_DOMAINS_PASS_REAL"}


def render_markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# Strategy11 / ZEL 10x Closure Matrix",
        "",
        f"- Overall: `{result['overall_state']}`",
        f"- Action: `{result['action']}`",
        f"- Structural domain coverage: `{result['structural_domain_coverage_pct']}%`",
        f"- Structural file coverage: `{result['structural_file_coverage_pct']}%`",
        f"- Real-evidence coverage: `{result['real_evidence_coverage_pct']}%`",
        f"- 10/10 claim allowed: `{str(result['score_claim_allowed']).lower()}`",
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
            "## Interpretation",
            "",
            "Structural PASS proves executable contracts and fixtures exist. It is never counted as real strategy or capital evidence.",
            "",
            "## Safety",
            "",
            "This matrix never promotes a strategy, starts Shadow/Paper/Live, changes capital, or grants order authority.",
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
    manifest = load_json(Path(args.data_manifest)) if args.data_manifest else None
    result = evaluate(root, manifest)

    json_path = Path(args.output_json)
    md_path = Path(args.output_md)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps({"state": result["overall_state"], "next": result["next"], "matrix_sha": result["matrix_sha"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
