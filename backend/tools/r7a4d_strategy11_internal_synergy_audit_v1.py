from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

VERSION = "R7A4D_STRATEGY11_INTERNAL_SYNERGY_AUDIT_V1"
TEXT_SUFFIXES = {".py", ".json", ".yml", ".yaml", ".md"}
EXCLUDE_PARTS = {".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv"}
EXCLUDE_PATH_FRAGMENTS = {"strategy11_internal_synergy_audit_v1", "strategy11-internal-synergy-audit-v1"}
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}

CAPABILITIES = {
    "COMMON_STRATEGY_OUTPUT_CONTRACT": {
        "path_hints": ["strategy", "proposal", "contract", "candidate"],
        "required_groups": [
            ["strategy_id"], ["confidence", "uncertainty"], ["regime"],
            ["cost", "slippage", "funding"], ["risk", "drawdown", "tail"], ["lineage", "source_sha"],
        ],
        "description": "One normalized strategy proposal schema carrying edge/confidence/regime/cost/risk/lineage.",
    },
    "GLOBAL_CANDIDATE_CLASSIFIER": {
        "path_hints": ["classifier", "classification"],
        "required_groups": [["core"], ["synthesis"], ["reject"], ["hold"]],
        "description": "Shared CORE/SYNTHESIS/REJECT/HOLD classifier.",
    },
    "ENSEMBLE_CORRELATION_ANALYZER": {
        "path_hints": ["ensemble", "correlation"],
        "required_groups": [["correlation"], ["overlap"], ["drawdown"], ["marginal", "contribution"], ["redundancy", "cosine"]],
        "description": "Cross-strategy overlap, correlation, joint drawdown and marginal contribution analysis.",
    },
    "PORTFOLIO_GOVERNOR": {
        "path_hints": ["portfolio", "allocator", "governor", "weight"],
        "required_groups": [["target_weight", "weights"], ["risk_budget"], ["turnover"], ["capacity", "liquidity"], ["rebalance"], ["rollback"]],
        "description": "Shadow-only portfolio construction layer between ensemble selection and lifecycle control.",
    },
    "REGIME_ROUTED_EXPERTS": {
        "path_hints": ["team", "lane", "regime", "selector"],
        "required_groups": [["alpha"], ["beta"], ["gamma"], ["delta"], ["regime"], ["conflict", "veto"]],
        "description": "Independent Alpha/Beta/Gamma/Delta teams with regime-aware routing and veto/conflict policy.",
    },
    "ROLE_BOUNDARY_ZBOT_ZICO_LICO_ZLICE": {
        "path_hints": ["zbot", "zico", "lico", "zlice"],
        "required_groups": [["zbot"], ["zico"], ["lico"], ["zlice"]],
        "description": "Advisor, lifecycle, liquidity/context and evidence/audit roles are separately represented.",
    },
    "STRATEGY_ATTRIBUTION_LEDGER": {
        "path_hints": ["attribution", "ledger", "contribution"],
        "required_groups": [["attribution"], ["strategy_id"], ["pnl", "net"], ["marginal", "contribution"], ["regime"], ["cost"]],
        "description": "Per-strategy and per-module contribution ledger after costs and by regime.",
    },
    "MODEL_RISK_GOVERNANCE": {
        "path_hints": ["model", "risk", "drift", "calibration", "error_budget"],
        "required_groups": [["drift"], ["calibration"], ["error_budget"], ["rollback"], ["shadow"], ["promotion_authority"]],
        "description": "Drift/calibration/error-budget/rollback controls independent of model opinions.",
    },
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_files(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in EXCLUDE_PARTS for part in path.parts):
            continue
        relative = str(path.relative_to(root))
        lower_path = relative.lower()
        if any(fragment in lower_path for fragment in EXCLUDE_PATH_FRAGMENTS):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lower = text.lower()
        imports: list[str] = []
        if path.suffix == ".py":
            try:
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.append(node.module)
            except SyntaxError:
                pass
        rows.append({
            "path": relative,
            "lower_path": lower_path,
            "suffix": path.suffix.lower(),
            "sha256": sha256_text(text),
            "lower": lower,
            "imports": sorted(set(imports)),
            "executable": path.suffix == ".py",
        })
    return rows


def match_group(text: str, group: list[str]) -> bool:
    return any(token.lower() in text for token in group)


def capability_evidence(rows: list[dict[str, Any]], spec: dict[str, Any]) -> dict[str, Any]:
    required = spec["required_groups"]
    path_hints = [str(value).lower() for value in spec["path_hints"]]
    evidence: list[dict[str, Any]] = []
    for row in rows:
        if not any(hint in row["lower_path"] for hint in path_hints):
            continue
        matched = [index for index, group in enumerate(required) if match_group(row["lower"], group)]
        if matched:
            evidence.append({"path": row["path"], "executable": row["executable"], "matched_groups": matched})
    executable = [row for row in evidence if row["executable"]]
    covered = sorted({index for row in executable for index in row["matched_groups"]})
    dense_evidence = [row for row in executable if len(row["matched_groups"]) >= max(2, (len(required) + 1) // 2)]
    implemented = len(covered) == len(required) and bool(dense_evidence)
    return {
        "status": "IMPLEMENTED_EVIDENCE" if implemented else "IMPLEMENTATION_REQUIRED",
        "covered_group_count": len(covered),
        "required_group_count": len(required),
        "dense_executable_evidence_count": len(dense_evidence),
        "executable_evidence": executable[:30],
        "all_evidence_count": len(evidence),
        "description": spec["description"],
    }


def main() -> int:
    root = Path(".").resolve()
    out = Path("artifacts/strategy11_internal_synergy_audit_v1")
    out.mkdir(parents=True, exist_ok=True)
    rows = read_files(root)
    capabilities = {name: capability_evidence(rows, spec) for name, spec in CAPABILITIES.items()}

    implemented = sorted(name for name, row in capabilities.items() if row["status"] == "IMPLEMENTED_EVIDENCE")
    missing = sorted(name for name, row in capabilities.items() if row["status"] != "IMPLEMENTED_EVIDENCE")
    priority = [
        name for name in (
            "COMMON_STRATEGY_OUTPUT_CONTRACT",
            "GLOBAL_CANDIDATE_CLASSIFIER",
            "ENSEMBLE_CORRELATION_ANALYZER",
            "PORTFOLIO_GOVERNOR",
            "STRATEGY_ATTRIBUTION_LEDGER",
            "REGIME_ROUTED_EXPERTS",
            "ROLE_BOUNDARY_ZBOT_ZICO_LICO_ZLICE",
            "MODEL_RISK_GOVERNANCE",
        ) if name in missing
    ]
    summary = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_INTERNAL_SYNERGY_AUDIT",
        "file_count": len(rows),
        "implemented_capabilities": implemented,
        "missing_capabilities": missing,
        "recommended_implementation_order": priority,
        "capabilities": capabilities,
        "recommended_flow": [
            "INDEPENDENT_TEAM_PROPOSALS",
            "LICO_CONTEXT_AND_COST_ENVELOPE",
            "ZBOT_ADVISORY_COUNTERARGUMENT",
            "GLOBAL_CLASSIFIER_AND_MATERIAL_SEAL",
            "ENSEMBLE_CORRELATION_ANALYSIS",
            "PORTFOLIO_GOVERNOR_TARGET_WEIGHTS_SHADOW_ONLY",
            "ZICO_INTENT_AND_LIFECYCLE_CONTROL",
            "ZLICE_ATTRIBUTION_LINEAGE_REPLAY_AUDIT",
        ],
        "constraints": {
            "zbot_execution_authority": False,
            "zico_strategy_generation": False,
            "lico_execution_authority": False,
            "zlice_execution_authority": False,
            "team_independence_required": True,
            "portfolio_governor_shadow_only": True,
        },
        **SAFETY,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "file_inventory.json").write_text(json.dumps([
        {key: row[key] for key in ("path", "suffix", "sha256", "imports", "executable")} for row in rows
    ], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = ["# Strategy11 Internal Synergy Audit", "", f"State: `{summary['state']}`", "", "## Missing capabilities"]
    lines.extend(f"- {name}" for name in missing)
    lines.extend(["", "## Recommended flow"])
    lines.extend(f"{i+1}. {name}" for i, name in enumerate(summary["recommended_flow"]))
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary["state"], "missing=", len(missing), "implemented=", len(implemented))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
