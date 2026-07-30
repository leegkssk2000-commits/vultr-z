from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

VERSION = "STRATEGY11_FAMOUS_INDICATOR_AUTONOMY_V1"
REPLAY_VERSION = "STRATEGY11_FAMOUS_INDICATOR_AUTONOMY_REPLAY_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}
FAMILY_MAP = {
    "alpha_combo": "hybrid",
    "anchor_vwap_trend": "trend_following",
    "bb_revert": "mean_reversion",
    "break_and_continue": "breakout_momentum",
    "ema_ribbon_scalp": "trend_following",
    "fvg_revert": "market_structure",
    "grid_rebalance": "mean_reversion",
    "keltner_trend": "trend_following",
    "liquidity_sweep": "market_structure",
    "mfi_rsi_div": "mean_reversion",
    "obv_trend": "trend_following",
    "pivot_reversal": "market_structure",
    "range_fade": "mean_reversion",
    "rbreaker_like": "breakout_momentum",
    "rsi_swing_fail": "mean_reversion",
    "scalp_snap": "hybrid",
    "session_bias": "session_volatility",
    "squeeze_break": "breakout_momentum",
    "sr_levels": "market_structure",
    "supertrend_pullback": "trend_following",
    "trend_ma_macd": "trend_following",
    "trend_rider": "trend_following",
    "turtle_trend": "breakout_momentum",
    "vol_spike_fade": "session_volatility",
    "vwap_revert": "mean_reversion",
}
STRATEGIES = tuple(FAMILY_MAP)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def parse_utc(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


def now_utc(value: str | None) -> dt.datetime:
    return parse_utc(value) if value else dt.datetime.now(dt.timezone.utc)


def empty_ledger(catalog: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "INITIALIZED",
        "catalog_sha256": stable_sha(catalog),
        "cycle_index": 0,
        "rows": [
            {
                "strategy_id": strategy_id,
                "family": FAMILY_MAP[strategy_id],
                "tested_candidates": [],
                "pass_candidates": [],
                "hold_candidates": [],
                "rejected_candidates": [],
                "last_cycle": 0,
            }
            for strategy_id in STRATEGIES
        ],
        **SAFETY,
    }


def normalize_previous(path: Path | None, catalog: Mapping[str, Any]) -> dict[str, Any]:
    if path is None or not path.exists():
        return empty_ledger(catalog)
    value = read_json(path)
    rows = value.get("rows")
    if not isinstance(rows, list):
        return empty_ledger(catalog)
    observed = {str(row.get("strategy_id")): dict(row) for row in rows if isinstance(row, Mapping)}
    normalized = empty_ledger(catalog)
    normalized["cycle_index"] = int(value.get("cycle_index") or 0)
    normalized["rows"] = []
    for strategy_id in STRATEGIES:
        row = observed.get(strategy_id, {})
        normalized["rows"].append({
            "strategy_id": strategy_id,
            "family": FAMILY_MAP[strategy_id],
            "tested_candidates": list(row.get("tested_candidates") or []),
            "pass_candidates": list(row.get("pass_candidates") or []),
            "hold_candidates": list(row.get("hold_candidates") or []),
            "rejected_candidates": list(row.get("rejected_candidates") or []),
            "last_cycle": int(row.get("last_cycle") or 0),
        })
    return normalized


def validate_catalog(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    if catalog.get("authority") != "RESEARCH_ONLY_NO_PROMOTION":
        raise ValueError("CATALOG_AUTHORITY_INVALID")
    candidates = [dict(row) for row in catalog.get("candidates", []) if isinstance(row, Mapping)]
    ids = [str(row.get("candidate_id")) for row in candidates]
    if len(candidates) < 50 or len(ids) != len(set(ids)):
        raise ValueError("CATALOG_COUNT_OR_DUPLICATE_INVALID")
    required_families = {"BOLLINGER_BANDS", "ATR_NATR", "FIBONACCI", "ICHIMOKU", "SUPERTREND", "RSI", "OBV"}
    observed = {str(row.get("indicator_family")) for row in candidates}
    if not required_families.issubset(observed):
        raise ValueError("FAMOUS_INDICATOR_COVERAGE_INCOMPLETE")
    for row in candidates:
        if row.get("kind") != "GATE" or row.get("causal") is not True:
            raise ValueError(f"CATALOG_NONCAUSAL_OR_KIND:{row.get('candidate_id')}")
        components = list(row.get("components") or [])
        required = list(row.get("required") or [])
        if not 1 <= len(components) <= 2:
            raise ValueError(f"COMPONENT_LIMIT:{row.get('candidate_id')}")
        if not 1 <= len(required) <= 3:
            raise ValueError(f"RAW_FEATURE_LIMIT:{row.get('candidate_id')}")
        if not set(row.get("compatible_families") or []).issubset(set(FAMILY_MAP.values())):
            raise ValueError(f"FAMILY_COMPATIBILITY_INVALID:{row.get('candidate_id')}")
    for key, expected in SAFETY.items():
        if catalog.get(key) != expected:
            raise ValueError(f"CATALOG_SAFETY_MISMATCH:{key}")
    return candidates


def tested_ids(row: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    for item in row.get("tested_candidates", []) or []:
        if isinstance(item, Mapping):
            result.add(str(item.get("candidate_id")))
        else:
            result.add(str(item))
    return result


def candidate_spec(candidate: Mapping[str, Any], family: str) -> dict[str, Any]:
    candidate_id = str(candidate["candidate_id"])
    return {
        "kind": "GATE",
        "axis": str(candidate["axis"]),
        "gate": {
            "gate_id": candidate_id,
            "family": family,
            "required": list(candidate.get("required") or []),
            "forbidden": list(candidate.get("forbidden") or []),
            "description": (
                f"{candidate.get('indicator_family')} bounded causal probe; "
                f"components={','.join(map(str, candidate.get('components') or []))}"
            ),
        },
        "indicator_family": candidate.get("indicator_family"),
        "components": list(candidate.get("components") or []),
        "catalog_candidate_sha256": stable_sha(candidate),
    }


def choose_candidates(
    strategy_id: str,
    family: str,
    candidates: list[dict[str, Any]],
    already_tested: set[str],
    cycle: int,
    limit: int,
) -> list[dict[str, Any]]:
    pool = [
        row for row in candidates
        if family in set(map(str, row.get("compatible_families") or []))
        and str(row["candidate_id"]) not in already_tested
    ]
    pool.sort(key=lambda row: (int(row.get("priority") or 999), str(row.get("indicator_family")), str(row["candidate_id"])))
    if not pool:
        return []
    offset = int(hashlib.sha256(f"{strategy_id}:{cycle}".encode()).hexdigest()[:8], 16) % len(pool)
    ordered = pool[offset:] + pool[:offset]
    front = sorted(ordered[: min(len(ordered), 12)], key=lambda row: (int(row.get("priority") or 999), str(row["candidate_id"])))
    remainder_ids = {str(row["candidate_id"]) for row in front}
    ordered = front + [row for row in ordered if str(row["candidate_id"]) not in remainder_ids]
    selected: list[dict[str, Any]] = []
    axes: set[str] = set()
    indicator_families: set[str] = set()
    for row in ordered:
        axis = str(row["axis"])
        indicator_family = str(row["indicator_family"])
        if axis in axes or indicator_family in indicator_families:
            continue
        selected.append(row)
        axes.add(axis)
        indicator_families.add(indicator_family)
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        for row in ordered:
            if row in selected:
                continue
            axis = str(row["axis"])
            if axis in axes:
                continue
            selected.append(row)
            axes.add(axis)
            if len(selected) >= limit:
                break
    return selected


def build_plan(args: argparse.Namespace) -> int:
    catalog_path = Path(args.catalog).resolve()
    catalog = read_json(catalog_path)
    candidates = validate_catalog(catalog)
    previous = normalize_previous(Path(args.previous_ledger).resolve() if args.previous_ledger else None, catalog)
    cutoff = parse_utc(str(catalog["continue_until_utc"]))
    current = now_utc(args.now_utc)
    cycle = int(previous.get("cycle_index") or 0) + 1
    ledger_rows = {str(row["strategy_id"]): row for row in previous["rows"]}

    rows: list[dict[str, Any]] = []
    exhausted: list[str] = []
    if current < cutoff:
        for strategy_id in STRATEGIES:
            family = FAMILY_MAP[strategy_id]
            prior_row = ledger_rows[strategy_id]
            selected = choose_candidates(
                strategy_id, family, candidates, tested_ids(prior_row), cycle,
                int(catalog["selection_rules"]["max_candidates_per_strategy_cycle"]),
            )
            if not selected:
                exhausted.append(strategy_id)
                continue
            ids = [str(row["candidate_id"]) for row in selected]
            specs = {str(row["candidate_id"]): candidate_spec(row, family) for row in selected}
            rows.append({
                "strategy_id": strategy_id,
                "strategy_alias": strategy_id,
                "family": family,
                "candidate_ids": ids,
                "candidate_specs": specs,
                "cycle_index": cycle,
                "selection_reason": "UNTESTED_FAMILY_COMPATIBLE_DISTINCT_AXIS_ROTATION",
                "falsification_test": "NO_CHANGE parity, duplicate=0, L090 loss ladder, retention, window breadth, economics and 2x-cost/P95-funding/+1-bar stress.",
                "promotion_authority": False,
            })

    state = "COMPLETE_CUTOFF_NO_NEW_REPLAY" if current >= cutoff else (
        "PASS_AUTONOMOUS_INDICATOR_PLAN" if rows else "COMPLETE_CATALOG_EXHAUSTED"
    )
    plan = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": state,
        "cycle_index": cycle,
        "generated_at_utc": current.isoformat().replace("+00:00", "Z"),
        "continue_until_utc": cutoff.isoformat().replace("+00:00", "Z"),
        "catalog_path": str(catalog_path),
        "catalog_sha256": stable_sha(catalog),
        "strategy_count_total": len(STRATEGIES),
        "active_strategy_count": len(rows),
        "candidate_count": sum(len(row["candidate_ids"]) for row in rows),
        "active_strategy_ids": [row["strategy_id"] for row in rows],
        "exhausted_strategy_ids": exhausted,
        "rows": rows,
        "no_change_control_required": True,
        "blind_cartesian_product_used": False,
        "max_candidates_per_strategy_cycle": 2,
        "next": "ISOLATED_REPLAY_AND_LEDGER_UPDATE" if rows else "WAIT_W1_OR_COMPLETE",
        **SAFETY,
    }
    previous["state"] = "PLAN_READY" if rows else state
    previous["cycle_index"] = cycle
    previous["catalog_sha256"] = stable_sha(catalog)
    previous["last_plan_sha256"] = stable_sha(plan)
    previous["last_generated_at_utc"] = plan["generated_at_utc"]
    previous.update(SAFETY)

    coverage = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": state,
        "catalog_candidate_count": len(candidates),
        "catalog_indicator_family_count": len({str(row["indicator_family"]) for row in candidates}),
        "strategy_count": len(STRATEGIES),
        "scheduled_candidate_count": plan["candidate_count"],
        "tested_strategy_candidate_pairs": sum(len(tested_ids(row)) for row in previous["rows"]),
        "unsupported_without_new_source": catalog.get("unsupported_without_new_source", []),
        "all_parameter_cartesian_product_tested": False,
        "bounded_canonical_variants_used": True,
        **SAFETY,
    }
    out = Path(args.out).resolve()
    write_json(out / "plan.json", plan)
    write_json(out / "search_ledger.json", previous)
    write_json(out / "coverage.json", coverage)
    print(json.dumps({"state": state, "cycle": cycle, "strategies": len(rows), "candidates": plan["candidate_count"]}, sort_keys=True))
    return 0


def metric(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def classify_variant(variant: Mapping[str, Any]) -> str:
    ladder = variant.get("ladder_check") if isinstance(variant.get("ladder_check"), Mapping) else {}
    parity = variant.get("parity") if isinstance(variant.get("parity"), Mapping) else {}
    if parity.get("state") != "PASS" or int(parity.get("duplicate_trade_count") or 0) != 0:
        return "HOLD_PARITY_OR_DUPLICATE"
    if int(variant.get("trade_count") or 0) == 0:
        return "REJECT_ZERO_TRADES"
    if ladder.get("research_pass") is True:
        return "PASS_L090_RESEARCH"
    retention = metric(ladder.get("trade_retention_pct"))
    if retention < 50.0:
        return "REJECT_RETENTION"
    normal = metric(ladder.get("normal_worst_net_loss_R"), -math.inf)
    stress = metric(ladder.get("stress_worst_net_loss_R"), -math.inf)
    if normal < -0.90 or stress < -0.95:
        return "REJECT_LOSS_STRESS"
    return "HOLD_NO_PARETO_EDGE"


def find_strategy_summaries(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in root.rglob("summary.json"):
        try:
            row = read_json(path)
        except Exception:
            continue
        if row.get("version") == REPLAY_VERSION and row.get("strategy_id"):
            result[str(row["strategy_id"])] = row
    return result


def update_ledger(args: argparse.Namespace) -> int:
    plan = read_json(Path(args.plan).resolve())
    ledger = read_json(Path(args.ledger).resolve())
    summaries = find_strategy_summaries(Path(args.replay_root).resolve())
    rows_by_id = {str(row["strategy_id"]): row for row in ledger["rows"]}
    tested_rows: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    survivors: list[dict[str, Any]] = []

    for plan_row in plan.get("rows", []):
        strategy_id = str(plan_row["strategy_id"])
        summary = summaries.get(strategy_id)
        if summary is None:
            missing.append({"strategy_id": strategy_id, "reason": "REPLAY_SUMMARY_MISSING"})
            continue
        variants = {
            str(row.get("variant_id")): row
            for row in summary.get("variants", [])
            if isinstance(row, Mapping)
        }
        ledger_row = rows_by_id[strategy_id]
        observed_ids = tested_ids(ledger_row)
        for candidate_id in plan_row["candidate_ids"]:
            candidate_id = str(candidate_id)
            variant = variants.get(candidate_id)
            if variant is None:
                missing.append({"strategy_id": strategy_id, "candidate_id": candidate_id, "reason": "VARIANT_MISSING"})
                continue
            status = classify_variant(variant)
            spec = plan_row["candidate_specs"][candidate_id]
            record = {
                "cycle_index": int(plan["cycle_index"]),
                "strategy_id": strategy_id,
                "candidate_id": candidate_id,
                "candidate_sha256": spec["catalog_candidate_sha256"],
                "axis": spec["axis"],
                "indicator_family": spec["indicator_family"],
                "status": status,
                "trade_count": int(variant.get("trade_count") or 0),
                "net_return_pct_sum": variant.get("net_return_pct_sum"),
                "net_profit_factor": variant.get("net_profit_factor"),
                "payoff_ratio": variant.get("payoff_ratio"),
                "max_drawdown_pct": variant.get("max_drawdown_pct"),
                "positive_fresh_windows_pct": variant.get("positive_fresh_windows_pct"),
                "ladder_check": variant.get("ladder_check"),
            }
            if candidate_id not in observed_ids:
                ledger_row["tested_candidates"].append(record)
                observed_ids.add(candidate_id)
            bucket = (
                "pass_candidates" if status.startswith("PASS_")
                else "rejected_candidates" if status.startswith("REJECT_")
                else "hold_candidates"
            )
            if candidate_id not in set(map(str, ledger_row[bucket])):
                ledger_row[bucket].append(candidate_id)
            ledger_row["last_cycle"] = int(plan["cycle_index"])
            tested_rows.append(record)
            if status == "PASS_L090_RESEARCH":
                survivors.append(record)

    survivors.sort(
        key=lambda row: (
            metric(row.get("net_return_pct_sum")),
            metric(row.get("net_profit_factor")),
            metric(row.get("payoff_ratio")),
            -metric(row.get("max_drawdown_pct"), math.inf),
        ),
        reverse=True,
    )
    ledger["state"] = "PASS_AUTONOMOUS_CYCLE" if not missing else "HOLD_INCOMPLETE_REPLAY"
    ledger["cycle_index"] = int(plan["cycle_index"])
    ledger["last_cycle_tested_count"] = len(tested_rows)
    ledger["last_cycle_missing_count"] = len(missing)
    ledger["last_cycle_survivor_count"] = len(survivors)
    ledger["last_cycle_plan_sha256"] = stable_sha(plan)
    ledger.update(SAFETY)

    all_tested = [
        item for row in ledger["rows"] for item in row.get("tested_candidates", [])
        if isinstance(item, Mapping)
    ]
    status_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    for row in all_tested:
        status = str(row.get("status"))
        family = str(row.get("indicator_family"))
        status_counts[status] = status_counts.get(status, 0) + 1
        family_counts[family] = family_counts.get(family, 0) + 1

    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": ledger["state"],
        "cycle_index": int(plan["cycle_index"]),
        "tested_count_this_cycle": len(tested_rows),
        "missing_count": len(missing),
        "research_survivor_count": len(survivors),
        "top_research_survivors": survivors[:3],
        "missing": missing,
        "status_counts_cumulative": status_counts,
        "indicator_family_test_counts_cumulative": family_counts,
        "tested_strategy_candidate_pairs_cumulative": len(all_tested),
        "continue_until_utc": plan["continue_until_utc"],
        "w1_confirmation_required": True,
        "canonical_mutated": False,
        "registry_mutated": False,
        "next": "NEXT_UNTESTED_INDICATOR_CYCLE" if not missing else "RETRY_MISSING_ONLY",
        **SAFETY,
    }
    out = Path(args.out).resolve()
    write_json(out / "search_ledger.json", ledger)
    write_json(out / "final.json", final)
    write_json(out / "cycle_results.json", {
        "state": final["state"], "rows": tested_rows, "missing": missing, **SAFETY
    })
    print(json.dumps({"state": final["state"], "tested": len(tested_rows), "survivors": len(survivors), "missing": len(missing)}, sort_keys=True))
    return 0 if not missing else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("plan", "update"), required=True)
    parser.add_argument("--catalog")
    parser.add_argument("--previous-ledger")
    parser.add_argument("--now-utc")
    parser.add_argument("--plan")
    parser.add_argument("--ledger")
    parser.add_argument("--replay-root")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.mode == "plan":
        if not args.catalog:
            raise SystemExit("--catalog required")
        return build_plan(args)
    if not all((args.plan, args.ledger, args.replay_root)):
        raise SystemExit("--plan --ledger --replay-root required")
    return update_ledger(args)


if __name__ == "__main__":
    raise SystemExit(main())
