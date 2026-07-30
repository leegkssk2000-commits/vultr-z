from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


def strict_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    policy_path = Path(args.policy)
    policy: Mapping[str, Any] = strict_json(policy_path)
    truth = policy["coverage_truth"]
    rules = policy["bounded_research_rules"]
    gemini = policy["gemini_delta_contract"]
    queue = list(policy["variant_queue"])
    inventory = policy["proven_feature_inventory"]

    assert inventory["ema_lengths_computed"] == [10, 20, 50, 100, 200]
    assert truth["all_indicators_tested_once_per_strategy"] is False
    assert truth["all_parameter_variants_tested"] is False
    assert truth["all_indicator_pairs_tested"] is False
    assert truth["selected_family_candidates_replayed"] is True
    assert truth["blind_cartesian_product_forbidden"] is True
    assert rules["single_semantic_axis_per_iteration"] is True
    assert int(rules["max_components_in_composite_gate"]) <= 2
    assert int(rules["max_candidates_per_strategy_iteration"]) <= 2
    assert int(rules["max_generations_per_strategy_axis_data_epoch"]) <= 2
    assert rules["independent_ab_parity_required"] is True
    assert int(rules["duplicate_trade_count_required"]) == 0
    assert gemini["enabled"] is True and gemini["free_only"] is True
    assert gemini["direct_video_required"] is True
    assert int(gemini["minimum_public_videos"]) >= 4
    assert int(gemini["minimum_independent_channels"]) >= 4
    assert gemini["gemini_output_is_hypothesis_only"] is True
    assert gemini["deterministic_replay_is_final_authority"] is True

    ids = [str(row["candidate_id"]) for row in queue]
    assert len(ids) == len(set(ids)), "DUPLICATE_INDICATOR_CANDIDATE_ID"
    allowed_status = {"PLANNED_UNTESTED", "FAMILY_EXPOSED_VARIANT_NOT_EXHAUSTED"}
    allowed_axes = {
        "ENTRY_CONTEXT_GATE", "CANDLE_STRUCTURE_GATE", "TREND_REGIME_GATE", "VOLATILITY_GATE",
        "VOLUME_FLOW_GATE", "MOMENTUM_GATE", "SESSION_GATE", "SYMBOL_EXCLUSION",
    }
    for row in queue:
        assert row["status"] in allowed_status, row
        assert row["axis"] in allowed_axes, row
        assert 1 <= len(row["components"]) <= int(rules["max_components_in_composite_gate"]), row
        assert row["compatible_families"], row

    status_counts = Counter(str(row["status"]) for row in queue)
    axis_counts = Counter(str(row["axis"]) for row in queue)
    output = {
        "schema_version": "1.0",
        "version": policy["version"],
        "state": "PASS_INDICATOR_SYNERGY_COVERAGE_PLAN",
        "blockers": [],
        "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        "coverage_sha256": stable_sha(queue),
        "ema_lengths_computed": inventory["ema_lengths_computed"],
        "ema_contexts_exposed_count": len(inventory["ema_contexts_exposed"]),
        "other_indicator_family_count": len(inventory["other_indicator_families_exposed"]),
        "variant_queue_count": len(queue),
        "status_counts": dict(sorted(status_counts.items())),
        "axis_counts": dict(sorted(axis_counts.items())),
        "all_indicators_tested_once_per_strategy": False,
        "all_indicator_pairs_tested": False,
        "selected_family_candidates_replayed": True,
        "blind_cartesian_product_forbidden": True,
        "gemini_delta_required": True,
        "next": policy["next"],
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "runtime_bound": False,
    }
    output["result_sha256"] = stable_sha(output)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "variant_queue.json").write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": output["state"], "queue": len(queue), "next": output["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
