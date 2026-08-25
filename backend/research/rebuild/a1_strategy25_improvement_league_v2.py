#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_strategy25_improvement_league_v1 as core

ROOT = core.ROOT
REBUILD = core.REBUILD
PERFORMANCE_MIN_TRADES = 8


def trusted_stage(rows: list[dict[str, Any]], fallback: Mapping[str, Any]) -> dict[str, Any]:
    trusted = [
        x for x in rows
        if x.get("operational_evidence")
        and not list(x.get("integrity_defects") or [])
        and int(x.get("leakage_lookahead") or 0) == 0
    ]
    pool = trusted or [dict(fallback)]
    return max(
        pool,
        key=lambda x: (
            int(x.get("stage_rank") or 0),
            int(x.get("source_priority") or 0),
            int((x.get("metrics") or {}).get("completed_trades") or 0),
        ),
    )


def lineage_headline(rows: list[dict[str, Any]], fallback: Mapping[str, Any]) -> dict[str, Any]:
    """Pick the best meaningful branch for lineage display/performance ranking only.

    Formal certification stage still comes from trusted operational evidence. A discovery/repair
    child may represent the lineage in the Top5 performance table, but cannot gain A1/A2/A3,
    promotion, execution, order or live authority from this selector.
    """
    clean = [
        x for x in rows
        if not list(x.get("integrity_defects") or [])
        and int(x.get("leakage_lookahead") or 0) == 0
    ]
    meaningful = [
        x for x in clean
        if int((x.get("metrics") or {}).get("completed_trades") or 0) >= PERFORMANCE_MIN_TRADES
        and core.positive_economics(x.get("metrics") or {})
    ]
    pool = meaningful or clean or [dict(fallback)]

    def key(x: Mapping[str, Any]) -> tuple[Any, ...]:
        m = x.get("metrics") or {}
        dd = core.finite(m.get("drawdown_bps"))
        return (
            int(core.positive_economics(m)),
            core.finite(m.get("net_expectancy_bps")) or -1e30,
            core.finite(m.get("net_pnl_bps")) or -1e30,
            core.finite(m.get("profit_factor")) or -1e30,
            core.finite(m.get("win_rate")) or -1e30,
            -(dd if dd is not None else 1e30),
            int(m.get("completed_trades") or 0),
        )

    picked = max(pool, key=key)
    operational = bool(picked.get("operational_evidence"))
    return {
        "identity": picked.get("identity") or fallback.get("identity"),
        "source_path": picked.get("source_path"),
        "observed_at_utc": picked.get("observed_at_utc"),
        "metrics": dict(picked.get("metrics") or {}),
        "verification_tier": "OPERATIONAL_EVIDENCE" if operational else "DISCOVERY_ONLY_FRESH_PENDING",
        "display_only": True,
        "formal_rank_uses_headline": False,
        "formal_promotion_eligible": False,
    }


def performance_metrics(row: Mapping[str, Any]) -> Mapping[str, Any]:
    display = row.get("display_metrics") if isinstance(row.get("display_metrics"), Mapping) else {}
    return display or (row.get("metrics") or {})


def performance_eligible(row: Mapping[str, Any]) -> bool:
    m = performance_metrics(row)
    return (
        not bool(row.get("failover_due"))
        and int(m.get("completed_trades") or 0) >= PERFORMANCE_MIN_TRADES
        and core.positive_economics(m)
    )


