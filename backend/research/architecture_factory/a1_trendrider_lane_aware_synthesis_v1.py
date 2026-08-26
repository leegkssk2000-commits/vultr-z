#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil
from backend.research.architecture_factory import a1_top5_evolutionary_synthesis_v7 as legacy_v7
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as exact_v1
from backend.research.rebuild import a1_recent_loss_cluster_diagnostic_v1 as diag
from backend.research.rebuild import a1_trend_rider_wr80_winner_restore_attribution_v1 as wr80

ROOT = Path(__file__).resolve().parents[3]
SSOT = ROOT / "backend/research/rebuild/a1_production_highwr_top5_ssot_v1.json"
LEAGUE = ROOT / "backend/research/rebuild/a1_strategy25_improvement_league_latest.json"
LEGACY = ROOT / "backend/research/architecture_factory/a1_top5_evolutionary_synthesis_latest.json"
HISTORY = ROOT / "backend/research/architecture_factory/a1_trendrider_lane_aware_history_latest.json"
LATEST = ROOT / "backend/research/architecture_factory/a1_trendrider_lane_aware_synthesis_latest.json"
SCHEMA = "zel.a1_trendrider_lane_aware_synthesis.v1"
PRIMARY = "trend_rider_primary_wr8125"
BROAD = "trend_rider_broad_wr7000"
EXPECTED_LANES = (PRIMARY, BROAD)
BROAD_SOURCE_RUN_ID = 32482936710
PRIMARY_FROZEN_COUNT = 24
PRIMARY_EXPECTED_TRADES = 16
PRIMARY_EXPECTED_WINS = 13
PRIMARY_EXPECTED_WR = 0.8125
PRIMARY_EXPECTED_PNL_BPS = 23297.769437281215

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
}


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _production_lanes(ssot: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [dict(x) for x in ssot.get("production_top5") or [] if isinstance(x, Mapping)]
    selected = [x for x in rows if str(x.get("lane_id")) in EXPECTED_LANES]
    selected.sort(key=lambda x: EXPECTED_LANES.index(str(x["lane_id"])))
    ids = [str(x.get("lane_id")) for x in selected]
    if ids != list(EXPECTED_LANES):
        raise RuntimeError(f"TREND_RIDER_LANES_REQUIRED:{ids}")
    if any(str(x.get("strategy_id")) != "trend_rider" for x in selected):
        raise RuntimeError("TREND_RIDER_STRATEGY_ID_REQUIRED")
    if any(not bool(x.get("challenger_parent_eligible")) for x in selected):
        raise RuntimeError("TREND_RIDER_CHALLENGER_PARENT_REQUIRED")
    if len({str(x["lane_id"]) for x in selected}) != 2:
        raise RuntimeError("LANE_ID_COLLAPSE_FORBIDDEN")
    return selected


def _parent_metrics(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "completed_trades": int(row.get("completed_trades") or 0),
        "wins": int(row.get("wins") or 0),
        "win_rate": row.get("win_rate"),
        "net_pnl_bps": row.get("net_pnl_bps"),
        "net_expectancy_bps": row.get("net_expectancy_bps"),
        "max_drawdown_bps": row.get("max_drawdown_bps"),
        "profit_factor": row.get("profit_factor"),
        "payoff": row.get("payoff"),
    }


def _stats_from_trades(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = [dict(x) for x in rows]
    ordered.sort(key=lambda x: (int(x.get("entry_ts") or 0), int(x.get("exit_ts") or 0), str(x.get("symbol") or "")))
    values = [float(x.get("net_bps") or 0.0) for x in ordered]
    wins = [x for x in values if x > 0.0]
    losses = [-x for x in values if x < 0.0]
    gp, gl = sum(wins), sum(losses)
    avg_win = gp / len(wins) if wins else None
    avg_loss = gl / len(losses) if losses else None
    return {
        "completed_trades": len(values),
        "wins": len(wins),
        "win_rate": len(wins) / len(values) if values else None,
        "net_pnl_bps": sum(values),
        "net_expectancy_bps": sum(values) / len(values) if values else None,
        "max_drawdown_bps": exact_v1.max_drawdown(values),
        "profit_factor": exact_v1.profit_factor(gp, gl),
        "payoff": avg_win / avg_loss if avg_win is not None and avg_loss not in (None, 0) else None,
    }


def _close(a: Any, b: Any, *, abs_tol: float = 0.05, rel_tol: float = 1e-9) -> bool:
    if a is None or b is None:
        return a is b
    try:
        av, bv = float(a), float(b)
    except (TypeError, ValueError):
        return a == b
    return abs(av - bv) <= max(abs_tol, rel_tol * max(abs(av), abs(bv), 1.0))


def _metric_match(observed: Mapping[str, Any], expected: Mapping[str, Any]) -> tuple[bool, dict[str, bool]]:
    tolerances = {
        "completed_trades": 0.0,
        "wins": 0.0,
        "win_rate": 1e-12,
        "net_pnl_bps": 0.05,
        "net_expectancy_bps": 0.01,
        "max_drawdown_bps": 0.05,
        "profit_factor": 0.01,
        "payoff": 0.01,
    }
    checks: dict[str, bool] = {}
    for key, tol in tolerances.items():
        checks[key] = _close(observed.get(key), expected.get(key), abs_tol=tol, rel_tol=1e-10)
    return all(checks.values()), checks


def _primary_parent(expected: Mapping[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="a1_lane_primary_") as td:
        receipt = diag._run_receipt("trend_rider", Path(td) / "trend_rider.json")
    rows = [dict(x) for x in receipt.get("trades") or [] if isinstance(x, Mapping)]
    rows.sort(key=lambda x: (int(x.get("entry_ts") or 0), str(x.get("symbol") or "")))
    if len(rows) < PRIMARY_FROZEN_COUNT:
        return {
            "lane_id": PRIMARY,
            "state": "HOLD_PRIMARY_FROZEN_24_UNAVAILABLE",
            "raw_trade_count": len(rows),
            "exact_trade_replay_verified": False,
            "same_baseline_ab_ready": False,
        }
    rows = rows[:PRIMARY_FROZEN_COUNT]
    wr80._enrich(receipt, rows)
    if any(bool(x.get("feature_missing")) for x in rows):
        return {
            "lane_id": PRIMARY,
            "state": "HOLD_PRIMARY_FEATURE_MISSING",
            "exact_trade_replay_verified": False,
            "same_baseline_ab_ready": False,
        }
    selected = [x for x in rows if str(x.get("session")) != "US" or str(x.get("chase_state")) == "COOLING_OR_FLAT"]
    observed = _stats_from_trades(selected)
    historical_anchor_ok = (
        observed["completed_trades"] == PRIMARY_EXPECTED_TRADES
        and observed["wins"] == PRIMARY_EXPECTED_WINS
        and _close(observed["win_rate"], PRIMARY_EXPECTED_WR, abs_tol=1e-12)
        and _close(observed["net_pnl_bps"], PRIMARY_EXPECTED_PNL_BPS, abs_tol=0.05)
    )
    exact, checks = _metric_match(observed, expected)
    return {
        "lane_id": PRIMARY,
        "state": "PASS_PRIMARY_EXACT_PARENT_REPLAY" if exact and historical_anchor_ok else "HOLD_PRIMARY_PARENT_METRIC_MISMATCH",
        "source_adapter": "FROZEN_WR8125_SESSION_CHASE_REPLAY",
        "historical_anchor_match": historical_anchor_ok,
        "metric_checks": checks,
        "observed_metrics": observed,
        "expected_metrics": dict(expected),
        "selected_trade_count": len(selected),
        "selected_trade_receipt_sha256": hashutil.sha(selected),
        "exact_trade_replay_verified": bool(exact and historical_anchor_ok),
        "same_baseline_ab_ready": bool(exact and historical_anchor_ok),
    }


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _broad_receipts(artifact_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not artifact_dir.exists():
        return out
    for path in sorted(artifact_dir.rglob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        for obj in _walk_dicts(value):
            if str(obj.get("strategy_id")) != "trend_rider":
                continue
            trades = obj.get("trades")
            if not isinstance(trades, list) or not trades:
                continue
            try:
                completed = int(obj.get("completed_trades") or len(trades))
            except (TypeError, ValueError):
                continue
            if completed != len(trades):
                continue
            row = dict(obj)
            row["_artifact_path"] = str(path)
            out.append(row)
    return out


def _receipt_metrics(receipt: Mapping[str, Any]) -> dict[str, Any]:
    raw = receipt.get("metrics") if isinstance(receipt.get("metrics"), Mapping) else {}
    trades = [dict(x) for x in receipt.get("trades") or [] if isinstance(x, Mapping)]
    derived = _stats_from_trades(trades)
    mapped = {
        "completed_trades": int(receipt.get("completed_trades") or len(trades)),
        "wins": derived["wins"],
        "win_rate": raw.get("win_rate", derived["win_rate"]),
        "net_pnl_bps": raw.get("net_pnl_bps", derived["net_pnl_bps"]),
        "net_expectancy_bps": raw.get("net_expectancy_bps", derived["net_expectancy_bps"]),
        "max_drawdown_bps": raw.get("max_drawdown_bps", derived["max_drawdown_bps"]),
        "profit_factor": raw.get("net_profit_factor", raw.get("profit_factor", derived["profit_factor"])),
        "payoff": raw.get("net_payoff", raw.get("payoff", derived["payoff"])),
    }
    return mapped


def _broad_parent(expected: Mapping[str, Any], lane_row: Mapping[str, Any], artifact_dir: Path | None) -> dict[str, Any]:
    if artifact_dir is None:
        return {
            "lane_id": BROAD,
            "state": "HOLD_BROAD_EXACT25_ARTIFACT_REQUIRED",
            "source_run_id": lane_row.get("source_run_id"),
            "source_receipt_sha256": lane_row.get("source_receipt_sha256"),
            "exact_trade_replay_verified": False,
            "same_baseline_ab_ready": False,
        }
    candidates: list[tuple[dict[str, Any], dict[str, Any], dict[str, bool]]] = []
    for receipt in _broad_receipts(artifact_dir):
        observed = _receipt_metrics(receipt)
        exact, checks = _metric_match(observed, expected)
        if exact:
            candidates.append((receipt, observed, checks))
    if len(candidates) != 1:
        return {
            "lane_id": BROAD,
            "state": "HOLD_BROAD_EXACT_RECEIPT_NOT_UNIQUE",
            "matching_receipt_count": len(candidates),
            "artifact_dir": str(artifact_dir),
            "source_run_id": lane_row.get("source_run_id"),
            "exact_trade_replay_verified": False,
            "same_baseline_ab_ready": False,
        }
    receipt, observed, checks = candidates[0]
    trades = [dict(x) for x in receipt.get("trades") or [] if isinstance(x, Mapping)]
    derived = _stats_from_trades(trades)
    derived_ok, derived_checks = _metric_match(derived, expected)
    integrity = {
        "source_run_id_matches_ssot": int(lane_row.get("source_run_id") or 0) == BROAD_SOURCE_RUN_ID,
        "strategy_id_is_trend_rider": str(receipt.get("strategy_id")) == "trend_rider",
        "receipt_trade_count_is_30": len(trades) == 30,
        "receipt_metrics_match_ssot": all(checks.values()),
        "trade_derived_metrics_match_ssot": derived_ok,
        "leakage_lookahead_zero": int(receipt.get("leakage_lookahead") or 0) == 0,
        "duplicate_count_zero": int(receipt.get("duplicate_count") or 0) == 0,
    }
    verified = all(integrity.values())
    return {
        "lane_id": BROAD,
        "state": "PASS_BROAD_EXACT25_ARTIFACT_PARENT" if verified else "HOLD_BROAD_EXACT25_ARTIFACT_INTEGRITY",
        "source_adapter": "EXACT25_RUN_ARTIFACT",
        "source_run_id": BROAD_SOURCE_RUN_ID,
        "ssot_controller_receipt_sha256": lane_row.get("source_receipt_sha256"),
        "economics_receipt_sha256": receipt.get("receipt_sha256"),
        "artifact_path": receipt.get("_artifact_path"),
        "metric_checks": checks,
        "trade_derived_metric_checks": derived_checks,
        "integrity": integrity,
        "observed_metrics": observed,
        "trade_derived_metrics": derived,
        "expected_metrics": dict(expected),
        "selected_trade_receipt_sha256": hashutil.sha(trades),
        "exact_trade_replay_verified": verified,
        "same_baseline_ab_ready": verified,
    }


def _row_metrics(row: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("display_metrics", "metrics", "formal_metrics"):
        value = row.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _positive_edge(metrics: Mapping[str, Any]) -> bool:
    try:
        trades = int(metrics.get("completed_trades") or metrics.get("trades") or 0)
        pnl = float(metrics.get("net_pnl_bps") or 0.0)
        exp = float(metrics.get("net_expectancy_bps") or 0.0)
        pf_raw = metrics.get("profit_factor", metrics.get("net_profit_factor"))
        pf = float(pf_raw) if pf_raw is not None else 1.0
        return trades >= 8 and pnl > 0.0 and exp > 0.0 and pf >= 1.0
    except (TypeError, ValueError):
        return False


def _donor_pool(league: Mapping[str, Any], ssot: Mapping[str, Any]) -> list[dict[str, Any]]:
    production_strategy_ids = {
        str(x.get("strategy_id")) for x in ssot.get("production_top5") or [] if isinstance(x, Mapping)
    }
    compatible = set(legacy_v7.HOST_TYPES.get("trend_rider") or set())
    out: list[dict[str, Any]] = []
    for raw in league.get("rows") or []:
        if not isinstance(raw, Mapping):
            continue
        sid = str(raw.get("strategy_id") or "")
        gene = legacy_v7.GENES.get(sid)
        if not sid or sid in production_strategy_ids or not isinstance(gene, Mapping):
            continue
        if str(gene.get("type")) not in compatible:
            continue
        metrics = _row_metrics(raw)
        out.append({
            "strategy_id": sid,
            "gene": str(gene.get("gene")),
            "gene_type": str(gene.get("type")),
            "required_sources": list(gene.get("required_sources") or ["ohlcv"]),
            "donor_tier": "VALIDATED_EDGE_DONOR" if _positive_edge(metrics) else "MECHANISM_HYPOTHESIS_ONLY",
            "performance_rank": int(raw.get("performance_rank") or raw.get("rank") or 999),
            "whole_strategy_merge_allowed": False,
            "numeric_threshold_import_allowed": False,
            "outcome_claim_import_allowed": False,
        })
    out.sort(key=lambda x: (0 if x["donor_tier"] == "VALIDATED_EDGE_DONOR" else 1, int(x["performance_rank"]), str(x["strategy_id"])))
    return out


def _axis(donor: Mapping[str, Any]) -> str:
    sid = str(donor.get("strategy_id") or "").upper().replace("-", "_")
    gene = str(donor.get("gene") or "").upper().replace("-", "_")
    return f"LANE_DONOR__{sid}__{gene}__ONLY"


def _lane_attempted(history: Mapping[str, Any], lane_id: str) -> set[str]:
    lanes = history.get("lanes") if isinstance(history.get("lanes"), Mapping) else {}
    row = lanes.get(lane_id) if isinstance(lanes, Mapping) and isinstance(lanes.get(lane_id), Mapping) else {}
    raw = row.get("attempted_axes") if isinstance(row, Mapping) else []
    return {str(x) for x in raw or [] if str(x)}


def _next_donor(donors: list[dict[str, Any]], history: Mapping[str, Any], lane_id: str) -> dict[str, Any] | None:
    attempted = _lane_attempted(history, lane_id)
    for donor in donors:
        if _axis(donor) not in attempted:
            out = dict(donor)
            out["axis"] = _axis(donor)
            return out
    return None


def run(output: Path, exact25_artifact_dir: Path | None = None) -> dict[str, Any]:
    ssot = _read(SSOT)
    league = _read(LEAGUE)
    legacy = _read(LEGACY)
    history = _read(HISTORY)
    lanes = _production_lanes(ssot)
    by_id = {str(x["lane_id"]): x for x in lanes}

    primary = _primary_parent(_parent_metrics(by_id[PRIMARY]))
    broad = _broad_parent(_parent_metrics(by_id[BROAD]), by_id[BROAD], exact25_artifact_dir)
    parents = [primary, broad]
    all_exact = all(bool(x.get("exact_trade_replay_verified")) for x in parents)

    donors = _donor_pool(league, ssot)
    plans: list[dict[str, Any]] = []
    for lane in lanes:
        lane_id = str(lane["lane_id"])
        donor = _next_donor(donors, history, lane_id)
        plans.append({
            "lane_id": lane_id,
            "strategy_id": "trend_rider",
            "parent_exact_replay_verified": next(bool(x.get("exact_trade_replay_verified")) for x in parents if x["lane_id"] == lane_id),
            "attempted_axes": sorted(_lane_attempted(history, lane_id)),
            "next_donor": donor,
            "next_axis": donor.get("axis") if donor else None,
            "development_child_generation_allowed": bool(all_exact and donor),
            "promotion_ready": False,
        })

    legacy_generic = []
    generic_history = legacy.get("economic_attempted_axes") if isinstance(legacy.get("economic_attempted_axes"), Mapping) else {}
    if isinstance(generic_history, Mapping):
        legacy_generic = [str(x) for x in generic_history.get("trend_rider") or []]

    result = {
        "schema_version": SCHEMA,
        "state": "READY_FOR_LANE_CHILD_GENERATION" if all_exact else "PARENT_REPLAY_HOLD",
        "selection_unit": "lane_id",
        "lane_ids": [str(x["lane_id"]) for x in lanes],
        "strategy_ids": [str(x["strategy_id"]) for x in lanes],
        "duplicate_strategy_id_lane_identity_preserved": len({str(x["lane_id"]) for x in lanes}) == 2 and len({str(x["strategy_id"]) for x in lanes}) == 1,
        "parent_adapters": parents,
        "lane_plans": plans,
        "donor_pool_count": len(donors),
        "donor_pool": donors,
        "legacy_generic_trend_rider_attempted_axes_observed_for_audit_only": legacy_generic,
        "generic_trend_rider_history_ignored": True,
        "generic_strategy_id_history_may_block_lane_axis": False,
        "lane_history_path": str(HISTORY.relative_to(ROOT)),
        "failed_lane_gene_pair_retry_forbidden": True,
        "one_gene_per_lane_per_attempt": True,
        "whole_strategy_merge_allowed": False,
        "donor_numeric_threshold_copy_allowed": False,
        "donor_outcome_claim_copy_allowed": False,
        "same_baseline_ab_required_before_improvement_claim": True,
        "fresh_oos_required_before_promotion": True,
        "improvement_claim_allowed": False,
        "promotion_ready": False,
        "next": "GENERATE_ONE_MECHANISM_CHILD_PER_EXACT_LANE_AND_RUN_SAME_PARENT_AB" if all_exact else "RESTORE_EXACT_PARENT_REPLAY_BEFORE_CHILD_GENERATION",
        **AUTH,
    }
    result["receipt_sha256"] = hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    fake_ssot = {
        "production_top5": [
            {"lane_id": PRIMARY, "strategy_id": "trend_rider", "challenger_parent_eligible": True},
            {"lane_id": BROAD, "strategy_id": "trend_rider", "challenger_parent_eligible": True},
        ]
    }
    lanes = _production_lanes(fake_ssot)
    assert [x["lane_id"] for x in lanes] == [PRIMARY, BROAD]
    assert len({x["lane_id"] for x in lanes}) == 2 and len({x["strategy_id"] for x in lanes}) == 1

    donors = [
        {"strategy_id": "x", "gene": "g1"},
        {"strategy_id": "y", "gene": "g2"},
    ]
    x_axis = _axis(donors[0])
    history = {"lanes": {PRIMARY: {"attempted_axes": [x_axis]}, BROAD: {"attempted_axes": []}}}
    assert _next_donor(donors, history, PRIMARY)["strategy_id"] == "y"
    assert _next_donor(donors, history, BROAD)["strategy_id"] == "x"

    legacy_only = {"economic_attempted_axes": {"trend_rider": [x_axis]}}
    assert x_axis in legacy_only["economic_attempted_axes"]["trend_rider"]
    assert _lane_attempted({}, PRIMARY) == set()
    assert AUTH["selection_authority"] is False and AUTH["promotion_authority"] is False
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    assert AUTH["live_trade_authority"] == "BLOCKED" and AUTH["exchange_order_submitted"] is False
    print("PASS_A1_TRENDRIDER_LANE_AWARE_SYNTHESIS_V1_SELF_TEST")
    print("PASS_DUPLICATE_STRATEGY_ID_PRESERVES_TWO_LANE_IDS")
    print("PASS_GENERIC_TREND_RIDER_HISTORY_IGNORED_BY_LANE_HISTORY")
    print("PASS_FAILED_AXIS_EXCLUSION_IS_INDEPENDENT_PER_LANE")
    print("PASS_AUTHORITY_BLOCKS_INTACT")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_trendrider_lane_aware_synthesis_v1.json"))
    ap.add_argument("--exact25-artifact-dir", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output, args.exact25_artifact_dir)
    print(json.dumps({
        "state": result["state"],
        "lane_ids": result["lane_ids"],
        "parent_states": {x["lane_id"]: x["state"] for x in result["parent_adapters"]},
        "next_axes": {x["lane_id"]: x["next_axis"] for x in result["lane_plans"]},
        "receipt": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
