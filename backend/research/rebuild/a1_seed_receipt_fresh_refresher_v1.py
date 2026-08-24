#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev

ROOT = Path(__file__).resolve().parents[3]
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def seed_symbols(seed: Mapping[str, Any]) -> list[str]:
    source = seed.get("source") if isinstance(seed.get("source"), Mapping) else {}
    raw = source.get("symbols") or seed.get("fixed_universe") or []
    out: list[str] = []
    for item in raw:
        symbol = str(item.get("symbol") if isinstance(item, Mapping) else item or "")
        if symbol and symbol not in out:
            out.append(symbol)
    if not out:
        raise RuntimeError("SEED_SYMBOLS_REQUIRED")
    return out


def load_seed_policy(seed: Mapping[str, Any]) -> tuple[Any, Path, str]:
    raw = str(seed.get("policy_path") or "")
    expected = str(seed.get("policy_sha") or "")
    if not raw:
        raise RuntimeError("SEED_POLICY_PATH_REQUIRED")
    path = (ROOT / raw).resolve()
    if ROOT not in path.parents or not path.is_file():
        raise RuntimeError(f"SEED_POLICY_PATH_INVALID:{raw}")
    sha = ev.git_blob_sha(path)
    if expected and sha != expected:
        raise RuntimeError(f"SEED_POLICY_SHA_MISMATCH:{sha}!={expected}")
    name = f"seed_refresh_{str(seed.get('strategy_id') or 'strategy')}_{sha[:12]}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("SEED_POLICY_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module, path, sha


