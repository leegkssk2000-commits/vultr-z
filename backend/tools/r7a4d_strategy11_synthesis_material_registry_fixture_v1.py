from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.research.strategy11_synthesis_material_registry_v1 import (
    SAFETY,
    SynthesisMaterialError,
    build_registry,
    canonical_sha,
    seal_material,
)


def expect_failure(code: str, fn) -> str:
    try:
        fn()
    except SynthesisMaterialError as exc:
        text = str(exc)
        if not text.startswith(code):
            raise AssertionError(f"EXPECTED_{code}_GOT_{text}") from exc
        return text
    raise AssertionError(f"EXPECTED_FAILURE_NOT_RAISED:{code}")


def evidence() -> dict:
    return {
        "ab_replay_pass": True,
        "duplicate_count": 0,
        "baseline_trades": 20,
        "candidate_trades": 18,
        "retention_pct": 90.0,
        "normal_loss_cap_pass": True,
        "stress_loss_cap_pass": True,
        "economic_gate_pass": True,
        "window_gate_pass": True,
        "pareto_non_dominated": True,
        "net_after_cost_delta": 0.42,
        "max_drawdown_delta": -0.18,
        "worst_loss_r_delta": 0.0,
        "positive_windows_delta": 1,
        "stress_worst_loss_r_delta": 0.0,
    }


def payload(material_id: str = "turtle.exit.mfe_trailing.v1") -> dict:
    row_evidence = evidence()
    return {
        "schema_version": "strategy11.synthesis_material.v1",
        "material_id": material_id,
        "base_strategy_id": "turtle_trend",
        "component_type": "EXIT_SKILL",
        "component_role": "EXIT",
        "semantic_axis": "MFE_TRAILING",
        "parameters": {"activation_r": 1.0, "atr_multiple": 2.0},
        "source_lineage": {
            "source_candidate_sha": "1" * 64,
            "source_proposal_sha": "2" * 64,
            "strategy_source_sha": "3" * 64,
            "data_sha": "4" * 64,
            "window_sha": "5" * 64,
            "source_manifest_sha": "6" * 64,
            "evidence_sha": canonical_sha(row_evidence),
        },
        "evidence": row_evidence,
        "compatibility": {
            "allowed_base_families": ["TREND", "BREAKOUT"],
            "incompatible_component_types": ["ADVISOR", "RISK_CONSTRAINT"],
            "incompatible_axes": ["SECOND_MFE_TRAILING"],
            "same_axis_allowed": False,
            "maximum_generation_per_axis_data": 2,
        },
        "state": "PASS_LEAF",
        "authority": dict(SAFETY),
        "metadata": {"fixture_only": True, "production_authority": False},
    }


def main() -> int:
    sealed = seal_material(payload())
    registry = build_registry([sealed])
    assert registry["schema_version"] == "strategy11.synthesis_material_registry.v1"
    assert registry["material_count"] == 1
    assert registry["pass_leaf_count"] == 1
    assert registry["eligible_material_ids"] == ["turtle.exit.mfe_trailing.v1"]
    assert registry["next"] == "BOUNDED_SYNTHESIS_CONSTRUCTOR"
    for key, expected in SAFETY.items():
        assert registry[key] == expected

    duplicate = payload("turtle.exit.mfe_trailing.alias")
    duplicate["material_sha"] = seal_material(duplicate)["material_sha"]
    expect_failure("DUPLICATE_MATERIAL_FINGERPRINT", lambda: build_registry([sealed, duplicate]))

    role_mismatch = payload("bad.role")
    role_mismatch["component_role"] = "FILTER"
    expect_failure("COMPONENT_ROLE_MISMATCH", lambda: seal_material(role_mismatch))

    unsafe = payload("bad.authority")
    unsafe["authority"]["runtime_bound"] = True
    expect_failure("AUTHORITY_MISMATCH", lambda: seal_material(unsafe))

    duplicate_trade = payload("bad.duplicate")
    duplicate_trade["evidence"]["duplicate_count"] = 1
    duplicate_trade["source_lineage"]["evidence_sha"] = canonical_sha(duplicate_trade["evidence"])
    expect_failure("PASS_LEAF_EVIDENCE_NOT_PASS", lambda: seal_material(duplicate_trade))

    private = payload("bad.private")
    private["parameters"]["api_key"] = "forbidden"
    expect_failure("PRIVATE_FIELD_FORBIDDEN", lambda: seal_material(private))

    stale_evidence_sha = payload("bad.evidence.sha")
    stale_evidence_sha["evidence"]["net_after_cost_delta"] = 9.0
    expect_failure("EVIDENCE_SHA_MISMATCH", lambda: seal_material(stale_evidence_sha))

    out = Path("artifacts/strategy11_synthesis_material_registry_v1")
    out.mkdir(parents=True, exist_ok=True)
    (out / "sealed_material.json").write_text(json.dumps(sealed, indent=2, sort_keys=True) + "\n")
    (out / "registry.json").write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")
    (out / "status.json").write_text(
        json.dumps(
            {
                "state": "PASS_SYNTHESIS_MATERIAL_REGISTRY_FIXTURE",
                "registry_sha": registry["registry_sha"],
                "fixture_only": True,
                "production_authority": False,
                **SAFETY,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(json.dumps({"state": "PASS_SYNTHESIS_MATERIAL_REGISTRY_FIXTURE", "registry_sha": registry["registry_sha"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
