from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.research.rebuild.a1_exact25_generic_evaluator_v1 import (
    fetch_bars,
    fetch_execution_snapshot,
    funding_cost,
    git_blob_sha,
    load_json,
    max_drawdown,
    stable_sha,
)
from backend.research.rebuild.microstructure_policy_batch_v1 import (
    MicroPolicyConfig,
    build_scalp_snap_intent,
    compute_scalp_snap_feature,
)
from backend.production.zel_production_a1_jump_liquidity_economic_v1 import _source_complete

ROOT = Path(__file__).resolve().parents[3]
PREREG = ROOT / "backend/research/rebuild/a1_experimental_scalp_snap_order_flow_exhaustion_v1.json"
POLICY = ROOT / "backend/research/rebuild/a1_experimental_scalp_snap_order_flow_exhaustion_policy_v1.json"
CONFIG = ROOT / "backend/research/rebuild/a1_experimental_scalp_snap_order_flow_exhaustion_config_v1.json"
BASELINE_POLICY = ROOT / "backend/research/rebuild/microstructure_policy_batch_v1.py"
COST_PATH = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.is_file():
        raise RuntimeError(f"MICRO_HISTORY_MISSING:{path}")
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"MICRO_HISTORY_JSON_INVALID:{n}") from exc
        if isinstance(row, dict):
            out.append(row)
    return out


def _sign(v: float) -> int:
    return 1 if v > 0 else (-1 if v < 0 else 0)


def confirmation_for_entry(rows: list[dict[str, Any]], *, symbol: str, entry_ts_ms: int, side: str,
                           bucket_ms: int = 5000, max_stale_buckets: int = 2) -> dict[str, Any]:
    eligible = [
        r for r in rows
        if str(r.get("symbol") or "") == symbol
        and int(r.get("bucket_end_ms") or 0) <= int(entry_ts_ms)
        and _source_complete(r)
    ]
    eligible.sort(key=lambda r: int(r.get("bucket_end_ms") or 0))
    if len(eligible) < 2:
        return {"pass": False, "reason": "MISSING_COMPLETE_MICRO_BUCKETS"}
    prev, cur = eligible[-2], eligible[-1]
    prev_start, cur_start = int(prev.get("bucket_start_ms") or 0), int(cur.get("bucket_start_ms") or 0)
    cur_end = int(cur.get("bucket_end_ms") or 0)
    if cur_start - prev_start != bucket_ms:
        return {"pass": False, "reason": "NON_CONSECUTIVE_MICRO_BUCKETS"}
    if entry_ts_ms - cur_end < 0 or entry_ts_ms - cur_end > max_stale_buckets * bucket_ms:
        return {"pass": False, "reason": "STALE_MICRO_CONFIRMATION"}
    try:
        prev_flow = float(prev["trade_imbalance"])
        cur_flow = float(cur["trade_imbalance"])
        cur_book = float(cur["imbalance_top20_mean"])
    except (KeyError, TypeError, ValueError):
        return {"pass": False, "reason": "MICRO_FIELDS_INVALID"}
    reversal = 1 if side == "long" else (-1 if side == "short" else 0)
    if reversal == 0:
        return {"pass": False, "reason": "SIDE_INVALID"}
    drive = -reversal
    passed = _sign(prev_flow) == drive and _sign(cur_flow) == reversal and _sign(cur_book) == reversal
    return {
        "pass": bool(passed),
        "reason": "ORDER_FLOW_EXHAUSTION_CONFIRMED" if passed else "ORDER_FLOW_EXHAUSTION_NOT_CONFIRMED",
        "prev_bucket_start_ms": prev_start,
        "cur_bucket_start_ms": cur_start,
        "cur_bucket_end_ms": cur_end,
        "prev_trade_imbalance": prev_flow,
        "cur_trade_imbalance": cur_flow,
        "cur_book_imbalance": cur_book,
        "source_entry_cutoff_ms": int(entry_ts_ms),
    }


