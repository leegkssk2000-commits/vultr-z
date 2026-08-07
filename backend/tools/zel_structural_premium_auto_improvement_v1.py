from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

VERSION = "ZEL_STRUCTURAL_PREMIUM_AUTO_IMPROVEMENT_V2_SIX_AXIS"
OVERLAY_SCHEMA = "zel.structural_premium.overlay.v1"
MAX_GENERATION = 12
MIN_SCORE_DELTA = 0.10
MULTIPLE_TEST_PENALTY = 0.03
ENTRY_OWNERS = ("vwap_revert", "support_resistance", "liquidity_sweep", "trend_rider")
MAIN_OWNERS = ("vwap_revert", "support_resistance")
SIX_AXES = (
    "FREQUENCY",
    "COST_EXECUTION",
    "RISK_EXPOSURE",
    "INTERACTION",
    "PORTFOLIO",
    "ROBUSTNESS",
)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def load_json(path: Path) -> dict[str, Any]:
    row = json.loads(path.read_text())
    if not isinstance(row, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return row


def normalized_parameters(row: dict[str, Any]) -> dict[str, Any]:
    params = row.get("parameters") or {}
    confidence = params.get("min_confidence")
    confidence = None if confidence is None else float(confidence)
    owners = params.get("enabled_entry_owners")
    if not isinstance(owners, list) or not owners:
        owners = list(ENTRY_OWNERS)
    owners = [name for name in ENTRY_OWNERS if name in {str(x) for x in owners}]
    if not all(name in owners for name in MAIN_OWNERS):
        owners = list(dict.fromkeys([*MAIN_OWNERS, *owners]))
    return {
        "stop_distance_mult": round(clamp(float(params.get("stop_distance_mult", 1.0)), 0.70, 1.25), 6),
        "target_distance_mult": round(clamp(float(params.get("target_distance_mult", 1.0)), 0.80, 1.50), 6),
        "min_confidence": None if confidence is None else round(clamp(confidence, 0.0, 0.90), 6),
        "cooldown_min": round(clamp(float(params.get("cooldown_min", 0.0)), 0.0, 120.0), 6),
        "min_risk_distance_pct": round(clamp(float(params.get("min_risk_distance_pct", 0.0)), 0.0, 2.0), 6),
        "max_hold_min": round(clamp(float(params.get("max_hold_min", 120.0)), 15.0, 240.0), 6),
        "enabled_entry_owners": owners,
    }


def metrics(result: dict[str, Any]) -> dict[str, Any]:
    selected = result.get("selected") or {}
    windows = selected.get("windows") or {}
    rows = [windows.get(name) or {} for name in ("W1", "W2", "W3")]
    if any(not row for row in rows):
        raise RuntimeError("SELECTED_WINDOWS_MISSING")
    nets = [float(row.get("net_R") or 0.0) for row in rows]
    total_net = sum(nets)
    total_trades = sum(int(row.get("trade_count") or 0) for row in rows)
    mean_expectancy = sum(float(row.get("expectancy_R") or 0.0) for row in rows) / 3.0
    mean_pf = sum(min(5.0, float(row.get("profit_factor") or 0.0)) for row in rows) / 3.0
    mean_win = sum(float(row.get("win_rate_pct") or 0.0) for row in rows) / 3.0
    mean_payoff = sum(min(5.0, float(row.get("payoff_ratio") or 0.0)) for row in rows) / 3.0
    max_dd = max(float(row.get("max_drawdown_R") or 0.0) for row in rows)
    min_pf = min(float(row.get("profit_factor") or 0.0) for row in rows)
    min_trades = min(int(row.get("trade_count") or 0) for row in rows)
    min_window_net = min(nets)
    window_net_spread = max(nets) - min(nets)
    per_strategy = result.get("per_strategy") or {}
    owner_trade_counts: dict[str, int] = {}
    for owner in ENTRY_OWNERS:
        node = per_strategy.get(owner) or {}
        owner_trade_counts[owner] = sum(
            int(((node.get(window) or {}).get("trade_count")) or 0)
            for window in ("W1", "W2", "W3")
        )
    total_owner_trades = sum(owner_trade_counts.values())
    largest_owner_trade_share = (
        max(owner_trade_counts.values()) / total_owner_trades if total_owner_trades else 1.0
    )
    score = (
        total_net
        - 0.60 * max_dd
        + 3.0 * mean_expectancy
        + 0.50 * max(0.0, mean_pf - 1.0)
        + 0.010 * mean_win
        + 0.30 * max(0.0, mean_payoff - 1.0)
        + 0.002 * total_trades
        + 0.35 * min_window_net
        - 0.12 * window_net_spread
        - 0.40 * largest_owner_trade_share
    )
    return {
        "score": score,
        "total_net_R": total_net,
        "total_trade_count": total_trades,
        "min_trade_count": min_trades,
        "mean_expectancy_R": mean_expectancy,
        "mean_profit_factor": mean_pf,
        "min_profit_factor": min_pf,
        "mean_win_rate_pct": mean_win,
        "mean_payoff_ratio": mean_payoff,
        "max_drawdown_R": max_dd,
        "min_window_net_R": min_window_net,
        "window_net_spread_R": window_net_spread,
        "largest_owner_trade_share": largest_owner_trade_share,
        "owner_trade_counts": owner_trade_counts,
        "survivor": bool(result.get("survivor")),
        "integrity_all_pass": bool((result.get("integrity") or {}).get("all_pass")),
        "coverage_restored": bool((result.get("coverage") or {}).get("coverage_restored")),
        "window_absolute_gates": dict(result.get("window_absolute_gates") or {}),
        "receipt_sha256": str(result.get("receipt_sha256") or ""),
        "selected_configuration": str((result.get("selection") or {}).get("selected_configuration") or ""),
        "windows": windows,
    }


def candidate(
    candidate_id: str,
    generation: int,
    axis: str,
    base_params: dict[str, Any],
    **overrides: Any,
) -> dict[str, Any]:
    params = dict(base_params)
    params.update(overrides)
    normalized = normalized_parameters({"parameters": params})
    return {
        "schema_version": OVERLAY_SCHEMA,
        "candidate_id": candidate_id,
        "generation": generation,
        "axis": axis,
        "closed_loop_axes": list(SIX_AXES),
        "parameters": normalized,
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }


def reserve_to_drop(baseline: dict[str, Any]) -> str:
    per_strategy = baseline.get("per_strategy") or {}
    scored: list[tuple[float, int, str]] = []
    for owner in ("liquidity_sweep", "trend_rider"):
        node = per_strategy.get(owner) or {}
        net = sum(float(((node.get(window) or {}).get("net_R")) or 0.0) for window in ("W1", "W2", "W3"))
        trades = sum(int(((node.get(window) or {}).get("trade_count")) or 0) for window in ("W1", "W2", "W3"))
        scored.append((net, trades, owner))
    return min(scored)[2]


def build_catalog(incumbent: dict[str, Any], baseline: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    generation = int(incumbent.get("generation") or 0)
    params = normalized_parameters(incumbent)
    baseline_metrics = metrics(baseline)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    if generation < MAX_GENERATION:
        next_gen = generation + 1
        conf = params["min_confidence"]
        conf_up = 0.55 if conf is None else float(conf) + 0.05
        cooldown = float(params["cooldown_min"])
        risk_floor = float(params["min_risk_distance_pct"])
        max_hold = float(params["max_hold_min"])
        stop = float(params["stop_distance_mult"])
        target = float(params["target_distance_mult"])
        owners = list(params["enabled_entry_owners"])
        drop = reserve_to_drop(baseline)
        portfolio_owners = [name for name in owners if name != drop]
        if not all(name in portfolio_owners for name in MAIN_OWNERS):
            portfolio_owners = list(MAIN_OWNERS)
        proposals = [
            candidate(
                f"G{next_gen:02d}_FREQUENCY",
                next_gen,
                "FREQUENCY",
                params,
                min_confidence=conf_up,
                cooldown_min=cooldown + 5.0,
            ),
            candidate(
                f"G{next_gen:02d}_COST_EXECUTION",
                next_gen,
                "COST_EXECUTION",
                params,
                min_risk_distance_pct=(0.15 if risk_floor <= 0.0 else risk_floor + 0.05),
                target_distance_mult=target * 1.03,
            ),
            candidate(
                f"G{next_gen:02d}_RISK_EXPOSURE",
                next_gen,
                "RISK_EXPOSURE",
                params,
                stop_distance_mult=stop * 0.95,
                max_hold_min=max_hold * 0.90,
            ),
            candidate(
                f"G{next_gen:02d}_INTERACTION",
                next_gen,
                "INTERACTION",
                params,
                min_confidence=(0.525 if conf is None else float(conf) + 0.025),
                min_risk_distance_pct=(0.10 if risk_floor <= 0.0 else risk_floor + 0.025),
                target_distance_mult=target * 1.04,
                cooldown_min=cooldown + 3.0,
            ),
            candidate(
                f"G{next_gen:02d}_PORTFOLIO",
                next_gen,
                "PORTFOLIO",
                params,
                enabled_entry_owners=portfolio_owners,
            ),
            candidate(
                f"G{next_gen:02d}_ROBUSTNESS",
                next_gen,
                "ROBUSTNESS",
                params,
                stop_distance_mult=stop * 0.98,
                target_distance_mult=target * 1.02,
                cooldown_min=cooldown + 2.0,
                min_risk_distance_pct=(0.05 if risk_floor <= 0.0 else risk_floor + 0.02),
                max_hold_min=max_hold * 0.95,
            ),
        ]
        seen: set[str] = set()
        base_key = json.dumps(params, sort_keys=True)
        for row in proposals:
            key = json.dumps(row["parameters"], sort_keys=True)
            if key == base_key or key in seen:
                continue
            seen.add(key)
            rows.append(row)
            (out_dir / f"{row['candidate_id']}.json").write_text(
                json.dumps(row, indent=2, sort_keys=True) + "\n"
            )
    catalog = {
        "schema_version": "zel.structural_premium.auto_improvement.catalog.v2",
        "state": "PASS_AUTO_IMPROVEMENT_SIX_AXIS_CATALOG_READY" if rows else "STOP_AUTO_IMPROVEMENT_GENERATION_CAP",
        "version": VERSION,
        "incumbent_generation": generation,
        "max_generation": MAX_GENERATION,
        "closed_loop_axes": list(SIX_AXES),
        "baseline_metrics": baseline_metrics,
        "candidate_count": len(rows),
        "candidates": rows,
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    (out_dir / "catalog.json").write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n")
    return catalog


def admissible(
    base: dict[str, Any],
    cand: dict[str, Any],
    axis: str,
    candidate_count: int,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not cand["integrity_all_pass"]:
        reasons.append("INTEGRITY_FAIL")
    if not cand["coverage_restored"]:
        reasons.append("COVERAGE_FAIL")
    retention_floor = 0.60 if axis == "PORTFOLIO" else 0.75
    if cand["min_trade_count"] < max(20, int(math.floor(base["min_trade_count"] * retention_floor))):
        reasons.append("TRADE_COLLAPSE")
    if cand["max_drawdown_R"] > base["max_drawdown_R"] * 1.15 + 0.25:
        reasons.append("DD_REGRESSION")
    for window in ("W2", "W3"):
        b = float((base["windows"].get(window) or {}).get("net_R") or 0.0)
        c = float((cand["windows"].get(window) or {}).get("net_R") or 0.0)
        tolerance = max(0.50, abs(b) * 0.15)
        if c < b - tolerance:
            reasons.append(f"{window}_NET_R_REGRESSION")
    if axis == "COST_EXECUTION" and cand["mean_payoff_ratio"] < base["mean_payoff_ratio"] - 0.10:
        reasons.append("PAYOFF_REGRESSION")
    if axis == "RISK_EXPOSURE" and cand["max_drawdown_R"] > base["max_drawdown_R"] + 1e-9:
        reasons.append("RISK_AXIS_DD_NOT_IMPROVED")
    if axis == "PORTFOLIO" and cand["largest_owner_trade_share"] > max(0.80, base["largest_owner_trade_share"] + 0.10):
        reasons.append("PORTFOLIO_CONCENTRATION")
    if axis == "ROBUSTNESS":
        if cand["min_window_net_R"] < base["min_window_net_R"] - 0.10:
            reasons.append("WORST_WINDOW_REGRESSION")
        if cand["window_net_spread_R"] > base["window_net_spread_R"] * 1.10 + 0.25:
            reasons.append("WINDOW_FRAGILITY")
    adjusted_candidate_score = cand["score"] - MULTIPLE_TEST_PENALTY * max(1, candidate_count)
    improved = adjusted_candidate_score >= base["score"] + MIN_SCORE_DELTA
    survivor_upgrade = cand["survivor"] and not base["survivor"]
    if not improved and not survivor_upgrade:
        reasons.append("DELTA_BELOW_MIN_AFTER_MULTIPLE_TEST_PENALTY")
    return not reasons, reasons


def select_candidate(
    incumbent: dict[str, Any],
    baseline: dict[str, Any],
    candidates_dir: Path,
    output: Path,
) -> dict[str, Any]:
    base_metrics = metrics(baseline)
    candidate_paths = sorted(candidates_dir.glob("G*.json"))
    evaluated: list[dict[str, Any]] = []
    for candidate_path in candidate_paths:
        row = load_json(candidate_path)
        candidate_id = str(row.get("candidate_id") or candidate_path.stem)
        axis = str(row.get("axis") or "UNKNOWN")
        result_path = candidates_dir / candidate_id / "coverage_revalidation.json"
        failure_path = candidates_dir / candidate_id / "failure.json"
        if not result_path.is_file():
            evaluated.append({
                "candidate_id": candidate_id,
                "axis": axis,
                "status": "FAILED_REPLAY",
                "failure": load_json(failure_path) if failure_path.is_file() else {"error": "RESULT_MISSING"},
            })
            continue
        result = load_json(result_path)
        cand_metrics = metrics(result)
        ok, reasons = admissible(base_metrics, cand_metrics, axis, len(candidate_paths))
        evaluated.append({
            "candidate_id": candidate_id,
            "axis": axis,
            "status": "ADMISSIBLE" if ok else "REJECTED",
            "candidate": row,
            "metrics": cand_metrics,
            "reasons": reasons,
        })
    eligible = [row for row in evaluated if row.get("status") == "ADMISSIBLE"]
    winner = max(
        eligible,
        key=lambda row: (
            float(row["metrics"]["score"]),
            float(row["metrics"]["min_window_net_R"]),
            float(row["metrics"]["total_net_R"]),
            float(row["metrics"]["mean_win_rate_pct"]),
        ),
    ) if eligible else None
    accepted = winner is not None
    new_incumbent = None
    if accepted:
        c = winner["candidate"]
        new_incumbent = {
            "schema_version": OVERLAY_SCHEMA,
            "candidate_id": c["candidate_id"],
            "generation": int(c["generation"]),
            "axis": c["axis"],
            "closed_loop_axes": list(SIX_AXES),
            "parameters": c["parameters"],
            "parent_candidate_id": str(incumbent.get("candidate_id") or "BASELINE"),
            "parent_generation": int(incumbent.get("generation") or 0),
            "baseline_receipt_sha256": base_metrics["receipt_sha256"],
            "candidate_receipt_sha256": winner["metrics"]["receipt_sha256"],
            "accepted_score": winner["metrics"]["score"],
            "previous_score": base_metrics["score"],
            "research_only": True,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        }
    selection = {
        "schema_version": "zel.structural_premium.auto_improvement.selection.v2",
        "state": "PASS_AUTO_IMPROVEMENT_SIX_AXIS_ACCEPTED" if accepted else "PASS_AUTO_IMPROVEMENT_SIX_AXIS_PLATEAU",
        "version": VERSION,
        "accepted": accepted,
        "closed_loop_axes": list(SIX_AXES),
        "baseline_metrics": base_metrics,
        "evaluated": evaluated,
        "winner": winner,
        "new_incumbent": new_incumbent,
        "min_score_delta": MIN_SCORE_DELTA,
        "multiple_test_penalty_per_candidate": MULTIPLE_TEST_PENALTY,
        "research_only": True,
        "canonical_source_mutations": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(selection, indent=2, sort_keys=True) + "\n")
    return selection


def self_test() -> None:
    def result(net: float, pf: float, exp: float, win: float, payoff: float, dd: float, trades: int, survivor: bool = False) -> dict[str, Any]:
        row = {
            "trade_count": trades,
            "net_R": net,
            "profit_factor": pf,
            "expectancy_R": exp,
            "win_rate_pct": win,
            "payoff_ratio": payoff,
            "max_drawdown_R": dd,
        }
        per_strategy = {
            owner: {window: {"trade_count": max(1, trades // len(ENTRY_OWNERS)), "net_R": net / len(ENTRY_OWNERS)}
                    for window in ("W1", "W2", "W3")}
            for owner in ENTRY_OWNERS
        }
        return {
            "selected": {"windows": {"W1": dict(row), "W2": dict(row), "W3": dict(row)}},
            "per_strategy": per_strategy,
            "survivor": survivor,
            "integrity": {"all_pass": True},
            "coverage": {"coverage_restored": True},
            "window_absolute_gates": {"W1": True, "W2": True, "W3": True},
            "receipt_sha256": "a" * 64,
            "selection": {"selected_configuration": "MAIN_ONLY"},
        }
    base_result = result(2, 1.2, 0.1, 55, 1.1, 2, 30)
    better_result = result(4, 1.5, 0.2, 60, 1.3, 1.5, 32)
    base = metrics(base_result)
    better = metrics(better_result)
    ok, reasons = admissible(base, better, "FREQUENCY", 1)
    assert ok and not reasons, reasons
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        inc = {
            "schema_version": OVERLAY_SCHEMA,
            "candidate_id": "BASELINE_IDENTITY",
            "generation": 0,
            "parameters": {
                "stop_distance_mult": 1.0,
                "target_distance_mult": 1.0,
                "min_confidence": None,
            },
        }
        catalog = build_catalog(inc, base_result, Path(tmp))
        assert catalog["candidate_count"] == 6, catalog
        assert {row["axis"] for row in catalog["candidates"]} == set(SIX_AXES)
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION, "axes": SIX_AXES}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("catalog")
    c.add_argument("--incumbent", type=Path, required=True)
    c.add_argument("--baseline", type=Path, required=True)
    c.add_argument("--out-dir", type=Path, required=True)
    s = sub.add_parser("select")
    s.add_argument("--incumbent", type=Path, required=True)
    s.add_argument("--baseline", type=Path, required=True)
    s.add_argument("--candidates-dir", type=Path, required=True)
    s.add_argument("--output", type=Path, required=True)
    sub.add_parser("self-test")
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
        return 0
    if args.command == "catalog":
        row = build_catalog(load_json(args.incumbent), load_json(args.baseline), args.out_dir)
        print(json.dumps({
            "state": row["state"],
            "candidate_count": row["candidate_count"],
            "incumbent_generation": row["incumbent_generation"],
            "axes": row["closed_loop_axes"],
        }, sort_keys=True))
        return 0
    row = select_candidate(load_json(args.incumbent), load_json(args.baseline), args.candidates_dir, args.output)
    print(json.dumps({
        "state": row["state"],
        "accepted": row["accepted"],
        "winner": None if row["winner"] is None else row["winner"]["candidate_id"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
