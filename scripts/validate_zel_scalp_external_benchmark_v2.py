#!/usr/bin/env python3
"""Validate the profitability-first external benchmark without granting authority."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PATH = Path("backend/research/zel_scalp_external_benchmark_v2.json")


def fail(message: str) -> None:
    raise ValueError(message)


def validate(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != "zel.scalp.external_benchmark.v2":
        fail("unexpected schema")
    if payload.get("state") != "PASS_BENCHMARK_EXPANDED_NO_ARCHITECTURE_OVERRIDE":
        fail("benchmark not sealed")

    policy = payload.get("source_policy", {})
    for key in ("marketing_claims_are_evidence", "popularity_is_evidence", "public_backtest_can_promote"):
        if policy.get(key) is not False:
            fail(f"{key} must be false")

    sources = payload.get("accepted_sources", [])
    if len(sources) < 10:
        fail("insufficient accepted source breadth")
    ids = [source.get("id") for source in sources]
    if len(ids) != len(set(ids)):
        fail("duplicate source id")
    tiers = {int(source.get("tier", 0)) for source in sources}
    if not {1, 2}.issubset(tiers):
        fail("tier 1 and tier 2 evidence both required")
    kinds = {source.get("kind") for source in sources}
    required_kinds = {"exchange_documentation", "framework_documentation", "primary_research", "open_source_public_strategy"}
    if not required_kinds.issubset(kinds):
        fail("required source classes missing")
    for source in sources:
        for field in ("id", "tier", "kind", "url", "accessed_date", "finding", "transfer"):
            if not source.get(field):
                fail(f"source missing {field}")

    coverage = payload.get("search_coverage", {})
    if "YouTube" not in " ".join(coverage.get("video", [])):
        fail("YouTube search coverage missing")
    if "Reddit" not in " ".join(coverage.get("community", [])):
        fail("Reddit search coverage missing")
    disposition = coverage.get("community_video_disposition", "")
    if "No community or video claim was accepted" not in disposition:
        fail("community/video evidence boundary missing")

    effect = payload.get("architecture_effect", {})
    if effect.get("selected_strategy_id") != "intraday_pullback_reclaim_v1":
        fail("selected architecture changed")
    if effect.get("decision") != "RETAIN_SEALED_ARCHITECTURE":
        fail("unexpected architecture decision")
    for key in ("true_microstructure_permitted", "maker_fill_assumption_permitted", "new_filter_addition_permitted_before_base_positive"):
        if effect.get(key) is not False:
            fail(f"{key} must remain false")

    authority = payload.get("authority", {})
    if authority.get("selection_authority") is not False or authority.get("promotion_authority") is not False:
        fail("selection/promotion authority opened")
    if authority.get("execution_authority") != "NONE" or authority.get("order_authority") != "BLOCKED":
        fail("execution/order authority changed")
    if int(authority.get("protected_mutations", -1)) != 0:
        fail("protected mutation detected")
    if authority.get("action") != "hold":
        fail("action must remain hold")

    return {
        "state": "PASS",
        "sources": len(sources),
        "tiers": sorted(tiers),
        "selected_strategy_id": effect["selected_strategy_id"],
        "architecture_decision": effect["decision"],
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "protected_mutations": 0,
        "action": "hold",
    }


def main() -> int:
    try:
        payload = json.loads(PATH.read_text(encoding="utf-8"))
        result = validate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"state": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