def evaluate(*, boundary_utc: str, history_path: Path, symbols: list[str]) -> dict[str, Any]:
    prereg, policy, exp_cfg, authority = load_json(PREREG), load_json(POLICY), load_json(CONFIG), load_json(COST_PATH)
    if prereg.get("experimental_not_baseline") is not True or prereg.get("baseline_mutated") is not False:
        raise RuntimeError("EXPERIMENT_PREREG_AUTHORITY_INVALID")
    if policy.get("selected_axis") != "ORDER_FLOW_EXHAUSTION_CONFIRMATION":
        raise RuntimeError("EXPERIMENT_AXIS_DRIFT")
    if float(exp_cfg.get("verified_pretrade_cost_bps_reference") or 0) != 14.0:
        raise RuntimeError("EXPERIMENT_COST_REFERENCE_DRIFT")
    if authority.get("state") != "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY":
        raise RuntimeError("COST_AUTHORITY_INVALID")
    boundary_ms = int(datetime.fromisoformat(boundary_utc.replace("Z", "+00:00")).timestamp() * 1000)
    micro = _load_jsonl(history_path)
    cfg = MicroPolicyConfig()
    baseline_policy_sha = git_blob_sha(BASELINE_POLICY)
    trades: list[dict[str, Any]] = []
    baseline_intents = confirmed_intents = 0
    defects: list[str] = []
    source_rows: list[dict[str, Any]] = []
    snapshots: dict[str, Any] = {}
    seen: set[str] = set()

    for symbol in symbols:
        snap = fetch_execution_snapshot(symbol, authority)
        snapshots[symbol] = snap
        bars = fetch_bars(symbol, "5m")
        post = [b for b in bars if int(b["ts_ms"]) >= boundary_ms]
        source_rows.append({"symbol": symbol, "bars_post_boundary": len(post), "micro_rows": sum(1 for r in micro if str(r.get("symbol") or "") == symbol)})
        warmup = max(64, cfg.volume_lookback + cfg.atr_len + 3)
        for i in range(warmup, len(bars) - 1):
            if int(bars[i]["ts_ms"]) < boundary_ms:
                continue
            feature = compute_scalp_snap_feature(bars[: i + 1], symbol=symbol, now_ts_ms=int(bars[i]["ts_ms"]), config=cfg)
            intent = build_scalp_snap_intent(feature, policy_source_sha=baseline_policy_sha,
                                             verified_round_trip_cost_bps=float(snap["pretrade_verified_cost_bps"]), config=cfg)
            if bool(getattr(intent, "no_trade")):
                continue
            baseline_intents += 1
            side_name = str(getattr(intent, "side"))
            entry_bar = bars[i + 1]
            entry_ts = int(entry_bar["ts_ms"])
            confirm = confirmation_for_entry(micro, symbol=symbol, entry_ts_ms=entry_ts, side=side_name)
            if not confirm["pass"]:
                continue
            confirmed_intents += 1
            key = stable_sha({"symbol": symbol, "signal_ts": int(getattr(intent, "signal_ts")), "side": side_name, "axis": "ORDER_FLOW_EXHAUSTION_CONFIRMATION"})
            if key in seen:
                defects.append(f"DUPLICATE_EXPERIMENTAL_INTENT:{key}")
                continue
            seen.add(key)
            side = 1 if side_name == "long" else -1
            entry_px = float(entry_bar["open"])
            timeout_bars = int((getattr(intent, "timeout", {}) or {}).get("bars", cfg.timeout_bars))
            sl, tp = getattr(intent, "sl", None), getattr(intent, "tp", None)
            last_j = min(len(bars) - 1, i + 1 + max(1, timeout_bars))
            exit_px = exit_ts = reason = None
            for j in range(i + 1, last_j + 1):
                bar = bars[j]; low, high = float(bar["low"]), float(bar["high"])
                if sl is not None and ((side == 1 and low <= float(sl)) or (side == -1 and high >= float(sl))):
                    exit_px, exit_ts, reason = float(sl), int(bar["ts_ms"]), "SL"; break
                if tp is not None and ((side == 1 and high >= float(tp)) or (side == -1 and low <= float(tp))):
                    exit_px, exit_ts, reason = float(tp), int(bar["ts_ms"]), "TP"; break
            if exit_px is None:
                if last_j >= len(bars) - 1:
                    continue
                exit_px, exit_ts, reason = float(bars[last_j]["close"]), int(bars[last_j]["ts_ms"]), "TIMEOUT"
            fee, spread, impact = float(snap["fee_bps"]), float(snap["spread_bps"]), float(snap["impact_bps"])
            fund = funding_cost(entry_ts, int(exit_ts), list(snap["funding_rows"]))
            cost = fee + spread + impact + fund
            gross = side * (float(exit_px) - entry_px) / entry_px * 10_000
            trades.append({"symbol": symbol, "signal_ts": int(getattr(intent, "signal_ts")), "entry_ts": entry_ts, "exit_ts": int(exit_ts), "side": side_name, "gross_bps": gross, "realized_cost_bps": cost, "net_bps": gross-cost, "baseline_policy_sha": baseline_policy_sha, "experimental_policy_sha": git_blob_sha(POLICY), "experimental_config_sha": git_blob_sha(CONFIG), "confirmation": confirm, "experimental_intent_sha": key})

    net = [float(t["net_bps"]) for t in trades]; gross = [float(t["gross_bps"]) for t in trades]
    wins = [x for x in net if x > 0]; losses = [-x for x in net if x < 0]
    gp, gl = sum(wins), sum(losses)
    avg_win = gp/len(wins) if wins else None; avg_loss = gl/len(losses) if losses else None
    receipt = {
        "schema_version": "zel.a1_experimental_scalp_snap_order_flow_exhaustion_economics.v1",
        "state": "HOLD_EXPERIMENTAL_INTEGRITY" if defects else ("WAIT_FRESH_PROSPECTIVE_DATA" if not trades else "EXPERIMENTAL_ECONOMICS_ACTIVE"),
        "experiment_id": "scalp_snap_v2_order_flow_exhaustion_confirmation",
        "baseline_strategy_id": "scalp_snap", "experimental_not_baseline": True, "baseline_mutated": False,
        "boundary_utc": boundary_utc, "source_history_path": str(history_path), "source_rows": source_rows,
        "policy_sha": git_blob_sha(POLICY), "config_sha": git_blob_sha(CONFIG), "baseline_policy_sha": baseline_policy_sha,
        "evaluator_sha": git_blob_sha(Path(__file__)), "cost_authority_sha256": stable_sha(authority),
        "baseline_intent_count": baseline_intents, "confirmed_intent_count": confirmed_intents, "completed_trades": len(trades),
        "metrics": {"gross_pnl_bps": sum(gross), "gross_expectancy_bps": sum(gross)/len(gross) if gross else None,
                    "net_pnl_bps": sum(net), "net_expectancy_bps": sum(net)/len(net) if net else None,
                    "net_profit_factor": gp/gl if gl > 0 else (math.inf if gp > 0 else None),
                    "net_payoff": avg_win/avg_loss if avg_win is not None and avg_loss not in (None,0) else None,
                    "win_rate": len(wins)/len(net) if net else None, "max_drawdown_bps": max_drawdown(net)},
        "trades": trades, "integrity_defects": defects, "leakage_lookahead": 0,
        "duplicate_count": len([x for x in defects if x.startswith("DUPLICATE_EXPERIMENTAL_INTENT:")]),
        "selection_authority": False, "promotion_authority": False, "execution_authority": "NONE",
        "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED", "exchange_order_submitted": False, "protected_mutations": 0,
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--boundary", required=True)
    p.add_argument("--history", default="/home/z/z/ledger/production_bingx_ws_microstructure_v2.jsonl")
    p.add_argument("--symbols", default="BTC-USDT,ETH-USDT")
    p.add_argument("--out", default="a1_experimental_scalp_snap_receipt.json")
    args = p.parse_args()
    receipt = evaluate(boundary_utc=args.boundary, history_path=Path(args.history), symbols=[x.strip() for x in args.symbols.split(",") if x.strip()])
    Path(args.out).write_text(json.dumps(receipt, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
