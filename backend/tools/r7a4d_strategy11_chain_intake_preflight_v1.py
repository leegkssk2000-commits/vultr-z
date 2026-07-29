from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
}

CHAIN = [
    "backend/contracts/strategy11_strategy_proposal_contract_v1.py",
    "backend/research/strategy11_global_candidate_classifier_v1.py",
    "backend/research/strategy11_ensemble_correlation_analyzer_v1.py",
    "backend/research/strategy11_portfolio_governor_v1.py",
    "backend/research/strategy11_attribution_ledger_v1.py",
    "backend/contracts/strategy11_role_boundary_zbot_zico_lico_zlice_v1.py",
    "backend/research/strategy11_model_risk_governance_v1.py",
]

REQUIRED_INTAKE = {
    "proposal": ["strategy_id", "candidate_sha", "edge", "confidence", "cost_envelope", "risk_envelope", "lineage"],
    "classification_evidence": ["w1", "w2", "w3", "new_sealed", "dsr_pass", "bh_fdr_pass", "regime_coverage_pass"],
    "portfolio": ["correlation", "overlap", "joint", "capacity", "turnover", "rollback"],
    "attribution": ["source_row_sha", "strategy_id", "regime", "net_pnl_r"],
    "model_risk": ["drift", "calibration", "error_budget", "rollback"],
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    ast.parse(text)
    return {"path": str(path), "sha256": sha(path), "bytes": len(text.encode("utf-8"))}


def main() -> int:
    root = Path(".")
    missing = [path for path in CHAIN if not (root / path).is_file()]
    evidence = [inspect(root / path) for path in CHAIN if (root / path).is_file()]

    w1_paths = [
        root / "backend/tools/r7a4d_strategy11_alpha_primary_w1_multiobjective_v1.py",
        root / "backend/tools/r7a4d_strategy11_data_wait_pool_compute_v1.py",
    ]
    w1_available = [inspect(path) for path in w1_paths if path.is_file()]

    # The seven modules exist, but no master executable currently consumes one real
    # W1 artifact and passes it through every stage. Keep this fail-closed until an
    # adapter supplies all fields from explicit source artifacts instead of guesses.
    blockers = []
    if missing:
        blockers.append("CHAIN_MODULE_MISSING")
    if len(w1_available) != len(w1_paths):
        blockers.append("W1_PRODUCER_NOT_ON_MASTER")
    blockers.append("REAL_ARTIFACT_CHAIN_ADAPTER_MISSING")
    blockers.append("CONFIDENCE_SOURCE_CONTRACT_MISSING")
    blockers.append("LICO_COST_CAPACITY_SOURCE_CONTRACT_MISSING")
    blockers.append("DSR_BH_FDR_CONCENTRATION_ADAPTER_MISSING")
    blockers.append("SOURCE_LEDGER_HISTORY_HEAD_MISSING")

    result = {
        "schema_version": "strategy11.chain_intake_preflight.v1",
        "status": "HOLD_CHAIN_INTAKE_PREFLIGHT",
        "chain_module_count": len(evidence),
        "chain_modules": evidence,
        "w1_producers_on_master": w1_available,
        "required_intake_groups": REQUIRED_INTAKE,
        "blockers": blockers,
        "next": "ADD_SOURCE_BOUND_W1_TO_COMMON_PROPOSAL_ADAPTER_AFTER_W1_PASS",
        "runtime_bound": False,
        **SAFETY,
    }
    out = root / "artifacts/strategy11_chain_intake_preflight_v1"
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(result["status"], "blockers=", len(blockers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
