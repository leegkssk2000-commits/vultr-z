from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

VERSION = "ZEL_STRUCTURAL_PREMIUM_AUTO_IMPROVEMENT_V1"
OVERLAY_SCHEMA = "zel.structural_premium.overlay.v1"
MAX_GENERATION = 12
MIN_SCORE_DELTA = 0.10


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def load_json(path: Path) -> dict[str, Any]:
    row = json.loads(path.read_text())
    if not isinstance(row, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return row


def metrics(result: dict[str, Any]) -> dict[str, Any]:
    selected = result.get("selected") or {}
    windows = selected.get("windows") or {}
    rows = [windows.get(name) or {} for name in ("W1", "W2", "W3")]
    if any(not row for row in rows):
        raise RuntimeError("SELECTED_WINDOWS_MISSING")
    total_net = sum(float(row.get("net_R") or 0.0) for row in rows)
    total_trades = sum(int(row.get("trade_count") or 0) for row in rows)
    mean_expectancy = sum(float(row.get("expectancy_R") or 0.0) for row in rows) / 3.0
    mean_pf = sum(min(5.0, float(row.get("profit_factor") or 0.0)) for row in rows) / 3.0
    mean_win = sum(float(row.get("win_rate_pct") or 0.0) for row in rows) / 3.0
    mean_payoff = sum(min(5.0, float(row.get("payoff_ratio") or 0.0)) for row in rows) / 3.0
    max_dd = max(float(row.get("max_drawdown_R") or 0.0) for row in rows)
    min_pf = min(float(row.get("profit_factor") or 0.0) for row in rows)
    min_trades = min(int(row.get("trade_count") or 0) for row in rows)
    score = (
        total_net
        - 0.60 * max_dd
        + 3.0 * mean_expectancy
        + 0.50 * max(0.0, mean_pf - 1.0)
        + 0.010 * mean_win
        + 0.30 * max(0.0, mean_payoff - 1.0)
        + 0.002 * total_trades
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
        "survivor": bool(result.get("survivor")),
        "integrity_all_pass": bool((result.get("integrity") or {}).get("all_pass")),
        "coverage_restored": bool((result.get("coverage") or {}).get("coverage_restored")),
        "window_absolute_gates": dict(result.get("window_absolute_gates") or {}),
        "receipt_sha256": str(result.get("receipt_sha256") or ""),
        "selected_configuration": str((result.get("selection") or {}).get("selected_configuration") or ""),
        "windows": windows,
    }


def candidate(candidate_id: str, generation: int, axis: str, stop: float, target: float, confidence: float | None) -> dict[str, Any]:
    return {
        "schema_version": OVERLAY_SCHEMA,
        "candidate_id": candidate_id,
        "generation": generation,
        "axis": axis,
        "parameters": {
            "stop_distance_mult": round(clamp(stop, 0.70, 1.25), 6),
            "target_distance_mult": round(clamp(target, 0.80, 1.50), 6),
            "min_confidence": None if confidence is None else round(clamp(confidence, 0.0, 0.90), 6),
        },
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }


def build_catalog(incumbent: dict[str, Any], baseline: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    generation = int(incumbent.get("generation") or 0)
    params = incumbent.get("parameters") or {}
    stop = float(params.get("stop_distance_mult", 1.0))
    target = float(params.get("target_distance_mult", 1.0))
    confidence = params.get("min_confidence")
    confidence = None if confidence is None else float(confidence)
    baseline_metrics = metrics(baseline)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    if generation < MAX_GENERATION:
        next_gen = generation + 1
        proposals = [
            candidate(f"G{next_gen:02d}_STOP_TIGHTEN", next_gen, "STOP", stop * 0.95, target, confidence),
            candidate(f"G{next_gen:02d}_TARGET_EXTEND", next_gen, "TARGET", stop, target * 1.05, confidence),
            candidate(f"G{next_gen:02d}_RR_EXPAND", next_gen, "STOP_TARGET", stop * 0.95, target * 1.05, confidence),
            candidate(f"G{next_gen:02d}_CONF_GATE", next_gen, "ENTRY_CONFIDENCE", stop, target, 0.55 if confidence is None else confidence + 0.05),
        ]
        seen: set[str] = set()
        base_key = json.dumps({"stop": stop, "target": target, "confidence": confidence}, sort_keys=True)
        for row in proposals:
            key = json.dumps(row["parameters"], sort_keys=True)
            if key == base_key or key in seen:
                continue
            seen.add(key)
            rows.append(row)
            (out_dir / f"{row['candidate_id']}.json").write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    catalog = {
        "schema_version": "zel.structural_premium.auto_improvement.catalog.v1",
        "state": "PASS_AUTO_IMPROVEMENT_CATALOG_READY" if rows else "STOP_AUTO_IMPROVEMENT_GENERATION_CAP",
        "version": VERSION,
        "incumbent_generation": generation,
        "max_generation": MAX_GENERATION,
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


def admissible(base: dict[str, Any], cand: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not cand["integrity_all_pass"]:
        reasons.append("INTEGRITY_FAIL")
    if not cand["coverage_restored"]:
        reasons.append("COVERAGE_FAIL")
    if cand["min_trade_count"] < max(20, int(math.floor(base["min_trade_count"] * 0.75))):
        reasons.append("TRADE_COLLAPSE")
    if cand["max_drawdown_R"] > base["max_drawdown_R"] * 1.15 + 0.25:
        reasons.append("DD_REGRESSION")
    for window in ("W2", "W3"):
        b = float((base["windows"].get(window) or {}).get("net_R") or 0.0)
        c = float((cand["windows"].get(window) or {}).get("net_R") or 0.0)
        tolerance = max(0.50, abs(b) * 0.15)
        if c < b - tolerance:
            reasons.append(f"{window}_NET_R_REGRESSION")
    improved = cand["score"] >= base["score"] + MIN_SCORE_DELTA
    survivor_upgrade = cand["survivor"] and not base["survivor"]
    if not improved and not survivor_upgrade:
        reasons.append("DELTA_BELOW_MIN")
    return not reasons, reasons


def select_candidate(incumbent: dict[str, Any], baseline: dict[str, Any], candidates_dir: Path, output: Path) -> dict[str, Any]:
    base_metrics = metrics(baseline)
    evaluated: list[dict[str, Any]] = []
    for candidate_path in sorted(candidates_dir.glob("G*.json")):
        row = load_json(candidate_path)
        candidate_id = str(row.get("candidate_id") or candidate_path.stem)
        result_path = candidates_dir / candidate_id / "coverage_revalidation.json"
        failure_path = candidates_dir / candidate_id / "failure.json"
        if not result_path.is_file():
            evaluated.append({"candidate_id": candidate_id, "status": "FAILED_REPLAY", "failure": load_json(failure_path) if failure_path.is_file() else {"error": "RESULT_MISSING"}})
            continue
        result = load_json(result_path)
        cand_metrics = metrics(result)
        ok, reasons = admissible(base_metrics, cand_metrics)
        evaluated.append({
            "candidate_id": candidate_id,
            "status": "ADMISSIBLE" if ok else "REJECTED",
            "candidate": row,
            "metrics": cand_metrics,
            "reasons": reasons,
        })
    eligible = [row for row in evaluated if row.get("status") == "ADMISSIBLE"]
    winner = max(eligible, key=lambda row: (float(row["metrics"]["score"]), float(row["metrics"]["total_net_R"]), float(row["metrics"]["mean_win_rate_pct"]))) if eligible else None
    accepted = winner is not None
    new_incumbent = None
    if accepted:
        c = winner["candidate"]
        new_incumbent = {
            "schema_version": OVERLAY_SCHEMA,
            "candidate_id": c["candidate_id"],
            "generation": int(c["generation"]),
            "axis": c["axis"],
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
        "schema_version": "zel.structural_premium.auto_improvement.selection.v1",
        "state": "PASS_AUTO_IMPROVEMENT_ACCEPTED" if accepted else "PASS_AUTO_IMPROVEMENT_PLATEAU",
        "version": VERSION,
        "accepted": accepted,
        "baseline_metrics": base_metrics,
        "evaluated": evaluated,
        "winner": winner,
        "new_incumbent": new_incumbent,
        "min_score_delta": MIN_SCORE_DELTA,
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
        row = {"trade_count": trades, "net_R": net, "profit_factor": pf, "expectancy_R": exp, "win_rate_pct": win, "payoff_ratio": payoff, "max_drawdown_R": dd}
        return {
            "selected": {"windows": {"W1": dict(row), "W2": dict(row), "W3": dict(row)}},
            "survivor": survivor,
            "integrity": {"all_pass": True},
            "coverage": {"coverage_restored": True},
            "window_absolute_gates": {"W1": True, "W2": True, "W3": True},
            "receipt_sha256": "a" * 64,
            "selection": {"selected_configuration": "MAIN_ONLY"},
        }
    base = metrics(result(2, 1.2, 0.1, 55, 1.1, 2, 30))
    better = metrics(result(3, 1.4, 0.15, 58, 1.2, 1.8, 32))
    ok, reasons = admissible(base, better)
    assert ok and not reasons
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


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
    if args.command == "self-test": self_test(); return 0
    if args.command == "catalog":
        row = build_catalog(load_json(args.incumbent), load_json(args.baseline), args.out_dir)
        print(json.dumps({"state": row["state"], "candidate_count": row["candidate_count"], "incumbent_generation": row["incumbent_generation"]}, sort_keys=True)); return 0
    row = select_candidate(load_json(args.incumbent), load_json(args.baseline), args.candidates_dir, args.output)
    print(json.dumps({"state": row["state"], "accepted": row["accepted"], "winner": None if row["winner"] is None else row["winner"]["candidate_id"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
