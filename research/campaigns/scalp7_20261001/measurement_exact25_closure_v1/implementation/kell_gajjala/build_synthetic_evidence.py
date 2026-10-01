"""Rebuild only hand-drawn QA receipts; no historical loader or FULL caller."""

from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
OUT = Path(__file__).resolve().parent
SCOPE = "G4_MEASUREMENT_REPAIR_AND_EXACT25_CLOSURE_AFTER_PR1345_V1"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    (OUT / name).write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )


def main():
    helpers = runpy.run_path(str(ROOT / "tests/test_scalp7_kell_gajjala_closure_v1.py"))
    module = helpers["m"]
    source = (
        ROOT
        / "research/campaigns/scalp7_20260920/implementation_v1/source_package/G4_25_FINAL_SUFFICIENCY_AND_ENGINEERING_REVIEW_20260920.json"
    )
    bindings = {
        str(path.relative_to(ROOT)): sha(path)
        for path in [
            Path(module.__file__),
            ROOT / "tests/test_scalp7_kell_gajjala_closure_v1.py",
            ROOT / "backend/research/rebuild/scalp7_exact25_structure_v1.py",
            ROOT / "backend/research/rebuild/scalp7_exact25_execution_v1.py",
            ROOT / "backend/research/rebuild/scalp7_volume_contract_v1.py",
            source,
            Path(__file__),
        ]
    }
    contract = {
        "schema": module.VERSION,
        "scope_key": SCOPE,
        "catalog": module.catalog(),
        "rules": {model: module.rules(model) for model in module.MODEL_IDS},
        "source_bindings": bindings,
        "new_full_runs": 0,
        "original25_complete": False,
        "g4_complete": False,
        "source_exact": False,
        "new_economics": None,
        "execution_ready": "SYNTHETIC_ONLY",
        "historical_blockers": [
            "Authorized genuine partial-receipt caller, exact future identity/budget/freeze",
            "PIT genuine context, benchmark, minute-detail data, price-grid receipt bindings",
            "Gajjala observed BASE volume source-unit authority via common admission",
            "Venue/product costs, slippage evidence and known funding omission",
            "Broader Kell/Gajjala discretionary/source-original method remains unclaimed",
        ],
    }
    save("CONTRACT.json", contract)
    results = {}
    for model in module.MODEL_IDS:
        data = helpers["frame"](model)
        detail = helpers["minute_details"](data)
        config = helpers["config"](model)
        frozen_inputs = {
            "decision": data.to_dict("records"),
            "detail": detail.to_dict("records"),
            "contexts": {
                key: value.to_dict("records")
                for key, value in config["context_frames"].items()
            },
            "metadata": {
                key: value for key, value in config.items() if key != "context_frames"
            },
            "decision_attrs": data.attrs,
            "detail_attrs": detail.attrs,
        }
        result = helpers["run_one"](model, data, detail, config)
        execution = result["executions"][0]
        assert execution["state"] == "CLOSED" and len(result["ledger"]) == 3
        valuation = result["account"]["valuation"]
        results[model] = {
            "synthetic_input_sha256": module.digest(frozen_inputs),
            "plans": result["compiled"]["plans"],
            "states": result["statuses"],
            "ledger": result["ledger"],
            "management_events": execution["management_events"],
            "account_first": valuation["curve"][0],
            "account_last": valuation["curve"][-1],
            "sampled_drawdown_pct": valuation["max_drawdown_pct"],
            "account_prefix_only": result["account_prefix_only"],
            "new_full_runs": result["new_full_runs"],
        }
    save(
        "SYNTHETIC_EVIDENCE.json",
        {
            "schema": "KELL_GAJJALA_SYNTHETIC_RECEIPT_V1",
            "scope_key": SCOPE,
            "data_kind": "SYNTHETIC_FIXTURE",
            "construction": helpers["MANIFEST"],
            "source_bindings": bindings,
            "results": results,
            "new_economics": None,
            "new_full_runs": 0,
            "funding_status": "UNKNOWN_NOT_ZERO",
            "not_market_performance_evidence": True,
        },
    )
    print(
        json.dumps(
            {"models": list(results), "synthetic_receipts": "PASS", "new_full_runs": 0}
        )
    )


if __name__ == "__main__":
    main()
