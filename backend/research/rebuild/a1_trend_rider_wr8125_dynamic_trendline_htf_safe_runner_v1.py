#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_trend_rider_wr8125_dynamic_trendline_htf_attribution_v1 as inner

SCHEMA = "zel.a1.trend_rider.wr8125.dynamic_trendline_htf.safe_runner.v1"


def run(out: Path) -> dict:
    try:
        return inner.run(out)
    except RuntimeError as exc:
        msg = str(exc)
        if not msg.startswith("FROZEN_24_UNAVAILABLE:"):
            raise
        observed = int(msg.rsplit(":", 1)[1])
        result = {
            "schema_version": SCHEMA,
            "state": "HOLD_FROZEN_24_UNAVAILABLE",
            "strategy_id": "trend_rider",
            "canonical_head": "trend_rider_wr80_us_chase_cooling_v1",
            "authority_match": False,
            "observed_current_completed_trades": observed,
            "required_frozen_trade_count": inner.FROZEN_COUNT,
            "base_wr8125": None,
            "strict_candidate_count": 0,
            "recommended_discovery_child": None,
            "numeric_threshold_sweep": False,
            "creator_numeric_threshold_imported": False,
            "creator_performance_claim_imported": False,
            "outcome_used_at_runtime": False,
            "development_only": True,
            "fresh_oos_required": True,
            "parent_incumbent_mutated": False,
            "next": "RESTORE_OR_BIND_AUTHORITATIVE_FROZEN_24_RECEIPT_BEFORE_DYNAMIC_HTF_ABLATION",
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "protected_mutations": 0,
        }
        result["receipt_sha256"] = ev.stable_sha(result)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    result = run(args.out)
    print(json.dumps({
        "state": result.get("state"),
        "authority_match": result.get("authority_match"),
        "observed_current_completed_trades": result.get("observed_current_completed_trades"),
        "receipt": result.get("receipt_sha256"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