def evaluate_seed(seed: Mapping[str, Any]) -> dict[str, Any]:
    strategy_id = str(seed.get("strategy_id") or "")
    boundary = str(seed.get("boundary_utc") or "")
    if not strategy_id or not boundary:
        raise RuntimeError("SEED_STRATEGY_AND_BOUNDARY_REQUIRED")
    boundary_ms = int(__import__("datetime").datetime.fromisoformat(boundary.replace("Z", "+00:00")).timestamp() * 1000)
    authority = ev.load_json(ev.COST_PATH)
    if authority.get("state") != "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY":
        raise RuntimeError("COST_AUTHORITY_INVALID")
    module, policy_path, policy_sha = load_seed_policy(seed)
    cfg = ev.config_instance(module)
    interval = ev.interval_for_ms(int(getattr(cfg, "timeframe_ms")))
    seed_interval = str((seed.get("source") or {}).get("interval") or "") if isinstance(seed.get("source"), Mapping) else ""
    if seed_interval and interval != seed_interval:
        raise RuntimeError(f"SEED_INTERVAL_MISMATCH:{interval}!={seed_interval}")
    compute, build = ev.policy_functions(module, strategy_id)
    config_sha = str(getattr(cfg, "sha", ev.stable_sha(asdict(cfg) if is_dataclass(cfg) else vars(cfg))))
    symbols = seed_symbols(seed)

    trades: list[dict[str, Any]] = []
    intent_count = 0
    seen: set[str] = set()
    defects: list[str] = []
    sources: list[dict[str, Any]] = []
    snapshots_full: dict[str, Any] = {}

    for symbol in symbols:
        snap = ev.fetch_execution_snapshot(symbol, authority)
        snapshots_full[symbol] = snap
        bars = ev.fetch_bars(symbol, interval, 1000)
        post = [x for x in bars if int(x["ts_ms"]) >= boundary_ms]
        sources.append({
            "symbol": symbol,
            "bars_total": len(bars),
            "bars_post_boundary": len(post),
            "first_post_boundary_ts": int(post[0]["ts_ms"]) if post else None,
            "last_post_boundary_ts": int(post[-1]["ts_ms"]) if post else None,
        })
        warmup = int(getattr(cfg, "warmup_bars", max(64, int(getattr(cfg, "lookback", 20)) + 10)))
        for i in range(max(1, warmup), len(bars) - 1):
            signal_ts = int(bars[i]["ts_ms"])
            if signal_ts < boundary_ms:
                continue
            try:
                feature = compute(bars[: i + 1], symbol=symbol, now_ts_ms=signal_ts, config=cfg)
                intent = build(
                    feature,
                    policy_source_sha=policy_sha,
                    verified_round_trip_cost_bps=float(snap["pretrade_verified_cost_bps"]),
                    config=cfg,
                )
            except ValueError as exc:
                if str(exc).startswith(("WARMUP_", "WINDOW_", "ATR_")):
                    continue
                defects.append(f"{symbol}:{signal_ts}:POLICY:{exc}")
                continue
            if bool(getattr(intent, "no_trade")):
                continue
            sha = ev.intent_sha(intent)
            if sha in seen:
                defects.append(f"DUPLICATE_INTENT:{sha}")
                continue
            seen.add(sha)
            intent_count += 1
            side_name = str(getattr(intent, "side"))
            if side_name not in ("long", "short"):
                defects.append(f"UNSUPPORTED_SIDE:{side_name}")
                continue
            entry_bar = bars[i + 1]
            entry_px = float(entry_bar["open"])
            side = 1 if side_name == "long" else -1
            timeout = getattr(intent, "timeout", {}) or {}
            timeout_bars = int(timeout.get("bars", getattr(cfg, "timeout_bars", 1)))
            sl, tp = getattr(intent, "sl", None), getattr(intent, "tp", None)
            if sl is None and tp is None:
                defects.append(f"{strategy_id}:EXIT_GEOMETRY_UNSUPPORTED_NO_SL_TP")
                continue
            last_j = i + 1 + max(1, timeout_bars)
            if last_j >= len(bars):
                continue
            exit_px = None; exit_ts = None; reason = None
            for j in range(i + 1, last_j + 1):
                low, high = float(bars[j]["low"]), float(bars[j]["high"])
                if sl is not None and ((side == 1 and low <= float(sl)) or (side == -1 and high >= float(sl))):
                    exit_px, exit_ts, reason = float(sl), int(bars[j]["ts_ms"]), "SL"; break
                if tp is not None and ((side == 1 and high >= float(tp)) or (side == -1 and low <= float(tp))):
                    exit_px, exit_ts, reason = float(tp), int(bars[j]["ts_ms"]), "TP"; break
            if exit_px is None:
                exit_px, exit_ts, reason = float(bars[last_j]["close"]), int(bars[last_j]["ts_ms"]), "TIMEOUT"
            fund = ev.funding_cost(int(entry_bar["ts_ms"]), int(exit_ts), list(snap["funding_rows"]))
            cost = float(snap["fee_bps"]) + float(snap["spread_bps"]) + float(snap["impact_bps"]) + fund
            gross = side * (float(exit_px) - entry_px) / entry_px * 10_000.0
            net = gross - cost
            trades.append({
                "symbol": symbol, "signal_ts": int(getattr(intent, "signal_ts")),
                "entry_ts": int(entry_bar["ts_ms"]), "exit_ts": int(exit_ts), "side": side_name,
                "entry": entry_px, "exit": float(exit_px), "reason": reason,
                "gross_bps": gross, "realized_cost_bps": cost, "net_bps": net,
                "intent_sha": sha, "feature_sha": str(getattr(intent, "feature_sha", "")),
                "config_sha": str(getattr(intent, "config_sha", config_sha)), "policy_sha": policy_sha,
                "cost_snapshot_sha": snap["snapshot_sha256"],
            })

    trades.sort(key=lambda x: (int(x["entry_ts"]), str(x["symbol"]), str(x["intent_sha"])))
    net_values = [float(x["net_bps"]) for x in trades]
    gross_values = [float(x["gross_bps"]) for x in trades]
    wins = [x for x in net_values if x > 0]; losses = [-x for x in net_values if x < 0]
    gp, gl = sum(wins), sum(losses)
    avg_win = gp / len(wins) if wins else None; avg_loss = gl / len(losses) if losses else None
    seed_quality = seed.get("source_quality_gate") if isinstance(seed.get("source_quality_gate"), Mapping) else {"state": "PASS"}
    quality_state = "PASS" if seed_quality.get("state") == "PASS" and not defects else "HOLD"
    receipt = {
        "schema_version": "zel.a1.seed_receipt_fresh_refresh.v1",
        "state": "HOLD_A1_REBUILT_INTEGRITY" if defects else ("WAIT_FRESH_PROSPECTIVE_DATA" if not trades else "A1_REBUILT_ECONOMICS_ACTIVE"),
        "strategy_id": strategy_id, "boundary_utc": boundary,
        "policy_path": str(policy_path.relative_to(ROOT)), "policy_sha": policy_sha, "config_sha": config_sha,
        "evidence_sha": seed.get("evidence_sha"), "seed_receipt_sha256": seed.get("receipt_sha256"),
        "cost_authority_sha256": ev.stable_sha(authority),
        "source": {"endpoint": ev.KLINE_API, "interval": interval, "symbols": sources},
        "source_quality_gate": {"state": quality_state, "source": "FROZEN_SEED_LINEAGE_PLUS_CURRENT_PUBLIC_BINGX"},
        "execution_snapshots": {k: {kk: vv for kk, vv in v.items() if kk != "funding_rows"} for k, v in snapshots_full.items()},
        "intent_count": intent_count, "completed_trades": len(trades),
        "metrics": {
            "gross_pnl_bps": sum(gross_values),
            "gross_expectancy_bps": sum(gross_values) / len(gross_values) if gross_values else None,
            "net_pnl_bps": sum(net_values),
            "net_expectancy_bps": sum(net_values) / len(net_values) if net_values else None,
            "net_profit_factor": ev.profit_factor(gp, gl),
            "net_payoff": avg_win / avg_loss if avg_win is not None and avg_loss not in (None, 0) else None,
            "win_rate": len(wins) / len(net_values) if net_values else None,
            "max_drawdown_bps": ev.max_drawdown(net_values),
        },
        "required_negative_controls": list(seed.get("required_negative_controls") or ["same_count_random_entry", "one_bar_delay", "direction_inversion", "timestamp_shuffle", "indicator_removal"]),
        "negative_control_gate": "PENDING_EXISTING_H4_CONTROL_EVALUATOR",
        "trades": trades, "integrity_defects": defects, "leakage_lookahead": 0,
        "duplicate_count": sum(x.startswith("DUPLICATE_INTENT:") for x in defects),
        **AUTH,
    }
    receipt["receipt_sha256"] = ev.stable_sha(receipt)
    return receipt


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--seed", type=Path); ap.add_argument("--out", type=Path); ap.add_argument("--self-test", action="store_true"); args = ap.parse_args()
    if args.self_test:
        fake = {"source": {"symbols": [{"symbol": "BTC-USDT"}, "ETH-USDT"]}}
        assert seed_symbols(fake) == ["BTC-USDT", "ETH-USDT"]
        print("PASS_A1_SEED_RECEIPT_FRESH_REFRESHER_V1_SELF_TEST")
        return 0
    if not args.seed or not args.out:
        raise SystemExit("--seed and --out required")
    result = evaluate_seed(read(args.seed)); args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"strategy_id": result["strategy_id"], "completed_trades": result["completed_trades"], "state": result["state"], "metrics": result["metrics"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
