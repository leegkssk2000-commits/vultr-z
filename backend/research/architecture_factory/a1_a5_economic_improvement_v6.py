#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_a5_economic_improvement_v5 as v5
from backend.research.architecture_factory import a1_a5_economic_improvement_v3 as v3
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil

ROOT = Path(__file__).resolve().parents[3]
LEAGUE = ROOT / "backend/research/rebuild/a1_strategy25_improvement_league_latest.json"
SCHEMA = "zel.a1_a5_economic_improvement.v6"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _focus_order() -> tuple[list[str], dict[str, Any]]:
    league = _read(LEAGUE)
    active = [str(x) for x in (league.get("active_top5") or []) if str(x)]
    if len(active) != 5 or len(set(active)) != 5:
        raise RuntimeError(f"PERFORMANCE_TOP5_REQUIRED:{active}")
    contract = v3.v1.contract()
    supported = set((contract.get("strategies") or {}).keys())
    missing = [sid for sid in active if sid not in supported]
    if missing:
        raise RuntimeError("TOP5_DIRECT_REPAIR_CONTRACT_MISSING__ROUTE_TO_SYNTHESIS_FIRST:" + ",".join(missing))
    return active, league


def _dispositions(league: Mapping[str, Any], focus: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    focus_set = set(focus)
    synthesis: list[dict[str, Any]] = []
    archive: list[dict[str, Any]] = []
    for raw in league.get("rows") or []:
        if not isinstance(raw, Mapping):
            continue
        sid = str(raw.get("strategy_id") or "")
        if not sid or sid in focus_set:
            continue
        m = raw.get("display_metrics") if isinstance(raw.get("display_metrics"), Mapping) else raw.get("metrics") or {}
        trades = int(m.get("completed_trades") or 0)
        pnl = m.get("net_pnl_bps")
        exp = m.get("net_expectancy_bps")
        pf = m.get("profit_factor")
        positive = False
        try:
            positive = trades >= 8 and float(pnl) > 0 and float(exp) > 0 and (pf is None or float(pf) >= 1.0)
        except (TypeError, ValueError):
            positive = False
        row = {
            "strategy_id": sid,
            "performance_rank": raw.get("performance_rank") or raw.get("rank"),
            "role": raw.get("role"),
            "metrics": dict(m) if isinstance(m, Mapping) else {},
        }
        if positive:
            row["disposition"] = "SYNTHESIS_ONLY_NO_DIRECT_REPAIR"
            synthesis.append(row)
        else:
            row["disposition"] = "ARCHIVE_REJECT_NO_MORE_IMPROVEMENT_BUDGET"
            archive.append(row)
    synthesis.sort(key=lambda x: int(x.get("performance_rank") or 999))
    archive.sort(key=lambda x: int(x.get("performance_rank") or 999))
    return synthesis, archive


def run(output: Path) -> dict[str, Any]:
    focus, league = _focus_order()
    original = v3.v1.a5_order

    def focused_order(_contract: Mapping[str, Any]) -> list[str]:
        return list(focus)

    try:
        v3.v1.a5_order = focused_order
        result = dict(v5.run(output))
    finally:
        v3.v1.a5_order = original

    # V5 historically carried a frozen A5 order. V6 binds the actual performance Top5 every run.
    result["a5_order"] = list(focus)
    result["performance_focus_order"] = list(focus)
    result["focus_source"] = str(LEAGUE.relative_to(ROOT))
    result["top5_selection_policy"] = league.get("top5_selection_policy")
    result["performance_top5_fully_eligible"] = league.get("performance_top5_fully_eligible")

    synthesis, archive = _dispositions(league, focus)
    result["non_top5_synthesis_pool"] = synthesis
    result["non_top5_archive_reject"] = archive
    result["non_top5_direct_repair_enabled"] = False
    result["direct_improvement_scope"] = "PERFORMANCE_TOP5_ONLY_IN_CURRENT_ORDER"
    result["dropped_lineage_policy"] = "POSITIVE_EDGE=>SYNTHESIS_ONLY; OTHERWISE=>ARCHIVE_REJECT"
    result["focus_count"] = len(focus)
    result["synthesis_pool_count"] = len(synthesis)
    result["archive_reject_count"] = len(archive)

    policy = result.setdefault("policy", {})
    policy["performance_top5_only_direct_improvement"] = True
    policy["non_top5_direct_repair_forbidden"] = True
    policy["non_top5_positive_edge_synthesis_only"] = True
    policy["non_top5_nonpositive_archive_reject"] = True
    policy["restart_from_zero_after_demotion_forbidden"] = True
    policy["promotion_still_requires_a1_a2_a3"] = True

    result["schema_version"] = SCHEMA
    result["selection_authority"] = False
    result["promotion_authority"] = False
    result["execution_authority"] = "NONE"
    result["order_authority"] = "BLOCKED"
    result["live_trade_authority"] = "BLOCKED"
    result["exchange_order_submitted"] = False
    result["protected_mutations"] = 0
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    league = {
        "rows": [
            {"strategy_id": "a", "rank": 1, "role": "ACTIVE_TOP5", "display_metrics": {"completed_trades": 10, "net_pnl_bps": 10, "net_expectancy_bps": 1, "profit_factor": 2}},
            {"strategy_id": "b", "rank": 6, "role": "CHALLENGER_NEXT5", "display_metrics": {"completed_trades": 12, "net_pnl_bps": 9, "net_expectancy_bps": 1, "profit_factor": 2}},
            {"strategy_id": "c", "rank": 7, "role": "CHALLENGER_NEXT5", "display_metrics": {"completed_trades": 20, "net_pnl_bps": -1, "net_expectancy_bps": -0.1, "profit_factor": 0.8}},
        ]
    }
    syn, arc = _dispositions(league, ["a", "x", "y", "z", "q"])
    assert [x["strategy_id"] for x in syn] == ["b"], syn
    assert [x["strategy_id"] for x in arc] == ["c"], arc
    assert v3.AUTH["execution_authority"] == "NONE" and v3.AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_A5_ECONOMIC_IMPROVEMENT_V6_FOCUS_SELF_TEST")
    print("PASS_TOP5_ONLY_DIRECT_REPAIR_NON_TOP5_SYNTHESIS_OR_ARCHIVE")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_a5_economic_improvement_v6.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output)
    print(json.dumps({
        "state": r.get("state"),
        "focus": r.get("performance_focus_order"),
        "development_pass": r.get("development_economic_pass_count"),
        "synthesis_pool": r.get("synthesis_pool_count"),
        "archive_reject": r.get("archive_reject_count"),
        "paid": r.get("paid_request_count"),
        "receipt": r.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
