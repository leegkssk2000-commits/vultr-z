from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.research.strategy11_component_attribution_v1 import attribute_components
from backend.research.strategy11_synthesis_material_registry_v1 import SAFETY, canonical_sha
from backend.research.strategy11_synthesis_sealer_v1 import (
    SynthesisSealerError,
    seal_synthesis,
)
from backend.tools.r7a4d_strategy11_component_attribution_fixture_v1 import attribution_input


def expect_failure(code: str, fn) -> str:
    try:
        fn()
    except SynthesisSealerError as exc:
        text = str(exc)
        if not text.startswith(code):
            raise AssertionError(f"EXPECTED_{code}_GOT_{text}") from exc
        return text
    raise AssertionError(f"EXPECTED_FAILURE_NOT_RAISED:{code}")


def policy() -> dict:
    return {
        "policy_id": "fixture-synthesis-sealer-v1",
        "min_trades": 10,
        "min_profit_factor": 1.1,
        "min_payoff": 1.0,
        "min_net_after_cost_r": 0.5,
        "max_drawdown_r": 3.0,
        "min_avg_loss_r": -0.75,
        "min_worst_loss_r": -0.75,
        "min_stress_worst_loss_r": -0.75,
        "min_positive_windows": 2,
        "min_net_retention_vs_w2_pct": 60.0,
        "max_drawdown_expansion_vs_w2_pct": 50.0,
        "require_ab_parity": True,
        "require_duplicate_zero": True,
    }


def metrics(trades: int, net: float, pf: float, payoff: float, dd: float) -> dict:
    return {
        "trades": trades,
        "net_after_cost_r": net,
        "profit_factor": pf,
        "payoff": payoff,
        "max_drawdown_r": dd,
        "avg_loss_r": -0.45,
        "worst_loss_r": -0.70,
        "stress_worst_loss_r": -0.74,
        "positive_windows": 3,
        "total_windows": 3,
    }


def receipt(
    stage: str,
    candidate_id: str,
    candidate_sha: str,
    *,
    data_sha: str,
    window_sha: str,
    manifest_sha: str,
    run_id: str,
    row_metrics: dict,
) -> dict:
    value = {
        "schema_version": "strategy11.synthesis_confirmation_receipt.v1",
        "stage": stage,
        "candidate_id": candidate_id,
        "candidate_sha": candidate_sha,
        "config_sha": candidate_sha,
        "lineage": {
            "data_sha": data_sha,
            "window_sha": window_sha,
            "source_manifest_sha": manifest_sha,
            "replay_run_id": run_id,
        },
        "ab_parity_pass": True,
        "duplicate_count": 0,
        "metrics": row_metrics,
        "authority": dict(SAFETY),
    }
    value["receipt_sha"] = canonical_sha(value)
    return value


def reseal(value: dict) -> None:
    value.pop("receipt_sha", None)
    value["receipt_sha"] = canonical_sha(value)


def fixture_input() -> dict:
    attr_input = attribution_input()
    attr_result = attribute_components(attr_input)
    candidate = attr_input["factorial_input"]["candidate"]
    confirmations = [
        receipt(
            "W3",
            candidate["candidate_id"],
            candidate["candidate_sha"],
            data_sha="d" * 64,
            window_sha="e" * 64,
            manifest_sha="f" * 64,
            run_id="fixture-w3-run-1",
            row_metrics=metrics(18, 2.0, 1.48, 1.30, 1.5),
        ),
        receipt(
            "NEW_SEALED",
            candidate["candidate_id"],
            candidate["candidate_sha"],
            data_sha="7" * 64,
            window_sha="8" * 64,
            manifest_sha="9" * 64,
            run_id="fixture-new-sealed-run-1",
            row_metrics=metrics(16, 1.8, 1.40, 1.24, 1.6),
        ),
    ]
    return {
        "schema_version": "strategy11.synthesis_sealer.input.v1",
        "attribution_input": attr_input,
        "attribution_result": attr_result,
        "confirmations": confirmations,
        "policy": policy(),
        "authority": dict(SAFETY),
    }


def main() -> int:
    payload = fixture_input()
    result = seal_synthesis(payload)
    assert result["state"] == "PASS_SYNTHESIS_NEW_SEALED_WAIT_CLASSIFIER"
    assert result["classification_ready"] is True
    assert result["next"] == "GLOBAL_CANDIDATE_CLASSIFIER"
    seal = result["synthesis_seal"]
    assert seal["seal_state"] == "NEW_SEALED_WAIT_CLASSIFIER"
    assert seal["classification_ready"] is True
    assert seal["promotion_authority"] is False
    assert len(seal["component_lineage"]) == 2
    assert len({row["data_sha"] for row in result["stage_lineages"].values()}) == 4
    assert len({row["window_sha"] for row in result["stage_lineages"].values()}) == 4
    for key, expected in SAFETY.items():
        assert result[key] == expected
        assert seal[key] == expected

    overlap = fixture_input()
    w3 = next(row for row in overlap["confirmations"] if row["stage"] == "W3")
    new_sealed = next(row for row in overlap["confirmations"] if row["stage"] == "NEW_SEALED")
    new_sealed["lineage"]["data_sha"] = w3["lineage"]["data_sha"]
    reseal(new_sealed)
    expect_failure("STAGE_LINEAGE_OVERLAP", lambda: seal_synthesis(overlap))

    config_mismatch = fixture_input()
    config_mismatch["confirmations"][0]["config_sha"] = "0" * 64
    reseal(config_mismatch["confirmations"][0])
    expect_failure("RECEIPT_CONFIG_SHA_MISMATCH", lambda: seal_synthesis(config_mismatch))

    weak = fixture_input()
    weak_receipt = next(row for row in weak["confirmations"] if row["stage"] == "NEW_SEALED")
    weak_receipt["metrics"]["net_after_cost_r"] = 0.3
    reseal(weak_receipt)
    weak_result = seal_synthesis(weak)
    assert weak_result["state"] == "HOLD_SYNTHESIS_SEAL"
    assert weak_result["classification_ready"] is False
    assert weak_result["synthesis_seal"] is None
    assert any("NEW_SEALED:NET_LOW" == code for code in weak_result["blockers"])
    assert any("NEW_SEALED:W2_NET_RETENTION_LOW" == code for code in weak_result["blockers"])

    attr_tamper = fixture_input()
    attr_tamper["attribution_result"]["attribution_sha"] = "1" * 64
    expect_failure("ATTRIBUTION_SHA_MISMATCH", lambda: seal_synthesis(attr_tamper))

    receipt_tamper = fixture_input()
    receipt_tamper["confirmations"][0]["metrics"]["net_after_cost_r"] = 99.0
    expect_failure("RECEIPT_SHA_MISMATCH", lambda: seal_synthesis(receipt_tamper))

    out = Path("artifacts/strategy11_synthesis_sealer_v1")
    out.mkdir(parents=True, exist_ok=True)
    (out / "input.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    (out / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    status = {
        "state": "PASS_SYNTHESIS_SEALER_FIXTURE",
        "sealer_sha": result["sealer_sha"],
        "seal_sha": result["synthesis_seal"]["seal_sha"],
        "fixture_only": True,
        "production_authority": False,
        **SAFETY,
    }
    (out / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
