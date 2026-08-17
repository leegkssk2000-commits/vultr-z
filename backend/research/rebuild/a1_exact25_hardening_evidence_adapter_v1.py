from __future__ import annotations

from typing import Any

from backend.research.rebuild.a1_exact25_survivor_gate_v1 import load_external_hardening_evidence
from backend.tools import zel_economic_hardening_gate_v1 as hardening_engine


def load_verified_hardening_evidence() -> dict[str, Any] | None:
    evidence = load_external_hardening_evidence()
    if evidence is None:
        return None
    out = dict(evidence)
    h4 = out.get("h4_receipt")
    if h4 is None:
        return out
    verified = hardening_engine.verify_embedded_receipt(
        h4,
        field="A1.survivor_gate.h4_receipt",
        expected_state="PASS_PLACEBO_NEGATIVE_CONTROLS",
        fixture_allowed=False,
    )
    if verified.get("schema_version") != "zel.economic_hardening.h4.receipt.v2":
        raise RuntimeError("A1_H4_RECEIPT_SCHEMA_INVALID")
    if verified.get("control") != "H4_PLACEBO_NEGATIVE_CONTROLS":
        raise RuntimeError("A1_H4_RECEIPT_CONTROL_INVALID")
    if verified.get("same_windows_costs_trade_budget_verified") is not True:
        raise RuntimeError("A1_H4_LINEAGE_OR_BUDGET_NOT_VERIFIED")
    results = verified.get("control_results")
    if not isinstance(results, dict) or not results:
        raise RuntimeError("A1_H4_CONTROL_RESULTS_MISSING")
    if any(not isinstance(row, dict) or row.get("pass") is not True for row in results.values()):
        raise RuntimeError("A1_H4_CONTROL_RESULT_NOT_PASS")
    out["negative_control"] = {
        "state": "PASS_DETERMINISTIC_REPLAY_RESULT",
        "p_value": max(float(row["p_value"]) for row in results.values()),
        "candidate_minus_control_ci_low_R": min(float(row["candidate_minus_control_ci_low_R"]) for row in results.values()),
        "equal_trade_budget": True,
        "identical_cost_model_sha": True,
        "identical_window_sha": True,
        "controls": {name: {"state": "PASS", "source_receipt_sha256": row.get("source_receipt_sha256")} for name, row in results.items()},
        "verified_h4_receipt_sha256": verified["receipt_sha256"],
        "verified_by_existing_hardening_engine": True,
    }
    return out
