from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_strategy25_active_deep_replay_v1 as deep

ROOT = Path(__file__).resolve().parents[3]
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
    "action": "hold",
}

# Rounded, dimensionless gates selected only after chronological 60/40 screening.
# Supertrend/Keltner stay unchanged because no simple scale-free entry gate passed
# the same train/holdout screen.  This file is research-only; policy source is not
# mutated and no promotion/order authority is granted.
CANDIDATE: dict[str, dict[str, float]] = {
    "trend_rider": {"signal_body_atr_max": 0.40},
    "break_and_continue": {"signal_body_atr_min": 1.10},
    "trend_ma_macd": {"chase_atr_max": 0.70},
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")


def body_atr_from_bar(bar: Mapping[str, Any], atr_value: float) -> float | None:
    if atr_value <= 0:
        return None
    return abs(float(bar["close"]) - float(bar["open"])) / atr_value


def gate_reasons(strategy_id: str, *, body_atr: float | None, chase_atr: float | None) -> tuple[str, ...]:
    rule = CANDIDATE.get(strategy_id) or {}
    reasons: list[str] = []
    lo = rule.get("signal_body_atr_min")
    hi = rule.get("signal_body_atr_max")
    chase_hi = rule.get("chase_atr_max")
    if lo is not None and (body_atr is None or body_atr < lo):
        reasons.append("SIGNAL_BODY_ATR_BELOW_MIN")
    if hi is not None and (body_atr is None or body_atr > hi):
        reasons.append("SIGNAL_BODY_ATR_ABOVE_MAX")
    if chase_hi is not None and (chase_atr is None or chase_atr > chase_hi):
        reasons.append("CHASE_ATR_ABOVE_MAX")
    return tuple(reasons)


def compact_metrics(receipt: dict[str, Any]) -> dict[str, Any]:
    metrics = receipt.get("metrics") or {}
    return {
        "completed_trades": int(receipt.get("completed_trades") or 0),
        "win_rate": metrics.get("win_rate"),
        "net_pnl_bps": metrics.get("net_pnl_bps"),
        "net_expectancy_bps": metrics.get("net_expectancy_bps"),
        "profit_factor": metrics.get("net_profit_factor"),
        "drawdown_bps": metrics.get("max_drawdown_bps"),
    }


def metric_delta(base: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("completed_trades", "win_rate", "net_pnl_bps", "net_expectancy_bps", "profit_factor", "drawdown_bps"):
        a, b = base.get(key), candidate.get(key)
        out[key] = None if a is None or b is None else b - a
    return out


def run(*, league_path: Path, out_dir: Path, aggregate_path: Path, baseline_dir: Path, symbols: str) -> dict[str, Any]:
    base_policy_functions = ev.policy_functions
    feature_meta: dict[tuple[str, str, int], dict[str, float | None]] = {}
    rejected = Counter()
    rejected_reason = Counter()

    def wrapped_policy_functions(module: Any, strategy_id: str):
        compute, build = base_policy_functions(module, strategy_id)
        rule = CANDIDATE.get(strategy_id)
        if not rule:
            return compute, build

        def compute_wrapped(bars: Any, *, symbol: str, now_ts_ms: int, config: Any):
            feature = compute(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=config)
            atr_value = float(getattr(feature, "atr", 0.0) or 0.0)
            values = getattr(feature, "values", {}) or {}
            chase = values.get("chase_atr") if isinstance(values, Mapping) else None
            key = (strategy_id, str(getattr(feature, "symbol")), int(getattr(feature, "signal_ts")))
            feature_meta[key] = {
                "body_atr": body_atr_from_bar(bars[-1], atr_value),
                "chase_atr": float(chase) if chase is not None else None,
            }
            return feature

        def build_wrapped(feature: Any, **kwargs: Any):
            intent = build(feature, **kwargs)
            if bool(getattr(intent, "no_trade")):
                return intent
            key = (strategy_id, str(getattr(feature, "symbol")), int(getattr(feature, "signal_ts")))
            meta = feature_meta.get(key) or {}
            reasons = gate_reasons(strategy_id, body_atr=meta.get("body_atr"), chase_atr=meta.get("chase_atr"))
            if not reasons:
                return intent
            rejected[strategy_id] += 1
            for reason in reasons:
                rejected_reason[(strategy_id, reason)] += 1
            return replace(
                intent,
                no_trade=True,
                regime=f"{getattr(intent, 'regime')}_RESEARCH_ENTRY_QUALITY_REJECT",
                reason_codes=tuple(getattr(intent, "reason_codes", ())) + ("RESEARCH_ENTRY_QUALITY_GATE_REJECT",) + reasons,
            )

        return compute_wrapped, build_wrapped

    ev.policy_functions = wrapped_policy_functions
    try:
        candidate_aggregate = deep.run(league_path, out_dir, aggregate_path, symbols)
    finally:
        ev.policy_functions = base_policy_functions

    comparisons: list[dict[str, Any]] = []
    for row in candidate_aggregate.get("rows") or []:
        sid = str(row["strategy_id"])
        candidate_receipt = read(out_dir / f"{sid}.json")
        baseline_path = baseline_dir / f"{sid}.json"
        baseline_metrics = compact_metrics(read(baseline_path)) if baseline_path.exists() else None
        candidate_metrics = compact_metrics(candidate_receipt)
        comparisons.append({
            "strategy_id": sid,
            "gate": CANDIDATE.get(sid),
            "quality_rejected_intents": int(rejected.get(sid, 0)),
            "quality_rejected_reasons": {
                reason: int(count)
                for (rsid, reason), count in sorted(rejected_reason.items())
                if rsid == sid
            },
            "baseline": baseline_metrics,
            "candidate": candidate_metrics,
            "delta": metric_delta(baseline_metrics, candidate_metrics) if baseline_metrics is not None else None,
        })

    result = {
        "schema_version": "zel.a1.active5_entry_quality_candidate.v1",
        "state": "PASS_RESEARCH_ENTRY_QUALITY_CANDIDATE_REPLAY" if candidate_aggregate.get("success_count") == 5 else "HOLD_RESEARCH_ENTRY_QUALITY_CANDIDATE_INCOMPLETE",
        "research_only": True,
        "candidate_rules": CANDIDATE,
        "screening_basis": "chronological_60_40_dimensionless_single_feature_screen_rounded_thresholds",
        "comparisons": comparisons,
        "shared_cache": candidate_aggregate.get("shared_cache"),
        "candidate_aggregate_path": str(aggregate_path),
        **AUTH,
    }
    report_path = aggregate_path.with_name(aggregate_path.stem + "_comparison.json")
    write(report_path, result)
    return result


def self_test() -> int:
    assert gate_reasons("trend_rider", body_atr=0.41, chase_atr=None) == ("SIGNAL_BODY_ATR_ABOVE_MAX",)
    assert gate_reasons("trend_rider", body_atr=0.39, chase_atr=None) == ()
    assert gate_reasons("break_and_continue", body_atr=1.09, chase_atr=None) == ("SIGNAL_BODY_ATR_BELOW_MIN",)
    assert gate_reasons("trend_ma_macd", body_atr=None, chase_atr=0.71) == ("CHASE_ATR_ABOVE_MAX",)
    assert gate_reasons("supertrend_pullback", body_atr=99.0, chase_atr=99.0) == ()
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_ACTIVE5_ENTRY_QUALITY_CANDIDATE_V1_SELF_TEST")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--league", type=Path, default=ROOT / "backend/research/rebuild/a1_strategy25_improvement_league_latest.json")
    p.add_argument("--out-dir", type=Path, default=ROOT / "out/active5_entry_quality_v1")
    p.add_argument("--aggregate", type=Path, default=ROOT / "out/active5_entry_quality_v1_aggregate.json")
    p.add_argument("--baseline-dir", type=Path, default=ROOT / "out/diag_active5_1h_full")
    p.add_argument("--symbols", default="BTC-USDT,ETH-USDT,SOL-USDT,XRP-USDT,LINK-USDT,DOGE-USDT")
    args = p.parse_args()
    if args.self_test:
        return self_test()
    result = run(
        league_path=args.league,
        out_dir=args.out_dir,
        aggregate_path=args.aggregate,
        baseline_dir=args.baseline_dir,
        symbols=args.symbols,
    )
    print("ACTIVE5_ENTRY_QUALITY=" + json.dumps({
        "state": result["state"],
        "comparisons": result["comparisons"],
        "shared_cache": result["shared_cache"],
    }, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
