from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.contracts.strategy11_strategy_proposal_contract_v1 import (
    ProposalContractError,
    contract_manifest,
    seal_proposal,
    validate_proposal,
)

OUT = Path("artifacts/strategy11_strategy_proposal_contract_v1")


def sha(char: str) -> str:
    return char * 64


def valid_fixture() -> dict:
    return {
        "schema_version": "strategy11.strategy_proposal.v1",
        "proposal_id": "alpha_combo.TIME54.F1F2F3",
        "strategy_id": "alpha_combo",
        "candidate_sha": sha("a"),
        "producer": {
            "team_lane": "ALPHA",
            "role": "LBOT",
            "independent_proposal": True,
        },
        "market": {
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            "timeframe": "15m",
            "side": "LONG",
            "regime": "MIXED",
            "session": "ALL",
        },
        "edge": {
            "trades": 40,
            "win_rate_pct": 57.5,
            "net_pct": 21.096558,
            "profit_factor": 4.422138,
            "payoff": 3.268536,
            "positive_windows": 3,
            "total_windows": 3,
            "retention_pct": 100.0,
        },
        "confidence": {
            "score": 0.82,
            "uncertainty": 0.18,
            "sample_quality": "MEDIUM",
            "oos_windows": 0,
        },
        "cost_envelope": {
            "fee_bps": 5.0,
            "slippage_bps": 4.0,
            "funding_8h_pct": 0.01,
            "latency_ms": 250.0,
            "stress_multiplier": 2.0,
            "capacity_notional_usdt": 100000.0,
        },
        "risk_envelope": {
            "max_drawdown_pct": 2.935907,
            "avg_loss_r": -0.25,
            "worst_loss_r": -0.575873,
            "stress_worst_loss_r": -0.713830,
            "joint_tail_budget_pct": 1.5,
            "max_exposure_pct": 20.0,
        },
        "lineage": {
            "strategy_source_sha": sha("1"),
            "candidate_config_sha": sha("2"),
            "data_sha": sha("3"),
            "window_sha": sha("4"),
            "source_manifest_sha": sha("5"),
            "run_id": "30426054379",
            "artifact": "s11-alpha-overfit-sentinel-v1-30426054379-attempt-1",
            "data_epoch": "F1_F2_F3",
        },
        "proposal_state": "REQUEST_EVALUATION",
        "reason_codes": ["PARETO_CANDIDATE", "OVERFIT_SENTINEL_PASS"],
        "authority": {
            "stage": "RESEARCH",
            "research_only": True,
            "promotion_authority": False,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
            "protected_mutations": 0,
        },
        "metadata": {
            "exit_policy": "TIME54",
            "classification": "UNCLASSIFIED",
            "source": "fixture",
        },
    }


def expect_failure(name: str, payload: dict, code: str) -> dict:
    try:
        validate_proposal(payload)
    except ProposalContractError as exc:
        text = str(exc)
        if not text.startswith(code):
            raise AssertionError(f"{name}: expected {code}, got {text}") from exc
        return {"name": name, "status": "PASS_REJECTED", "code": text}
    raise AssertionError(f"{name}: invalid payload accepted")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    sealed = seal_proposal(valid_fixture())
    assert validate_proposal(sealed) == sealed

    reordered = dict(reversed(list(valid_fixture().items())))
    assert seal_proposal(reordered)["proposal_sha"] == sealed["proposal_sha"]

    invalid_execution = copy.deepcopy(sealed)
    invalid_execution["authority"]["execution_allowed"] = True
    invalid_execution = seal_proposal({**invalid_execution, "authority": {**invalid_execution["authority"], "execution_allowed": False}})
    invalid_execution["authority"]["execution_allowed"] = True

    private_field = copy.deepcopy(sealed)
    private_field["metadata"]["api_key"] = "forbidden"

    tampered = copy.deepcopy(sealed)
    tampered["edge"]["net_pct"] += 1.0

    non_independent = copy.deepcopy(sealed)
    non_independent["producer"]["independent_proposal"] = False
    non_independent.pop("proposal_sha", None)

    tests = [
        expect_failure("execution_authority", invalid_execution, "EXECUTION_FORBIDDEN"),
        expect_failure("private_field", private_field, "PRIVATE_FIELD_FORBIDDEN"),
        expect_failure("sha_tamper", tampered, "PROPOSAL_SHA_MISMATCH"),
        expect_failure("team_independence", non_independent, "TEAM_INDEPENDENCE_REQUIRED"),
    ]

    manifest = contract_manifest()
    summary = {
        "state": "PASS_COMMON_STRATEGY_OUTPUT_CONTRACT",
        "schema_version": sealed["schema_version"],
        "proposal_sha": sealed["proposal_sha"],
        "valid_roundtrip": True,
        "canonical_order_invariant": True,
        "negative_fixture_count": len(tests),
        "negative_fixtures": tests,
        "next": "GLOBAL_CANDIDATE_CLASSIFIER",
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "runtime_bound": False,
    }
    (OUT / "valid_proposal.json").write_text(json.dumps(sealed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "contract_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(summary["state"], sealed["proposal_sha"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