def performance_rank_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Top5 is a performance board: PnL first, then sample, WR, expectancy/PF, then DD.

    This is deliberately separate from formal A1/A2/A3 stage rank. Weak/negative lineages are
    removed from Active Top5 immediately when at least five eligible positive lineages exist.
    """
    m = performance_metrics(row)
    dd = core.finite(m.get("drawdown_bps"))
    return (
        int(performance_eligible(row)),
        core.finite(m.get("net_pnl_bps")) or -1e30,
        int(m.get("completed_trades") or 0),
        core.finite(m.get("win_rate")) or -1e30,
        core.finite(m.get("net_expectancy_bps")) or -1e30,
        core.finite(m.get("profit_factor")) or -1e30,
        -(dd if dd is not None else 1e30),
        int(row.get("stage_rank") or 0),
    )


def collect_evidence(extra_json: list[Path] | None = None) -> tuple[list[str], list[dict[str, Any]]]:
    inventory = core.read(core.INVENTORY)
    baseline = core.read(core.BASELINE)
    canonical = list((inventory.get("strategies") or {}).keys())
    canonical_set = set(canonical)
    evidence = core.baseline_evidence(baseline, canonical)
    for path in sorted(REBUILD.rglob("*latest*.json")):
        if path == core.PREVIOUS or "strategy25_improvement_league" in path.name:
            continue
        payload = core.read(path, None)
        if payload is None:
            continue
        evidence.extend(core.walk_rows(payload, canonical_set, path))
    for path in extra_json or []:
        if not path.exists():
            continue
        source_path = path if path.is_absolute() and ROOT in path.parents else ROOT / path
        evidence.extend(core.walk_rows(core.read(path), canonical_set, source_path))
    return canonical, evidence


def repartition(result: dict[str, Any], baseline: Mapping[str, Any]) -> None:
    # Top5/Next5 are performance ranks, not parent/stage ranks. Stable ID tie-break first.
    rows = sorted(result["rows"], key=lambda x: x["strategy_id"])
    rows = sorted(rows, key=performance_rank_key, reverse=True)
    active_n = 5
    challenger_n = 5
    eligible_count = sum(performance_eligible(x) for x in rows)
    for i, row in enumerate(rows):
        row["rank"] = i + 1
        row["performance_rank"] = i + 1
        row["performance_eligible"] = performance_eligible(row)
        row["remainder_disposition"] = None
        if i < active_n:
            row["role"] = "ACTIVE_TOP5"
        elif i < active_n + challenger_n:
            row["role"] = "CHALLENGER_NEXT5"
        else:
            row["role"] = "MATERIAL_HOLD"
            status = str(((baseline.get("strategies") or {}).get(row["strategy_id"]) or {}).get("status") or "")
            row["remainder_disposition"] = core.remainder_disposition(row, status)
    result["rows"] = rows
    result["role_counts"] = {
        "ACTIVE_TOP5": sum(x["role"] == "ACTIVE_TOP5" for x in rows),
        "CHALLENGER_NEXT5": sum(x["role"] == "CHALLENGER_NEXT5" for x in rows),
        "MATERIAL_HOLD": sum(x["role"] == "MATERIAL_HOLD" for x in rows),
    }
    result["performance_eligible_count"] = eligible_count
    result["performance_top5_fully_eligible"] = eligible_count >= active_n
    result["active_top5"] = [x["strategy_id"] for x in rows if x["role"] == "ACTIVE_TOP5"]
    result["challenger_next5"] = [x["strategy_id"] for x in rows if x["role"] == "CHALLENGER_NEXT5"]
    result["failover_due"] = [x["strategy_id"] for x in rows if x.get("failover_due")]
    result["deep_replay_manifest"]["strategy_ids"] = list(result["active_top5"])
    result["headline_top5"] = [
        {
            "strategy_id": x["strategy_id"],
            "rank": x["rank"],
            "role": x["role"],
            "performance_eligible": x.get("performance_eligible"),
            "lineage_headline": x.get("lineage_headline"),
            "formal_metrics": x.get("metrics"),
        }
        for x in rows if x["role"] == "ACTIVE_TOP5"
    ]


def build(extra_json: list[Path] | None = None) -> dict[str, Any]:
    result = core.build(extra_json)
    baseline = core.read(core.BASELINE)
    canonical, evidence = collect_evidence(extra_json)
    by_sid: dict[str, list[dict[str, Any]]] = {sid: [] for sid in canonical}
    for item in evidence:
        sid = item.get("strategy_id")
        if sid in by_sid:
            by_sid[sid].append(item)

    for row in result["rows"]:
        sid = row["strategy_id"]
        fallback = {
            "identity": row.get("identity") or sid,
            "stage_rank": row.get("stage_rank", 0),
            "source_priority": (row.get("source") or {}).get("priority", 0),
            "source_path": (row.get("source") or {}).get("path"),
            "observed_at_utc": (row.get("source") or {}).get("observed_at_utc"),
            "metrics": row.get("metrics") or {},
            "operational_evidence": True,
            "integrity_defects": [],
            "leakage_lookahead": 0,
        }
        stage_evidence = trusted_stage(by_sid.get(sid) or [], fallback)
        metric_stage = int(row.get("stage_rank") or 0)
        trusted_rank = int(stage_evidence.get("stage_rank") or 0)
        row["metric_source_stage_rank"] = metric_stage
        row["stage_rank"] = trusted_rank
        row["stage_source"] = {
            "path": stage_evidence.get("source_path"),
            "priority": stage_evidence.get("source_priority"),
            "observed_at_utc": stage_evidence.get("observed_at_utc"),
        }
        row["stage_preserved_across_metric_refresh"] = trusted_rank >= metric_stage
        row["lineage_headline"] = lineage_headline(by_sid.get(sid) or [], fallback)
        row["formal_metrics"] = dict(row.get("metrics") or {})
        row["display_metrics"] = dict((row["lineage_headline"] or {}).get("metrics") or {})
        if trusted_rank >= 6:
            row["failover_due"] = False

    repartition(result, baseline)
    result["schema_version"] = "zel.a1.strategy25_improvement_league.v2"
    result["stage_aggregation"] = "MAX_TRUSTED_OPERATIONAL_STAGE_SEPARATE_FROM_METRIC_SOURCE"
    result["lineage_display_policy"] = "BEST_MEANINGFUL_BRANCH_HEADLINE_PARENT_RETAINED_AS_FORMAL_BASELINE"
    result["lineage_display_min_trades"] = PERFORMANCE_MIN_TRADES
    result["top5_selection_policy"] = "PERFORMANCE_LINEAGE_HEADLINE:POSITIVE_ECONOMICS+MIN8;ORDER=NET_PNL,TRADES,WR,EXPECTANCY,PF,DD"
    result["formal_certification_separate_from_top5_rank"] = True
    result["stage_regression_guard"] = True
    result["receipt_sha256"] = core.stable({k: v for k, v in result.items() if k != "receipt_sha256"})
    if result["role_counts"] != {"ACTIVE_TOP5": 5, "CHALLENGER_NEXT5": 5, "MATERIAL_HOLD": 15}:
        raise RuntimeError(f"ROLE_PARTITION_INVALID:{result['role_counts']}")
    return result


def self_test() -> int:
    assert core.self_test() == 0
    high_metric_low_stage = {
        "stage_rank": 1, "source_priority": 600, "metrics": {"completed_trades": 13},
        "operational_evidence": True, "integrity_defects": [], "leakage_lookahead": 0,
        "source_path": "deep.json",
    }
    lower_metric_high_stage = {
        "stage_rank": 4, "source_priority": 550, "metrics": {"completed_trades": 12},
        "operational_evidence": True, "integrity_defects": [], "leakage_lookahead": 0,
        "source_path": "a2.json",
    }
    contaminated_stage = {
        "stage_rank": 6, "source_priority": 999, "metrics": {"completed_trades": 99},
        "operational_evidence": True, "integrity_defects": ["TEST"], "leakage_lookahead": 0,
        "source_path": "bad.json",
    }
    picked = trusted_stage([high_metric_low_stage, lower_metric_high_stage, contaminated_stage], high_metric_low_stage)
    assert picked["stage_rank"] == 4 and picked["source_path"] == "a2.json", picked

    parent = {
        "identity": "trend_rider_parent", "source_path": "deep.json", "operational_evidence": True,
        "integrity_defects": [], "leakage_lookahead": 0,
        "metrics": {"completed_trades": 27, "win_rate": 0.4074, "net_pnl_bps": 10939.0,
                    "net_expectancy_bps": 405.1, "profit_factor": 5.27, "drawdown_bps": 877.4},
    }
    child = {
        "identity": "trend_rider_wr81_child", "source_path": "attribution_latest.json", "operational_evidence": False,
        "integrity_defects": [], "leakage_lookahead": 0,
        "metrics": {"completed_trades": 16, "win_rate": 0.8125, "net_pnl_bps": 23297.8,
                    "net_expectancy_bps": 1456.1, "profit_factor": None, "drawdown_bps": None},
    }
    head = lineage_headline([parent, child], parent)
    assert head["identity"] == "trend_rider_wr81_child" and head["verification_tier"] == "DISCOVERY_ONLY_FRESH_PENDING", head
    assert head["formal_rank_uses_headline"] is False and head["formal_promotion_eligible"] is False, head

    strong = {"strategy_id": "strong", "display_metrics": child["metrics"], "stage_rank": 0, "failover_due": False}
    weak = {"strategy_id": "weak", "display_metrics": {"completed_trades": 100, "win_rate": 0.9, "net_pnl_bps": -1.0,
            "net_expectancy_bps": -0.01, "profit_factor": 0.9, "drawdown_bps": 1.0}, "stage_rank": 6, "failover_due": False}
    assert performance_rank_key(strong) > performance_rank_key(weak), (strong, weak)
    print("PASS_A1_STRATEGY25_IMPROVEMENT_LEAGUE_V2_STAGE_GUARD_SELF_TEST")
    print("PASS_A1_STRATEGY25_LINEAGE_HEADLINE_SELF_TEST")
    print("PASS_A1_STRATEGY25_PERFORMANCE_TOP5_SELF_TEST")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--out", type=Path, default=Path("out/a1_strategy25_improvement_league_latest.json"))
    p.add_argument("--extra-json", action="append", default=[])
    args = p.parse_args()
    if args.self_test:
        return self_test()
    result = build([Path(x) for x in args.extra_json])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print("STRATEGY25_LEAGUE_V2=" + json.dumps({
        "active": result["active_top5"],
        "headline_top5": result["headline_top5"],
        "challenger": result["challenger_next5"],
        "roles": result["role_counts"],
        "performance_eligible_count": result["performance_eligible_count"],
        "improved": result["improved_count"],
        "failover": result["failover_due"],
        "stage_guard": result["stage_regression_guard"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
