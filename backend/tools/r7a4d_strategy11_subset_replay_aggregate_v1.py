from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

VERSION = "R7A4D_STRATEGY11_SUBSET_REPLAY_AGGREGATE_V1"
SOURCE_REPLAY_VERSION = "R7A4D_STRATEGY11_MULTIMODAL_L090_REPLAY_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def metric(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    result = float(value)
    return result if math.isfinite(result) else default


def assert_safety(value: Mapping[str, Any], name: str) -> None:
    if value.get("promotion_authority") is not False:
        raise ValueError(f"PROMOTION_AUTHORITY_UNSAFE:{name}")
    if int(value.get("protected_mutations") or 0) != 0:
        raise ValueError(f"PROTECTED_MUTATIONS_UNSAFE:{name}")
    if value.get("execution_allowed") is not False:
        raise ValueError(f"EXECUTION_ALLOWED_UNSAFE:{name}")
    if value.get("order_authority") != "BLOCKED":
        raise ValueError(f"ORDER_AUTHORITY_UNSAFE:{name}")


def winner_row(summary: Mapping[str, Any]) -> Mapping[str, Any]:
    winner = summary.get("winner")
    variants = summary.get("variants")
    if not isinstance(variants, list):
        raise ValueError(f"VARIANTS_REQUIRED:{summary.get('strategy_id')}")
    for row in variants:
        if isinstance(row, Mapping) and row.get("variant_id") == winner:
            return row
    raise ValueError(f"WINNER_ROW_MISSING:{summary.get('strategy_id')}:{winner}")


def collect_summaries(root: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("summary.json")):
        payload = read_json(path)
        strategy_id = payload.get("strategy_id")
        if not strategy_id or payload.get("version") != SOURCE_REPLAY_VERSION:
            continue
        strategy_id = str(strategy_id)
        if strategy_id in rows:
            raise ValueError(f"DUPLICATE_STRATEGY_SUMMARY:{strategy_id}")
        assert_safety(payload, f"summary:{strategy_id}")
        parity_rows = payload.get("variants") or []
        for candidate in parity_rows:
            if not isinstance(candidate, Mapping):
                raise ValueError(f"VARIANT_OBJECT_REQUIRED:{strategy_id}")
            parity = candidate.get("parity") or {}
            if parity.get("state") != "PASS" or int(parity.get("duplicate_trade_count") or 0) != 0:
                raise ValueError(f"REPLAY_PARITY_FAIL:{strategy_id}:{candidate.get('variant_id')}")
        rows[strategy_id] = payload
    return rows


def aggregate(replay_root: Path, accepted_plan: Mapping[str, Any]) -> dict[str, Any]:
    assert_safety(accepted_plan, "accepted_plan")
    plan_rows = accepted_plan.get("rows")
    if not isinstance(plan_rows, list):
        raise ValueError("ACCEPTED_PLAN_ROWS_REQUIRED")
    expected = [str(row.get("strategy_id")) for row in plan_rows if isinstance(row, Mapping)]
    if not expected or len(expected) != len(set(expected)):
        raise ValueError("ACCEPTED_PLAN_STRATEGY_SET_INVALID")
    found = collect_summaries(replay_root)
    if set(found) != set(expected):
        missing = sorted(set(expected) - set(found))
        extra = sorted(set(found) - set(expected))
        raise ValueError(f"SUBSET_AGGREGATE_STRATEGY_MISMATCH:missing={missing}:extra={extra}")

    candidates = [row for row in found.values() if row.get("state") == "PASS_L090_RESEARCH_CANDIDATE"]
    candidates.sort(
        key=lambda row: (
            metric(winner_row(row).get("net_return_pct_sum")),
            metric(winner_row(row).get("net_profit_factor")),
            metric(winner_row(row).get("payoff_ratio")),
            -metric(winner_row(row).get("max_drawdown_pct"), math.inf),
        ),
        reverse=True,
    )
    source_rows = [
        {
            "strategy_id": strategy_id,
            "summary_sha": canonical_sha(found[strategy_id]),
            "state": found[strategy_id]["state"],
            "tested_candidate_ids": list(found[strategy_id].get("tested_candidate_ids") or []),
            "winner": found[strategy_id].get("winner"),
        }
        for strategy_id in sorted(found)
    ]
    final = {
        "schema_version": "strategy11.subset_replay_aggregate.v1",
        "version": VERSION,
        "source_replay_version": SOURCE_REPLAY_VERSION,
        "capability_marker": "MULTIMODAL_RESCUE_L090_REPLAY_SUBSET_AGGREGATE",
        "state": "PASS_MULTIMODAL_L090_REPLAY_COMPLETE",
        "expected_strategy_ids": sorted(expected),
        "strategy_count": len(found),
        "source_plan_strategy_count": int(accepted_plan.get("original_strategy_count") or len(expected)),
        "partial_strategy_set": len(found) < int(accepted_plan.get("original_strategy_count") or len(found)),
        "unreplayed_strategies_intentionally_untouched": True,
        "l090_candidate_count": len(candidates),
        "active_l085_queue": [
            {
                "strategy_id": row["strategy_id"],
                "winner": row["winner"],
                "metrics": winner_row(row),
                "next": "L085_REFINEMENT",
            }
            for row in candidates[:3]
        ],
        "pending_distinct_axis_queue": [
            {"strategy_id": row["strategy_id"], "next": "NEXT_DISTINCT_CAUSAL_AXIS"}
            for row in found.values()
            if row.get("state") != "PASS_L090_RESEARCH_CANDIDATE"
        ],
        "source_rows": source_rows,
        "source_rows_sha": canonical_sha(source_rows),
        "accepted_plan_sha": canonical_sha(accepted_plan),
        "w1_confirmation_required": True,
        "new_sealed_required": True,
        "canonical_mutated": False,
        "registry_mutated": False,
        **SAFETY,
    }
    final["final_sha256"] = canonical_sha(final)
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--accepted-plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = aggregate(args.replay_root, read_json(args.accepted_plan))
    write_json(args.out / "final.json", result)
    print(result["state"], "strategies=", result["strategy_count"], "l090=", result["l090_candidate_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
