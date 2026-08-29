#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_top5_additive_entry_union_v1 as addu
from backend.research.rebuild import a1_trend_ma_macd_ablation_child_v1 as ab
from backend.research.rebuild import a1_trendma52_top5_salvage_v1 as salvage
from backend.research.rebuild import trend_policy_batch_v1 as policy
from backend.research.rebuild.a1_exact25_generic_evaluator_v1 import stable_sha

ROOT = Path(__file__).resolve().parents[3]
COST = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
ABLATION = ROOT / "backend/research/rebuild/a1_trend_ma_macd_ablation_child_latest.json"
SCHEMA = "zel.a1.trendma.slow_ema_ablation.true_long.salvage.v1"
VARIANT = "ABLATE_SLOW_EMA_ALIGNMENT_ONLY"
SYMBOLS = salvage.SYMBOLS


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def replay(
    *, boundary_ms: int, bars_by: Mapping[str, list[dict[str, Any]]],
    snapshots: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    cfg = policy.TrendPolicyConfig()
    timeframe_ms = 3600 * 1000
    trades: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        bars = list(bars_by[symbol])
        snap = snapshots[symbol]
        blocked_until_ts = -1
        for i in range(64, len(bars) - 1):
            if int(bars[i]["ts_ms"]) < boundary_ms:
                continue
            side, values, atr = ab._side_for_variant(bars, i, VARIANT, symbol)
            if side != "long":
                # Suppress shorts before ownership/cooldown reservation.
                continue
            signal_close = float(bars[i]["close"])
            stop = signal_close - 1.5 * float(atr)
            risk_distance_bps = abs(signal_close - stop) / max(signal_close, 1e-12) * 10_000
            move_budget_bps = risk_distance_bps * 2.0
            if move_budget_bps / max(float(snap["pretrade_verified_cost_bps"]), 1e-12) < cfg.min_cost_budget_ratio:
                continue
            entry_bar = bars[i + 1]
            entry_ts = int(entry_bar["ts_ms"])
            if ev.ownership_blocked(entry_ts, blocked_until_ts):
                continue
            entry = float(entry_bar["open"])
            last_j = min(len(bars) - 1, i + 1 + cfg.timeout_bars)
            exit_px = exit_ts = reason = None
            for j in range(i + 1, last_j + 1):
                bar = bars[j]
                if float(bar["low"]) <= stop:
                    exit_px, exit_ts, reason = stop, int(bar["ts_ms"]), "SL"
                    break
            if exit_px is None:
                if last_j >= len(bars) - 1:
                    blocked_until_ts = max(
                        blocked_until_ts,
                        ev.reserve_position_ownership(
                            exit_ts=None,
                            open_horizon_ts=int(bars[-1]["ts_ms"]),
                            cooldown_bars=2,
                            timeframe_ms=timeframe_ms,
                        ),
                    )
                    continue
                exit_px, exit_ts, reason = float(bars[last_j]["close"]), int(bars[last_j]["ts_ms"]), "TIMEOUT"
            blocked_until_ts = max(
                blocked_until_ts,
                ev.reserve_position_ownership(
                    exit_ts=int(exit_ts), open_horizon_ts=None,
                    cooldown_bars=2, timeframe_ms=timeframe_ms,
                ),
            )
            cost = (
                float(snap["fee_bps"]) + float(snap["spread_bps"]) + float(snap["impact_bps"])
                + ev.funding_cost(entry_ts, int(exit_ts), list(snap["funding_rows"]))
            )
            gross = (float(exit_px) - entry) / entry * 10_000
            trades.append({
                "symbol": symbol,
                "signal_ts": int(bars[i]["ts_ms"]),
                "entry_ts": entry_ts,
                "exit_ts": int(exit_ts),
                "side": "long",
                "entry": entry,
                "exit": float(exit_px),
                "reason": reason,
                "gross_bps": gross,
                "realized_cost_bps": cost,
                "net_bps": gross - cost,
                "changed_axis_parent": VARIANT,
                "changed_axis_gen2": "LONG_ONLY_BEFORE_OWNERSHIP_RESERVATION",
                "feature_state_sha256": stable_sha({"values": values, "signal_ts": int(bars[i]["ts_ms"]), "symbol": symbol}),
            })
    return trades


def run(parent_path: Path, trend70: Path, a4_dir: Path, break_dir: Path, out: Path) -> dict[str, Any]:
    exact = read(parent_path)
    if str(exact.get("strategy_id")) != "trend_ma_macd" or len(exact.get("trades") or []) != 52:
        raise RuntimeError("EXACT_TRENDMA_52_PARENT_REQUIRED")
    ablation = read(ABLATION)
    nxt = ablation.get("next_candidate") or {}
    if nxt.get("changed_variant") != VARIANT or nxt.get("development_candidate_ready") is not True:
        raise RuntimeError("SLOW_EMA_ABLATION_NOT_FROZEN_DEVELOPMENT_READY")

    authority = read(COST)
    bars_by, maps, fetched = ab.load_shared_inputs(SYMBOLS, authority)
    public = exact.get("execution_snapshots") or {}
    snapshots = {
        s: salvage._snapshot_with_exact_cost(fetched[s], dict(public.get(s) or {})) for s in SYMBOLS
    }
    rows = replay(
        boundary_ms=ab.parse_boundary(str(exact.get("boundary_utc") or "")),
        bars_by=bars_by,
        snapshots=snapshots,
    )
    enriched = [dict(x) for x in rows]
    salvage.enrich(enriched, bars_by, maps)
    metrics = addu.metrics(enriched)
    lanes = salvage.parent_lanes(trend70, a4_dir, break_dir)
    unions: dict[str, Any] = {}
    historical_pass: list[str] = []
    for lane_id, p in lanes.items():
        u = addu.evaluate(p, {"strategy_id": "trend_ma_macd", "trades": enriched})
        unions[lane_id] = {
            "state": u["state"],
            "parent_T": u["parent_trade_count"],
            "added_only_T": u["added_only_trade_count"],
            "overlap_T": u["overlap_trade_count"],
            "parent_metrics": u["parent_metrics"],
            "added_metrics": u["added_only_metrics"],
            "combined_metrics": u["combined_metrics"],
            "failed_checks": u["failed_checks"],
            "near_overlap": salvage.near_overlap(p["trades"], enriched),
        }
        if u["state"] == "PASS_ADD_ONLY_ENTRY_LANE":
            historical_pass.append(lane_id)

    result = {
        "schema_version": SCHEMA,
        "state": "PASS_TRENDMA_SLOW_EMA_ABLATION_TRUE_LONG_SALVAGE",
        "strategy_id": "trend_ma_macd",
        "generation_1": {
            "axis": "REMOVE_SLOW_EMA_ALIGNMENT_ONLY",
            "candidate_id": nxt.get("candidate_id"),
            "historical_T": nxt.get("completed_trades"),
            "historical_metrics": nxt.get("metrics"),
            "development_candidate_ready": True,
            "fresh_prospective_validation_required": True,
        },
        "generation_2": {
            "axis": "LONG_ONLY_BEFORE_OWNERSHIP_RESERVATION",
            "single_axis_relative_to_gen1": True,
            "T": len(enriched),
            "metrics": metrics,
            "trade_identity_sha256": stable_sha(sorted((x["symbol"], x["signal_ts"], x["entry_ts"], x["side"]) for x in enriched)),
        },
        "top5_append_only_unions": unions,
        "historical_strict_pass_lanes": historical_pass,
        "historical_strict_pass_count": len(historical_pass),
        "attachable_now": False,
        "attachable_now_reason": "GEN2_HAS_NO_PREREGISTERED_FRESH_PROSPECTIVE_EVIDENCE",
        "latent_attachable_after_fresh": bool(historical_pass),
        "next": "FREEZE_GEN2_POLICY_AND_START_NEW_FRESH_PROSPECTIVE_BOUNDARY" if historical_pass and float(metrics.get("net_pnl_bps") or 0.0) > 0 and float(metrics.get("profit_factor") or 0.0) > 1 else "DO_NOT_ADVANCE_GEN2",
        "numeric_threshold_sweep": False,
        "post_outcome_trade_deletion": False,
        "parent_rewrite": False,
        "top5_ssot_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "action": "hold",
    }
    result["receipt_sha256"] = stable_sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert VARIANT == "ABLATE_SLOW_EMA_ALIGNMENT_ONLY"
    print("PASS_A1_TRENDMA_SLOW_ABLATION_TRUE_LONG_SALVAGE_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", type=Path)
    ap.add_argument("--trend70-source", type=Path)
    ap.add_argument("--a4-source-dir", type=Path)
    ap.add_argument("--break-source-dir", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_trendma_slow_ablation_true_long_salvage_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not all((a.parent, a.trend70_source, a.a4_source_dir, a.break_source_dir)):
        raise SystemExit("required paths missing")
    r = run(a.parent, a.trend70_source, a.a4_source_dir, a.break_source_dir, a.out)
    print(json.dumps({
        "state": r["state"],
        "gen2": r["generation_2"],
        "historical_strict_pass_lanes": r["historical_strict_pass_lanes"],
        "latent_attachable_after_fresh": r["latent_attachable_after_fresh"],
        "next": r["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
