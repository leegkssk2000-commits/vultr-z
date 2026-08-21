from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as ev2
from backend.research.rebuild import trend_policy_batch_v1 as trend

ROOT = Path(__file__).resolve().parents[3]
PREREG = ROOT / "backend/research/architecture_factory/a1_trend_rider_transition_repair_prereg_v1.json"
REGISTRY = ROOT / "backend/research/rebuild/a1_exact25_v3_causal_registry_v1.json"
COST = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
PARENT_POLICY = ROOT / "backend/research/rebuild/trend_policy_batch_v1.py"
CANDIDATE_ID = "trend_rider_confirm_transition_v1"
PARENT_ID = "trend_rider"
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _eligible(feature: trend.FeatureSnapshot) -> tuple[bool, bool]:
    v = feature.values
    long_ok = bool(v["long_confirm"] and float(v["st_gap_atr"]) >= 0.10 and float(v["chase_atr"]) <= 2.0)
    short_ok = bool(v["short_confirm"] and float(v["st_gap_atr"]) >= 0.10 and float(v["chase_atr"]) <= 2.0)
    return long_ok, short_ok


def _validate_contract() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], trend.TrendPolicyConfig, str, str, str]:
    prereg, registry, authority = read(PREREG), read(REGISTRY), read(COST)
    if prereg.get("state") != "FROZEN_BEFORE_PROSPECTIVE_OUTCOMES" or prereg.get("candidate_id") != CANDIDATE_ID:
        raise RuntimeError("REPAIR_PREREG_INVALID")
    if prereg.get("parent_strategy_id") != PARENT_ID or prereg.get("changed_axis") != "ENTRY_ELIGIBILITY_STATE_TO_FALSE_TRUE_TRANSITION":
        raise RuntimeError("REPAIR_AXIS_INVALID")
    parent = (registry.get("strategies") or {}).get(PARENT_ID) or {}
    if parent.get("state") != "CAUSAL_CONTROL_FAIL" or ((parent.get("hard_control_states") or {}).get("same_count_random_entry") != "FAIL"):
        raise RuntimeError("PARENT_CAUSAL_FAIL_NOT_SEALED")
    if parent.get("terminal_for_policy_config_boundary_identity") is not True or registry.get("same_identity_retest_forbidden") is not True:
        raise RuntimeError("PARENT_RETEST_GUARD_NOT_SEALED")
    if authority.get("state") != "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY":
        raise RuntimeError("COST_AUTHORITY_INVALID")
    cfg = trend.TrendPolicyConfig()
    frozen = prereg.get("frozen_parent_policy", {}).get("config_contract") or {}
    checks = {
        "timeframe_ms": cfg.timeframe_ms,
        "atr_len": cfg.atr_len,
        "ema_trend_len": cfg.ema_trend_len,
        "supertrend_len": cfg.supertrend_len,
        "supertrend_mult": cfg.supertrend_mult,
        "risk_fraction_of_equity": cfg.risk_fraction_of_equity,
        "max_notional_fraction_of_equity": cfg.max_notional_fraction_of_equity,
        "min_cost_budget_ratio": cfg.min_cost_budget_ratio,
        "timeout_bars": cfg.timeout_bars,
    }
    if any(float(checks[k]) != float(frozen[k]) for k in checks):
        raise RuntimeError("PARENT_CONFIG_DRIFT")
    parent_policy_sha = ev.git_blob_sha(PARENT_POLICY)
    prereg_sha = ev.git_blob_sha(PREREG)
    repair_policy_sha = ev.stable_sha({"candidate_id": CANDIDATE_ID, "parent_policy_sha": parent_policy_sha, "prereg_blob_sha": prereg_sha})
    repair_config_sha = ev.stable_sha({"candidate_id": CANDIDATE_ID, "parent_config_sha": cfg.sha, "changed_axis": prereg["changed_axis"]})
    return prereg, registry, authority, cfg, parent_policy_sha, repair_policy_sha, repair_config_sha


