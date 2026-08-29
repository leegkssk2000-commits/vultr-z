#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
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
SCHEMA = "zel.a1.supertrend.atr_adverse_veto.prospective_shadow.v1"
STRATEGY = "supertrend_pullback"
SYMBOLS = salvage.SYMBOLS
PROSPECTIVE_BOUNDARY_UTC = "2026-08-29T11:57:00Z"
FROZEN_AXIS = {
    "origin_commit": "051ff7015e6456410073b1a42dc0c201876c1958",
    "name": "long_above_sma50_and_shock_ge_1x_atr14_veto_only",
    "atr_n": 14,
    "sma_n": 50,
    "shock_atr_floor": 1.0,
    "threshold_sweep": False,
    "future_information_used": False,
    "transfer_mode": "SUPERTREND_NATIVE_PREENTRY_SHADOW_VETO",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def parse_boundary(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def atr14(bars: list[dict[str, Any]], i: int) -> float:
    vals: list[float] = []
    for j in range(i - 13, i + 1):
        prev_close = float(bars[j - 1]["close"])
        vals.append(
            max(
                float(bars[j]["high"]) - float(bars[j]["low"]),
                abs(float(bars[j]["high"]) - prev_close),
                abs(float(bars[j]["low"]) - prev_close),
            )
        )
    return sum(vals) / len(vals)


def _exit_for_side(*, side: str, low: float, high: float, sl: float | None, tp: float | None) -> tuple[float | None, str | None]:
    if side == "long":
        if sl is not None and low <= sl:
            return sl, "SL"
        if tp is not None and high >= tp:
            return tp, "TP"
    elif side == "short":
        if sl is not None and high >= sl:
            return sl, "SL"
        if tp is not None and low <= tp:
            return tp, "TP"
    else:
        raise RuntimeError(f"SIDE_UNSUPPORTED:{side}")
    return None, None


def replay(
    *,
    boundary_ms: int,
    bars_by: Mapping[str, list[dict[str, Any]]],
    snapshots: Mapping[str, Mapping[str, Any]],
    policy_sha: str,
    veto_enabled: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cfg = policy.TrendPolicyConfig()
    timeframe_ms = 3_600_000
    trades: list[dict[str, Any]] = []
    vetoed: list[dict[str, Any]] = []

    for symbol in SYMBOLS:
        bars = list(bars_by[symbol])
        snap = snapshots[symbol]
        blocked_until_ts = -1
        for i in range(64, len(bars) - 1):
            signal_ts = int(bars[i]["ts_ms"])
            if signal_ts < boundary_ms:
                continue
            try:
                feature = policy.compute_supertrend_pullback_feature(
                    bars[: i + 1], symbol=symbol, now_ts_ms=signal_ts, config=cfg
                )
                intent = policy.build_supertrend_pullback_intent(
                    feature,
                    policy_source_sha=policy_sha,
                    verified_round_trip_cost_bps=float(snap["pretrade_verified_cost_bps"]),
                    config=cfg,
                )
            except ValueError as exc:
                if str(exc).startswith(("WARMUP_", "WINDOW_", "ATR_")):
                    continue
                raise
            if bool(getattr(intent, "no_trade")):
                continue

            side = str(getattr(intent, "side"))
            a = atr14(bars, i)
            shock = abs(float(bars[i]["close"]) - float(bars[i - 1]["close"]))
            shock_atr = shock / max(a, 1e-12)
            sma50 = sum(float(x["close"]) for x in bars[i - 49 : i + 1]) / 50.0
            above_sma50 = float(bars[i]["close"]) >= sma50
            veto_hit = side == "long" and above_sma50 and shock_atr >= 1.0
            if veto_enabled and veto_hit:
                vetoed.append(
                    {
                        "symbol": symbol,
                        "signal_ts": signal_ts,
                        "side": side,
                        "shock_atr": shock_atr,
                        "above_sma50": True,
                    }
                )
                continue

            entry_bar = bars[i + 1]
            entry_ts = int(entry_bar["ts_ms"])
            owns_position, cooldown_bars = ev.execution_ownership_policy(intent)
            if owns_position and ev.ownership_blocked(entry_ts, blocked_until_ts):
                continue

            entry = float(entry_bar["open"])
            sl_raw = getattr(intent, "sl", None)
            tp_raw = getattr(intent, "tp", None)
            sl = None if sl_raw is None else float(sl_raw)
            tp = None if tp_raw is None else float(tp_raw)
            timeout = getattr(intent, "timeout", {}) or {}
            timeout_bars = int(timeout.get("bars", getattr(cfg, "timeout_bars", 1)))
            if sl is None and tp is None:
                raise RuntimeError("EXIT_GEOMETRY_UNSUPPORTED_NO_SL_TP")

            exit_px: float | None = None
            exit_ts: int | None = None
            reason: str | None = None
            last_j = min(len(bars) - 1, i + 1 + max(1, timeout_bars))
            for j in range(i + 1, last_j + 1):
                bar = bars[j]
                px, why = _exit_for_side(
                    side=side,
                    low=float(bar["low"]),
                    high=float(bar["high"]),
                    sl=sl,
                    tp=tp,
                )
                if px is not None:
                    exit_px, exit_ts, reason = px, int(bar["ts_ms"]), why
                    break

            if exit_px is None:
                if last_j >= len(bars) - 1:
                    if owns_position:
                        blocked_until_ts = max(
                            blocked_until_ts,
                            ev.reserve_position_ownership(
                                exit_ts=None,
                                open_horizon_ts=int(bars[-1]["ts_ms"]),
                                cooldown_bars=cooldown_bars,
                                timeframe_ms=timeframe_ms,
                            ),
                        )
                    continue
                exit_px = float(bars[last_j]["close"])
                exit_ts = int(bars[last_j]["ts_ms"])
                reason = "TIMEOUT"

            if owns_position:
                blocked_until_ts = max(
                    blocked_until_ts,
                    ev.reserve_position_ownership(
                        exit_ts=int(exit_ts),
                        open_horizon_ts=None,
                        cooldown_bars=cooldown_bars,
                        timeframe_ms=timeframe_ms,
                    ),
                )

            cost = (
                float(snap["fee_bps"])
                + float(snap["spread_bps"])
                + float(snap["impact_bps"])
                + ev.funding_cost(entry_ts, int(exit_ts), list(snap["funding_rows"]))
            )
            if side == "long":
                gross = (float(exit_px) - entry) / entry * 10000.0
            else:
                gross = (entry - float(exit_px)) / entry * 10000.0
            trades.append(
                {
                    "symbol": symbol,
                    "signal_ts": int(getattr(intent, "signal_ts")),
                    "entry_ts": entry_ts,
                    "exit_ts": int(exit_ts),
                    "side": side,
                    "entry": entry,
                    "exit": float(exit_px),
                    "reason": reason,
                    "gross_bps": gross,
                    "realized_cost_bps": cost,
                    "net_bps": gross - cost,
                    "shock_atr": shock_atr,
                    "above_sma50": above_sma50,
                    "veto_hit": veto_hit,
                }
            )
    return trades, vetoed


def _pf_ge(candidate: Mapping[str, Any], base: Mapping[str, Any]) -> bool:
    if bool(candidate.get("profit_factor_unbounded")):
        return True
    if bool(base.get("profit_factor_unbounded")):
        return bool(candidate.get("profit_factor_unbounded"))
    b = base.get("profit_factor")
    c = candidate.get("profit_factor")
    if b is None:
        return True
    return c is not None and float(c) >= float(b)


def compare(base_trades: list[dict[str, Any]], candidate_trades: list[dict[str, Any]]) -> dict[str, Any]:
    b = addu.metrics(base_trades)
    c = addu.metrics(candidate_trades)
    checks = {
        "candidate_has_trades": int(c["trades"]) > 0,
        "net_pnl_non_decrease": float(c["net_pnl_bps"] or 0.0) >= float(b["net_pnl_bps"] or 0.0),
        "expectancy_non_decrease": (
            b["net_expectancy_bps"] is None
            or (c["net_expectancy_bps"] is not None and float(c["net_expectancy_bps"]) >= float(b["net_expectancy_bps"]))
        ),
        "win_rate_non_decrease": (
            b["win_rate"] is None or (c["win_rate"] is not None and float(c["win_rate"]) >= float(b["win_rate"]))
        ),
        "profit_factor_non_decrease": _pf_ge(c, b),
        "drawdown_non_increase": float(c["drawdown_bps"] or 0.0) <= float(b["drawdown_bps"] or 0.0),
    }
    return {
        "base": b,
        "candidate": c,
        "checks": checks,
        "all_quality_checks_pass": all(checks.values()),
    }


def trade_key(row: Mapping[str, Any]) -> tuple[str, int, int, str]:
    return str(row["symbol"]), int(row["signal_ts"]), int(row["entry_ts"]), str(row["side"])


def run(parent_path: Path, out: Path) -> dict[str, Any]:
    parent = read(parent_path)
    if str(parent.get("strategy_id")) != STRATEGY:
        raise RuntimeError("SUPERTREND_PARENT_REQUIRED")
    if parent.get("integrity_defects"):
        raise RuntimeError("SUPERTREND_PARENT_INTEGRITY_DEFECT")
    if int(parent.get("leakage_lookahead") or 0) != 0:
        raise RuntimeError("SUPERTREND_PARENT_LOOKAHEAD_NONZERO")

    authority = read(COST)
    bars_by, _maps, fetched = ab.load_shared_inputs(SYMBOLS, authority)
    public = parent.get("execution_snapshots") or {}
    snapshots = {
        symbol: salvage._snapshot_with_exact_cost(fetched[symbol], dict(public.get(symbol) or {}))
        for symbol in SYMBOLS
    }
    policy_sha = str(parent.get("policy_sha") or "")
    if not policy_sha:
        raise RuntimeError("SUPERTREND_POLICY_SHA_REQUIRED")

    historical_boundary_utc = str(parent.get("boundary_utc") or "")
    if not historical_boundary_utc:
        raise RuntimeError("SUPERTREND_HISTORICAL_BOUNDARY_REQUIRED")

    historical_base, _ = replay(
        boundary_ms=parse_boundary(historical_boundary_utc),
        bars_by=bars_by,
        snapshots=snapshots,
        policy_sha=policy_sha,
        veto_enabled=False,
    )
    historical_candidate, historical_vetoed = replay(
        boundary_ms=parse_boundary(historical_boundary_utc),
        bars_by=bars_by,
        snapshots=snapshots,
        policy_sha=policy_sha,
        veto_enabled=True,
    )
    historical = compare(historical_base, historical_candidate)

    fresh_base, _ = replay(
        boundary_ms=parse_boundary(PROSPECTIVE_BOUNDARY_UTC),
        bars_by=bars_by,
        snapshots=snapshots,
        policy_sha=policy_sha,
        veto_enabled=False,
    )
    fresh_candidate, fresh_vetoed = replay(
        boundary_ms=parse_boundary(PROSPECTIVE_BOUNDARY_UTC),
        bars_by=bars_by,
        snapshots=snapshots,
        policy_sha=policy_sha,
        veto_enabled=True,
    )
    prospective = compare(fresh_base, fresh_candidate)

    base_keys = {trade_key(x) for x in fresh_base}
    candidate_keys = {trade_key(x) for x in fresh_candidate}
    fresh_base_t = len(fresh_base)
    fresh_candidate_t = len(fresh_candidate)
    if fresh_base_t == 0:
        state = "CONNECTED_SHADOW_WAIT_NEW_T"
    elif prospective["all_quality_checks_pass"]:
        state = "CONNECTED_SHADOW_FRESH_IMPROVING"
    else:
        state = "CONNECTED_SHADOW_FRESH_MIXED_OR_WORSE"

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": STRATEGY,
        "shadow_connected": True,
        "connection_target": "SUPERTREND_NATIVE_PREENTRY_FILTER_SHADOW",
        "frozen_axis": FROZEN_AXIS,
        "historical_diagnostic_only": {
            "authority": False,
            "boundary_utc": historical_boundary_utc,
            "comparison": historical,
            "veto_signal_T": len(historical_vetoed),
        },
        "prospective": {
            "boundary_utc": PROSPECTIVE_BOUNDARY_UTC,
            "base_T": fresh_base_t,
            "candidate_T": fresh_candidate_t,
            "veto_signal_T": len(fresh_vetoed),
            "trade_ids_removed_T": len(base_keys - candidate_keys),
            "trade_ids_added_after_ownership_release_T": len(candidate_keys - base_keys),
            "comparison": prospective,
        },
        "policy": {
            "historical_donor_trade_attachment": False,
            "parent_trade_rewrite": False,
            "top5_ssot_mutated": False,
            "threshold_sweep": False,
            "outcome_selected": False,
            "future_information_used": False,
            "fresh_only_for_decision": True,
            "production_execution_unchanged": True,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "action": "hold",
        "next": "COLLECT_PROSPECTIVE_SUPERTREND_T_AND_REEVALUATE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    result["receipt_sha256"] = stable_sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert FROZEN_AXIS["shock_atr_floor"] == 1.0
    assert FROZEN_AXIS["threshold_sweep"] is False
    assert parse_boundary(PROSPECTIVE_BOUNDARY_UTC) > 0
    assert _exit_for_side(side="long", low=90.0, high=110.0, sl=95.0, tp=120.0) == (95.0, "SL")
    assert _exit_for_side(side="short", low=90.0, high=110.0, sl=105.0, tp=80.0) == (105.0, "SL")
    print("PASS_A1_SUPERTREND_ATR_ADVERSE_VETO_PROSPECTIVE_SHADOW_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", type=Path)
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("out/a1_supertrend_atr_adverse_veto_prospective_shadow_latest.json"),
    )
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.parent is None:
        raise RuntimeError("--parent required")
    result = run(args.parent, args.out)
    print(
        json.dumps(
            {
                "state": result["state"],
                "historical": result["historical_diagnostic_only"]["comparison"],
                "prospective": result["prospective"],
                "next": result["next"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
