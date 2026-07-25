from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import tempfile
from pathlib import Path
from typing import Any, Mapping


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _metric(value: Any, default: float = 0.0) -> float:
    return float(value) if _finite(value) else default


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _candidate_summary(strategy_summary: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    evaluation = result.get("evaluation") if isinstance(result.get("evaluation"), Mapping) else {}
    metrics = evaluation.get("metrics") if isinstance(evaluation.get("metrics"), Mapping) else {}
    combined = metrics.get("all") if isinstance(metrics.get("all"), Mapping) else {}
    candidate = result.get("candidate") if isinstance(result.get("candidate"), Mapping) else {}
    gate = candidate.get("gate") if isinstance(candidate.get("gate"), Mapping) else {}
    exit_value = candidate.get("exit") if isinstance(candidate.get("exit"), Mapping) else {}
    return {
        "strategy_id": str(strategy_summary.get("strategy_id")),
        "family": str(strategy_summary.get("family")),
        "lane": str(candidate.get("lane") or "RETURN"),
        "mode": str(result.get("mode") or "BASE_EXACT"),
        "gate_id": str(gate.get("gate_id") or "BASE"),
        "exit_id": str(exit_value.get("exit_id") or "ORIG"),
        "symbols": list(result.get("symbols") or []),
        "surgery": result.get("surgery"),
        "score": _metric(evaluation.get("score"), -math.inf),
        "trade_count": int(combined.get("trade_count") or 0),
        "win_count": int(combined.get("win_count") or 0),
        "loss_count": int(combined.get("loss_count") or 0),
        "win_rate_pct": _metric(combined.get("win_rate_pct")),
        "net_return_pct_sum": _metric(combined.get("net_return_pct_sum")),
        "net_profit_factor": _metric(combined.get("net_profit_factor")),
        "payoff_ratio": _metric(combined.get("payoff_ratio")),
        "max_drawdown_pct_conservative_sum": _metric(combined.get("max_drawdown_pct_conservative_sum")),
        "positive_windows": evaluation.get("positive_windows"),
        "positive_symbols": evaluation.get("positive_symbols"),
        "failure_reasons": list(evaluation.get("failure_reasons") or []),
        "pass": bool(evaluation.get("pass")),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exact-root", required=True)
    parser.add_argument("--output", default="artifacts/strategy11_final_roster_v1/summary.json")
    parser.add_argument("--target", type=int, default=11)
    args = parser.parse_args()

    exact_root = Path(args.exact_root)
    summaries: list[dict[str, Any]] = []
    blockers: list[str] = []
    for path in sorted(exact_root.rglob("summary.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("authority") != "READ_ONLY_EXACT_NO_EXECUTION":
                continue
            summaries.append(payload)
            blockers.extend(str(value) for value in payload.get("blockers", []))
        except Exception as exc:
            blockers.append(f"{path}:{type(exc).__name__}:{exc}")

    accepted_by_strategy: dict[str, dict[str, Any]] = {}
    near_misses: list[dict[str, Any]] = []
    for summary in summaries:
        strategy_id = str(summary.get("strategy_id"))
        accepted = summary.get("accepted") if isinstance(summary.get("accepted"), list) else []
        if accepted:
            best = max(
                (_candidate_summary(summary, value) for value in accepted if isinstance(value, Mapping)),
                key=lambda value: float(value["score"]),
            )
            accepted_by_strategy[strategy_id] = best
        elif isinstance(summary.get("best"), Mapping):
            near_misses.append(_candidate_summary(summary, summary["best"]))

    accepted = sorted(accepted_by_strategy.values(), key=lambda value: float(value["score"]), reverse=True)
    roster: list[dict[str, Any]] = []
    family_counts: dict[str, int] = {}
    lane_counts: dict[str, int] = {"RETURN": 0, "WINRATE": 0}

    for candidate in accepted:
        family = candidate["family"]
        lane = candidate["lane"]
        if family_counts.get(family, 0) >= 3:
            continue
        if len(roster) >= args.target:
            break
        roster.append(candidate)
        family_counts[family] = family_counts.get(family, 0) + 1
        lane_counts[lane] = lane_counts.get(lane, 0) + 1

    selected_ids = {value["strategy_id"] for value in roster}
    for candidate in accepted:
        if len(roster) >= args.target:
            break
        if candidate["strategy_id"] in selected_ids:
            continue
        family = candidate["family"]
        if family_counts.get(family, 0) >= 4:
            continue
        roster.append(candidate)
        selected_ids.add(candidate["strategy_id"]
        )
        family_counts[family] = family_counts.get(family, 0) + 1
        lane_counts[candidate["lane"]] = lane_counts.get(candidate["lane"], 0) + 1

    family_total = len({value["family"] for value in roster})
    pf_values = [value["net_profit_factor"] for value in roster]
    net_values = [value["net_return_pct_sum"] for value in roster]
    wr_values = [value["win_rate_pct"] for value in roster]
    trades_values = [value["trade_count"] for value in roster]
    summary_metrics = {
        "count": len(roster),
        "family_count": family_total,
        "return_lane_count": lane_counts.get("RETURN", 0),
        "winrate_lane_count": lane_counts.get("WINRATE", 0),
        "median_profit_factor": statistics.median(pf_values) if pf_values else None,
        "median_net_return_pct_sum": statistics.median(net_values) if net_values else None,
        "median_win_rate_pct": statistics.median(wr_values) if wr_values else None,
        "total_trade_count": sum(trades_values),
        "minimum_trade_count": min(trades_values) if trades_values else 0,
    }

    meaningful = bool(
        not blockers
        and len(roster) >= 10
        and family_total >= 4
        and lane_counts.get("RETURN", 0) >= 4
        and lane_counts.get("WINRATE", 0) >= 3
        and _metric(summary_metrics["median_profit_factor"]) > 1.10
        and _metric(summary_metrics["median_net_return_pct_sum"]) > 2.0
        and _metric(summary_metrics["median_win_rate_pct"]) >= 35.0
        and int(summary_metrics["minimum_trade_count"]) >= 35
    )

    near_misses.sort(key=lambda value: float(value["score"]), reverse=True)
    report = {
        "schema_version": "1.0",
        "authority": "READ_ONLY_FINAL_ROSTER_NO_EXECUTION",
        "state": "PASS" if not blockers else "HOLD",
        "meaningful_strategy_roster": meaningful,
        "target_count": args.target,
        "exact_summary_count": len(summaries),
        "accepted_unique_strategy_count": len(accepted),
        "roster": roster,
        "roster_metrics": summary_metrics,
        "family_counts": family_counts,
        "lane_counts": lane_counts,
        "near_misses": near_misses[:15],
        "blockers": blockers,
        "canonical_mutated": False,
        "registry_mutated": False,
        "route_allowed": False,
        "shadow_allowed": meaningful,
        "paper_allowed": False,
        "live_allowed": False,
        "execution_allowed": False,
        "next": "SHADOW_CANARY_ROSTER_REVIEW" if meaningful else "SECOND_PASS_PARAMETER_AND_TIMEFRAME_SEARCH",
    }
    _atomic_json(Path(args.output), report)
    print(json.dumps({
        "STATE": report["state"],
        "MEANINGFUL": meaningful,
        "ACCEPTED_UNIQUE": len(accepted),
        "ROSTER_COUNT": len(roster),
        "METRICS": summary_metrics,
        "ROSTER": roster,
        "NEXT": report["next"],
        "BLOCKERS": blockers,
    }, sort_keys=True))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