def evaluate() -> dict[str, Any]:
    prereg, registry, authority, cfg, parent_policy_sha, repair_policy_sha, repair_config_sha = _validate_contract()
    boundary = str(prereg["prospective_boundary_utc"])
    boundary_ms = int(datetime.fromisoformat(boundary.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)
    interval = ev.interval_for_ms(cfg.timeframe_ms)
    trades: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    snapshots: dict[str, Any] = {}
    defects: list[str] = []
    seen: set[str] = set()
    transition_signal_count = 0

    for symbol in ("BTC-USDT", "ETH-USDT"):
        snap = ev.fetch_execution_snapshot(symbol, authority)
        snapshots[symbol] = snap
        bars = ev.fetch_bars(symbol, interval, 1000)
        post = [x for x in bars if int(x["ts_ms"]) >= boundary_ms]
        sources.append({
            "symbol": symbol,
            "bars_total": len(bars),
            "bars_post_boundary": len(post),
            "first_post_boundary_ts": int(post[0]["ts_ms"]) if post else None,
            "last_post_boundary_ts": int(post[-1]["ts_ms"]) if post else None,
        })
        warmup = 64
        for i in range(max(warmup, 1), len(bars) - 1):
            signal_ts = int(bars[i]["ts_ms"])
            if signal_ts < boundary_ms:
                continue
            try:
                cur = trend.compute_trend_rider_feature(bars[: i + 1], symbol=symbol, now_ts_ms=signal_ts, config=cfg)
                prev_ts = int(bars[i - 1]["ts_ms"])
                prev = trend.compute_trend_rider_feature(bars[:i], symbol=symbol, now_ts_ms=prev_ts, config=cfg)
                long_now, short_now = _eligible(cur)
                long_prev, short_prev = _eligible(prev)
                long_fire = long_now and not long_prev
                short_fire = short_now and not short_prev
                if long_fire == short_fire:
                    continue
                intent = trend.build_trend_rider_intent(
                    cur,
                    policy_source_sha=parent_policy_sha,
                    verified_round_trip_cost_bps=float(snap["pretrade_verified_cost_bps"]),
                    config=cfg,
                )
            except ValueError as exc:
                if str(exc).startswith(("WARMUP_", "WINDOW_", "ATR_")):
                    continue
                defects.append(f"{symbol}:{signal_ts}:POLICY:{exc}")
                continue
            if bool(getattr(intent, "no_trade")):
                defects.append(f"{symbol}:{signal_ts}:TRANSITION_REPLAYED_NO_TRADE")
                continue
            expected_side = "long" if long_fire else "short"
            side_name = str(getattr(intent, "side"))
            if side_name != expected_side:
                defects.append(f"{symbol}:{signal_ts}:SIDE_MISMATCH:{side_name}!={expected_side}")
                continue
            transition_signal_count += 1
            parent_intent_sha = ev.intent_sha(intent)
            repair_intent_sha = ev.stable_sha({
                "candidate_id": CANDIDATE_ID,
                "parent_intent_sha": parent_intent_sha,
                "signal_ts": signal_ts,
                "side": side_name,
                "changed_axis": prereg["changed_axis"],
            })
            if repair_intent_sha in seen:
                defects.append(f"DUPLICATE_INTENT:{repair_intent_sha}")
                continue
            seen.add(repair_intent_sha)

            entry_bar = bars[i + 1]
            entry_px = float(entry_bar["open"])
            side = 1 if side_name == "long" else -1
            timeout = getattr(intent, "timeout", {}) or {}
            timeout_bars = int(timeout.get("bars", cfg.timeout_bars))
            sl, tp = getattr(intent, "sl", None), getattr(intent, "tp", None)
            if sl is None and tp is None:
                defects.append(f"{symbol}:{signal_ts}:NO_EXIT_GEOMETRY")
                continue
            last_j = min(len(bars) - 1, i + 1 + max(1, timeout_bars))
            exit_px = exit_ts = reason = None
            for j in range(i + 1, last_j + 1):
                low, high = float(bars[j]["low"]), float(bars[j]["high"])
                if sl is not None and ((side == 1 and low <= float(sl)) or (side == -1 and high >= float(sl))):
                    exit_px, exit_ts, reason = float(sl), int(bars[j]["ts_ms"]), "SL"
                    break
                if tp is not None and ((side == 1 and high >= float(tp)) or (side == -1 and low <= float(tp))):
                    exit_px, exit_ts, reason = float(tp), int(bars[j]["ts_ms"]), "TP"
                    break
            if exit_px is None:
                if last_j >= len(bars) - 1:
                    continue
                exit_px, exit_ts, reason = float(bars[last_j]["close"]), int(bars[last_j]["ts_ms"]), "TIMEOUT"
            funding = ev.funding_cost(int(entry_bar["ts_ms"]), int(exit_ts), list(snap["funding_rows"]))
            cost = float(snap["fee_bps"]) + float(snap["spread_bps"]) + float(snap["impact_bps"]) + funding
            gross = side * (float(exit_px) - entry_px) / entry_px * 10_000.0
            trades.append({
                "symbol": symbol,
                "signal_ts": signal_ts,
                "entry_ts": int(entry_bar["ts_ms"]),
                "exit_ts": int(exit_ts),
                "side": side_name,
                "entry": entry_px,
                "exit": float(exit_px),
                "reason": reason,
                "gross_bps": gross,
                "realized_cost_bps": cost,
                "net_bps": gross - cost,
                "intent_sha": repair_intent_sha,
                "parent_intent_sha": parent_intent_sha,
                "feature_sha": str(getattr(intent, "feature_sha", "")),
                "config_sha": repair_config_sha,
                "policy_sha": repair_policy_sha,
                "parent_policy_sha": parent_policy_sha,
                "cost_snapshot_sha": snap["snapshot_sha256"],
                "entry_axis": "ELIGIBILITY_FALSE_TO_TRUE_TRANSITION",
            })

    net = [float(x["net_bps"]) for x in trades]
    gross = [float(x["gross_bps"]) for x in trades]
    wins = [x for x in net if x > 0]
    losses = [-x for x in net if x < 0]
    gp, gl = sum(wins), sum(losses)
    avg_win = gp / len(wins) if wins else None
    avg_loss = gl / len(losses) if losses else None
    receipt: dict[str, Any] = {
        "schema_version": "zel.a1.trend_rider_transition_repair_economics.v1",
        "state": "WAIT_FRESH_PROSPECTIVE_DATA" if not trades and not defects else "HOLD_A1_REPAIR_INTEGRITY" if defects else "A1_REPAIR_ECONOMICS_ACTIVE",
        "strategy_id": CANDIDATE_ID,
        "parent_strategy_id": PARENT_ID,
        "mode": "REPAIR",
        "boundary_utc": boundary,
        "prereg_path": str(PREREG.relative_to(ROOT)),
        "prereg_blob_sha": ev.git_blob_sha(PREREG),
        "parent_registry_receipt_sha256": registry.get("receipt_sha256"),
        "policy_path": str(PARENT_POLICY.relative_to(ROOT)),
        "policy_sha": repair_policy_sha,
        "parent_policy_sha": parent_policy_sha,
        "config_sha": repair_config_sha,
        "parent_config_sha": cfg.sha,
        "changed_axis": prereg["changed_axis"],
        "cost_authority_sha256": ev.stable_sha(authority),
        "source": {"endpoint": "/openApi/swap/v3/quote/klines", "interval": interval, "symbols": sources},
        "execution_snapshots": {k: {kk: vv for kk, vv in v.items() if kk != "funding_rows"} for k, v in snapshots.items()},
        "transition_signal_count": transition_signal_count,
        "intent_count": len(seen),
        "completed_trades": len(trades),
        "metrics": {
            "gross_pnl_bps": sum(gross),
            "gross_expectancy_bps": sum(gross) / len(gross) if gross else None,
            "net_pnl_bps": sum(net),
            "net_expectancy_bps": sum(net) / len(net) if net else None,
            "net_profit_factor": ev.profit_factor(gp, gl),
            "net_payoff": avg_win / avg_loss if avg_win is not None and avg_loss not in (None, 0) else None,
            "win_rate": len(wins) / len(net) if net else None,
            "max_drawdown_bps": ev.max_drawdown(net),
        },
        "trades": trades,
        "integrity_defects": defects,
        "leakage_lookahead": 0,
        "duplicate_count": len([x for x in defects if x.startswith("DUPLICATE_INTENT:")]),
        "repair_invariants": {
            "only_changed_axis": prereg["changed_axis"],
            "parent_thresholds_changed": False,
            "parent_risk_geometry_changed": False,
            "parent_timeout_changed": False,
            "historical_backfill": False,
            "preboundary_outcomes_used": False,
        },
        **AUTH,
    }
    receipt["source_quality_gate"] = ev2.source_quality_gate(receipt)
    if receipt["source_quality_gate"]["state"] == "FAIL":
        receipt["state"] = "A1_DATA_BLOCKED"
    elif receipt["source_quality_gate"]["state"] == "PENDING" and not defects:
        receipt["state"] = "WAIT_FRESH_PROSPECTIVE_DATA"
    receipt["receipt_sha256"] = ev.stable_sha({k: v for k, v in receipt.items() if k != "receipt_sha256"})
    return receipt


def self_test() -> int:
    prereg, registry, authority, cfg, parent_policy_sha, repair_policy_sha, repair_config_sha = _validate_contract()
    assert prereg["prospective_boundary_utc"] == "2026-08-21T17:00:00Z"
    assert prereg["changed_axis"] == "ENTRY_ELIGIBILITY_STATE_TO_FALSE_TRUE_TRANSITION"
    assert ((registry.get("strategies") or {}).get(PARENT_ID) or {}).get("state") == "CAUSAL_CONTROL_FAIL"
    assert authority["state"] == "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY"
    assert cfg.timeout_bars == 48 and cfg.supertrend_len == 10 and cfg.supertrend_mult == 3.0 and cfg.ema_trend_len == 50
    assert parent_policy_sha and repair_policy_sha and repair_config_sha
    print("PASS_A1_TREND_RIDER_TRANSITION_REPAIR_EVALUATOR_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_trend_rider_transition_repair_evaluator_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "candidate_id": result["strategy_id"],
        "completed_trades": result["completed_trades"],
        "source_quality": (result.get("source_quality_gate") or {}).get("state"),
        "metrics": result["metrics"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
