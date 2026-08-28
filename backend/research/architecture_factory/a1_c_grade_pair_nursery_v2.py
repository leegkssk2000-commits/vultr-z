#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_c_grade_pair_nursery_v1 as v1

SCHEMA = "zel.a1.c_grade_pair_nursery.generator_contract.v2"


def prompt_v2(pairs: list[dict[str, Any]], evidence: list[dict[str, Any]], readiness: Mapping[str, Any]) -> str:
    allowed = sorted(k for k, raw in readiness.items() if isinstance(raw, Mapping) and raw.get("ready") is True)
    evidence_ids = [str(x.get("id")) for x in evidence if x.get("id")]
    contract = {
        "candidates": [{
            "candidate_id": "EXACT pair_id",
            "mode": "REPAIR",
            "strategy_id": "EXACT host_strategy_id",
            "architecture_family": "existing host family plus one donor mechanism",
            "changed_axis": "EXACT changed_axis from pair",
            "mechanism": "causal economic mechanism",
            "payer": "who/what pays",
            "entry_event": "entry-time observable event",
            "direction_rule": "long/short/both rule",
            "native_horizon": "natural untuned horizon",
            "regime_owner": "when mechanism owns risk",
            "invalidation": "causal invalidation",
            "exit_logic": "causal exit logic",
            "time_stop_rationale": "why time stop matches mechanism",
            "turnover_cost_budget": "why expected move can clear 14bps",
            "required_sources": ["ONLY replay-ready source names"],
            "evidence_ids": ["1 to 3 IDs copied exactly from EVIDENCE_IDS"],
            "expected_move_cost_multiple_target": 2.0,
            "falsification": "bounded prospective kill test",
            "forbidden_changes": ["fees", "best-horizon selection", "post-outcome loss deletion", "donor numeric threshold copy"],
            "why_distinct": "why the donor mechanism adds a distinct causal axis",
            "executable_spec": {
                "bar_interval": "5m|15m|30m|1h|4h|1d",
                "features": [{"name": "feature_name", "formula": "deterministic formula using only required_sources"}],
                "entry_rule": "deterministic boolean rule with fixed provenance, no outcome-tuned threshold",
                "side_rule": "deterministic side rule",
                "exit_rule": "deterministic causal exit rule",
                "max_hold_bars": 48,
                "entry_timing": "next-bar/open or explicitly causal timing",
                "cost_model": "14bps verified development cost plus supported source costs",
                "development_data_rule": "fixed pre-boundary development replay only; no holdout",
                "parameter_provenance": "host native constants or mechanism-defined constants only; no sweep"
            }
        }]
    }
    return (
        "You are an EXECUTABLE C-grade material nursery. Return JSON only. This is not Top5 repair and not parameter optimization. "
        "For each supplied CxC pair emit AT MOST ONE candidate, and emit zero for a pair if you cannot satisfy every field below without inventing evidence. "
        "HARD IDENTITY: candidate_id=pair_id EXACTLY; mode=REPAIR EXACTLY; strategy_id=host_strategy_id EXACTLY; changed_axis=pair.changed_axis EXACTLY. "
        "Preserve host identity. Import exactly ONE qualitative donor_gene mechanism. Never copy donor numeric thresholds. Never add a second mechanism. "
        "required_sources MUST be non-empty and a subset of REPLAY_READY_SOURCES. evidence_ids MUST contain 1-3 IDs copied exactly from EVIDENCE_IDS. "
        "Every emitted candidate MUST include every generic architecture field AND a deterministic executable_spec. Numeric values are allowed only when inherited from host native constants or structurally defined by the mechanism; no threshold sweep, no best-horizon selection, no outcome-selected filtering. "
        "Same 14bps development economics will kill the child unless it achieves >=12T, Net PnL>0, Net expectancy>0, PF>1, payoff>=1, finite DD. Do not claim it passes; only emit an executable hypothesis. "
        "CONTRACT=" + json.dumps(contract, sort_keys=True, separators=(",", ":")) +
        "\nREPLAY_READY_SOURCES=" + json.dumps(allowed, separators=(",", ":")) +
        "\nEVIDENCE_IDS=" + json.dumps(evidence_ids, separators=(",", ":")) +
        "\nSOURCE_READINESS=" + json.dumps(readiness, sort_keys=True, separators=(",", ":")) +
        "\nPAIRS=" + json.dumps(pairs, sort_keys=True, separators=(",", ":")) +
        "\nEVIDENCE=" + json.dumps(evidence, sort_keys=True, separators=(",", ":"))
    )


def run(output: Path, *, no_ai: bool = False) -> dict[str, Any]:
    old_prompt = v1.prompt
    v1.prompt = prompt_v2
    try:
        result = v1.run(output, no_ai=no_ai)
    finally:
        v1.prompt = old_prompt
    result["generator_contract_schema"] = SCHEMA
    result["generator_contract_hardened"] = True
    result["invalid_generation_is_auditable_hold_not_workflow_failure"] = True
    # Recompute receipt after wrapper annotations.
    result["receipt_sha256"] = v1.stable({k: val for k, val in result.items() if k != "receipt_sha256"})
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    evidence = [{"id": "F1", "claim": "x"}]
    p = [{"pair_id":"CPAIR__a__X__b__g","host_strategy_id":"a","host_family":"trend","donor_strategy_id":"b","donor_gene":"g","changed_axis":"C_PAIR__B__G__ONLY"}]
    text = prompt_v2(p, evidence, {"ohlcv":{"ready":True},"funding":{"ready":False}})
    for required in ("mode=REPAIR EXACTLY", "candidate_id=pair_id EXACTLY", "executable_spec", "evidence_ids", "REPLAY_READY_SOURCES"):
        assert required in text
    assert '"ohlcv"' in text
    print("PASS_A1_C_GRADE_PAIR_NURSERY_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_c_grade_pair_nursery_v2.json"))
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    r = run(a.out, no_ai=a.no_ai)
    print(json.dumps({"state":r["state"],"c":r["eligible_c_material_count"],"pairs":r["pair_count_this_run"],"upgrades":r["c_to_b_upgrade_count"],"provider":r["provider"],"next":r["next"],"receipt":r["receipt_sha256"]}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
