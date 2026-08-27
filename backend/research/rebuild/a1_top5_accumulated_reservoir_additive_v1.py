#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild.a1_top5_additive_entry_union_v1 import evaluate, trade_key

SCHEMA = "zel.a1.top5.accumulated_reservoir_additive.v1"
ROOT = Path(__file__).resolve().parents[3]
PARENTS = {
    "keltner_trend": ROOT / "backend/research/rebuild/a1_keltner_trend_highwr_frozen_parent_v1.json",
    "supertrend_pullback": ROOT / "backend/research/rebuild/a1_supertrend_pullback_highwr_frozen_parent_v1.json",
}
SOURCES = {
    "keltner_trend": "keltner_trend_exact_parent.json",
    "supertrend_pullback": "supertrend_pullback_exact_parent.json",
}

# Categorical, symmetric and outcome-blind. Do not add a value because it won historically.
FAMILIES = [
    ("APAC_OPEN_POINT", [0]),
    ("EU_OPEN_POINT", [8]),
    ("US_OPEN_POINT", [16]),
    ("APAC_OPEN_3H", [0, 1, 2]),
    ("EU_OPEN_3H", [8, 9, 10]),
    ("US_OPEN_3H", [16, 17, 18]),
]


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def signal_hour_utc(trade: Mapping[str, Any]) -> int:
    return datetime.fromtimestamp(int(trade["signal_ts"]) / 1000.0, tz=timezone.utc).hour


def run(artifact_dir: Path, out: Path) -> dict[str, Any]:
    by_strategy: dict[str, Any] = {}
    for strategy_id, source_name in SOURCES.items():
        parent = read(PARENTS[strategy_id])
        broad = read(artifact_dir / source_name)
        if broad.get("strategy_id") != strategy_id:
            raise RuntimeError(f"SOURCE_STRATEGY_MISMATCH:{strategy_id}")

        parent_keys = {trade_key(x) for x in parent.get("trades") or []}
        source_trades = [dict(x) for x in broad.get("trades") or []]
        reservoir = [x for x in source_trades if trade_key(x) not in parent_keys]
        if len(source_trades) != len(parent_keys) + len(reservoir):
            raise RuntimeError(f"PARENT_RESERVOIR_PARTITION_MISMATCH:{strategy_id}")

        candidates = []
        for name, hours in FAMILIES:
            lane = [x for x in reservoir if signal_hour_utc(x) in hours]
            if not lane:
                continue
            receipt = evaluate(parent, {"strategy_id": strategy_id, "trades": lane})
            candidates.append({
                "rule": name,
                "signal_hour_utc_in": hours,
                "source_trade_count": len(lane),
                "development_pass": receipt["state"] == "PASS_ADD_ONLY_ENTRY_LANE",
                "additive_receipt": receipt,
            })

        passes = [x for x in candidates if x["development_pass"]]
        passes.sort(
            key=lambda x: (
                x["additive_receipt"]["added_only_trade_count"],
                x["additive_receipt"]["combined_metrics"]["net_expectancy_bps"],
                x["additive_receipt"]["combined_metrics"]["net_pnl_bps"],
            ),
            reverse=True,
        )
        best = passes[0] if passes else None
        by_strategy[strategy_id] = {
            "source_trade_count": len(source_trades),
            "frozen_parent_trade_count": len(parent_keys),
            "added_only_reservoir_trade_count": len(reservoir),
            "parent_overlap_removed": len(parent_keys),
            "candidate_rules": candidates,
            "strict_pass_count": len(passes),
            "best_development_candidate": best,
            "state": "PASS_DEVELOPMENT_RESERVOIR_CANDIDATE_FRESH_REQUIRED" if best else "HOLD_NO_STRICT_RESERVOIR_CANDIDATE",
        }

    result = {
        "schema_version": SCHEMA,
        "state": "PASS_DEVELOPMENT_ONLY_FRESH_REQUIRED",
        "mode": "FROZEN_PARENT_PLUS_ACCUMULATED_T_RESERVOIR",
        "rule_policy": {
            "outcome_blind_runtime": True,
            "post_outcome_trade_cherry_pick_forbidden": True,
            "numeric_threshold_sweep": False,
            "predeclared_categorical_families": [
                {"name": name, "signal_hour_utc_in": hours} for name, hours in FAMILIES
            ],
            "parent_match_required_pct": 100.0,
            "fresh_confirmation_required_before_promotion": True,
        },
        "by_strategy": by_strategy,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
        "action": "hold",
    }
    result["receipt_sha256"] = stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("out/a1_top5_accumulated_reservoir_additive_v1.json"))
    args = ap.parse_args()
    result = run(args.artifact_dir, args.out)
    brief = {}
    for strategy_id, value in result["by_strategy"].items():
        best = value["best_development_candidate"]
        brief[strategy_id] = {
            "reservoir_t": value["added_only_reservoir_trade_count"],
            "best_rule": None if best is None else best["rule"],
            "combined_t": None if best is None else best["additive_receipt"]["combined_trade_count"],
            "combined_metrics": None if best is None else best["additive_receipt"]["combined_metrics"],
        }
    print("A1_TOP5_ACCUMULATED_RESERVOIR=" + json.dumps(brief, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
