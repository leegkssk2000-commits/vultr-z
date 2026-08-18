from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.research import a1_ai_multicritic_review_v1 as core

SCHEMA = "zel.a1_ai_multicritic_review.v2"
_ORIGINAL_BUILD = core.build_semantic_payload


def build_semantic_payload(prep, prep_path):
    payload = _ORIGINAL_BUILD(prep, prep_path)
    payload["review_context"] = {
        "stage": "PRE_REPLAY_HYPOTHESIS_REVIEW",
        "baseline_metrics_semantics": "The supplied strategy metrics are frozen BASELINE FAILURE CONTEXT, not outcomes from the proposed candidate axis.",
        "decision_rule": "Do not REJECT or HOLD merely because baseline expectancy/PF/WR are poor. Judge whether the ONE proposed causal axis is independently evidenced, entry-time observable, non-leaky, non-duplicative, falsifiable, cost-plausible, and not disguised loss deletion or multi-axis tuning. Candidate economic efficacy is unknown until fresh prospective replay.",
        "candidate_economics_available": False,
        "candidate_replay_not_yet_run": True,
        "promotion_authority": False,
    }
    return payload


core.build_semantic_payload = build_semantic_payload


def self_test() -> int:
    rc = core.self_test()
    assert rc == 0
    fixture = {
        "strategy_id": "fixture",
        "state": "EARLY_AI_PREP_READY",
        "classification": "PRELIMINARY_NOT_TERMINAL",
        "baseline_mutated": False,
        "metrics": {"completed_trades": 9, "net_expectancy_bps": -10.0, "profit_factor": 0.2},
        "fingerprint": {"primary": "BASELINE_ECONOMIC_FAILURE", "secondary": []},
        "external_sources": [{"id": "S1", "tier": "paper", "identifier": "doi:test", "claim": "fixture"}],
        "top3_axes": [{
            "rank": 1,
            "axis": "ONE_AXIS",
            "mechanism": "one evidence-backed gate",
            "source_ids": ["S1"],
            "expected_metric_direction": {"net_expectancy": "UP"},
            "falsification": "reject if fresh replay does not improve frozen control",
            "required_data": ["ohlcv"],
            "forbidden_collateral_changes": ["fees", "stop", "target"],
        }],
    }
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "prep.json"
        p.write_text(json.dumps(fixture), encoding="utf-8")
        payload = build_semantic_payload(fixture, p)
        ctx = payload["review_context"]
        assert ctx["candidate_economics_available"] is False
        assert ctx["candidate_replay_not_yet_run"] is True
        assert "not outcomes" in ctx["baseline_metrics_semantics"]
        assert "Do not REJECT" in ctx["decision_rule"]
    print("PASS_A1_AI_MULTICRITIC_V2_BASELINE_SEMANTICS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prep-dir", type=Path, default=Path("backend/research/early_ai_prep"))
    ap.add_argument("--gemini-receipt", type=Path)
    ap.add_argument("--output", type=Path, default=Path("out/a1_ai_multicritic_review.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = core.run(args.prep_dir, args.output, args.gemini_receipt)
    result["schema_version"] = SCHEMA
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "reviewed_strategy_count": result["reviewed_strategy_count"],
        "provider_successful_strategy_counts": result["provider_successful_strategy_counts"],
        "bottlenecks": result["bottlenecks"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
