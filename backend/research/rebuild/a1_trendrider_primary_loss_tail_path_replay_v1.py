#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_break_main_loss_tail_path_replay_v1 as core
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_trend_rider_wr80_winner_restore_attribution_v1 as wr80

ROOT = Path(__file__).resolve().parents[3]
DESCRIPTOR = ROOT / "backend/research/rebuild/a1_trend_rider_wr8125_exact_parent_v1.json"
SCHEMA = "zel.a1.trendrider_primary.loss_tail_path_replay.v1"
STOP_SCALES = (1.00, 0.90, 0.85, 0.80)
BE_TRIGGERS_R = (None, 1.00, 0.75)
TIMEOUT_BARS = (48,)
ANCHOR = {
    "symbol": "ETH-USDT",
    "signal_ts": 1787079600000,
    "entry_ts": 1787083200000,
    "exit_ts": 1787256000000,
    "side": "long",
    "intent_sha": "7cc8614aaf6eba44b559ee6bbaaef2e6aaad2fd6d179b777bedebd3b4092dadf",
}


def _read(path: Path) -> dict[str, Any]:
    v = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(v, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return v


def _identity(row: Mapping[str, Any]) -> dict[str, Any]:
    return {k: row.get(k) for k in ("symbol", "signal_ts", "entry_ts", "exit_ts", "side", "intent_sha")}


def _select_exact16(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = sorted((dict(x) for x in source.get("trades") or []), key=lambda x: (int(x["entry_ts"]), str(x["symbol"])))
    if len(rows) != 25:
        raise RuntimeError(f"PRIMARY_SOURCE_25T_REQUIRED:{len(rows)}")
    frozen = rows[:24]
    selected = []
    for row in frozen:
        session = wr80.nonus._session(int(row["signal_ts"]))
        if session != "US" or _identity(row) == ANCHOR:
            selected.append(row)
    if len(selected) != 16:
        raise RuntimeError(f"EXACT_PRIMARY_16T_REQUIRED:{len(selected)}")
    if sum(1 for x in selected if _identity(x) == ANCHOR) != 1:
        raise RuntimeError("PRIMARY_ANCHOR_REQUIRED")
    return selected


def _load_historical_policy(source: Mapping[str, Any]):
    rel = str(source.get("policy_path") or "")
    path = ROOT / rel
    if not path.exists():
        raise RuntimeError(f"POLICY_PATH_MISSING:{rel}")
    spec = importlib.util.spec_from_file_location("a1_wr8125_historical_policy", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("POLICY_IMPORT_SPEC_FAIL")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


def _bind_geometry(source: Mapping[str, Any], rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    module, _ = _load_historical_policy(source)
    cfg = ev.config_instance(module)
    compute, build = ev.policy_functions(module, "trend_rider")
    policy_sha = str(source.get("policy_sha") or "")
    snaps = source.get("execution_snapshots") or {}
    out = []
    bars_by: dict[str, list[dict[str, Any]]] = {}
    for symbol in sorted({str(x["symbol"]) for x in rows}):
        bars_by[symbol] = list(ev.fetch_bars(symbol, "1h", limit=1000))
    for row in rows:
        symbol = str(row["symbol"])
        bars = bars_by[symbol]
        idx = next((i for i, b in enumerate(bars) if int(b["ts_ms"]) == int(row["signal_ts"])), None)
        if idx is None:
            raise RuntimeError(f"SIGNAL_BAR_MISSING:{symbol}:{row['signal_ts']}")
        feature = compute(bars[: idx + 1], symbol=symbol, now_ts_ms=int(row["signal_ts"]), config=cfg)
        snap = snaps.get(symbol) if isinstance(snaps, Mapping) else None
        if not isinstance(snap, Mapping):
            raise RuntimeError(f"EXECUTION_SNAPSHOT_MISSING:{symbol}")
        intent = build(
            feature,
            policy_source_sha=policy_sha,
            verified_round_trip_cost_bps=float(snap["pretrade_verified_cost_bps"]),
            config=cfg,
        )
        got = ev.intent_sha(intent)
        if got != str(row["intent_sha"]):
            raise RuntimeError(f"FROZEN_INTENT_GEOMETRY_DRIFT:{symbol}:{row['signal_ts']}:{got}:{row['intent_sha']}")
        sl = getattr(intent, "sl", None)
        if sl is None:
            raise RuntimeError(f"FROZEN_SL_MISSING:{symbol}:{row['signal_ts']}")
        r = dict(row)
        r["intent_geometry"] = {"sl": float(sl)}
        out.append(r)
    return out, bars_by


def run(source_path: Path, out_path: Path) -> dict[str, Any]:
    source = _read(source_path)
    descriptor = _read(DESCRIPTOR)
    if source.get("strategy_id") != "trend_rider" or int(source.get("completed_trades") or 0) != 25:
        raise RuntimeError("EXACT_PRIMARY_SOURCE_REQUIRED")
    if str(source.get("receipt_sha256")) != "b064d6ee58c158cdb1169b79d93d1df46ea020d0dde3762703a577f9a3068103":
        raise RuntimeError("PRIMARY_SOURCE_RECEIPT_DRIFT")
    if any((source.get("execution_authority") != "NONE", source.get("order_authority") != "BLOCKED", source.get("live_trade_authority") != "BLOCKED")):
        raise RuntimeError("SOURCE_AUTHORITY_DRIFT")
    selected = _select_exact16(source)
    baseline = core._metrics(selected)
    dm = descriptor.get("metrics") or {}
    checks = {
        "completed_trades": (baseline["completed_trades"], dm.get("completed_trades")),
        "wins": (baseline["wins"], dm.get("wins")),
        "win_rate": (baseline["win_rate"], dm.get("win_rate")),
        "net_pnl_bps": (baseline["net_pnl_bps"], dm.get("net_pnl_bps")),
        "profit_factor": (baseline["profit_factor"], dm.get("profit_factor")),
        "realized_payoff": (baseline["realized_payoff"], dm.get("payoff")),
        "max_drawdown_bps": (baseline["max_drawdown_bps"], dm.get("max_drawdown_bps")),
    }
    for key, (a, b) in checks.items():
        if b is None or abs(float(a) - float(b)) > 1e-6:
            raise RuntimeError(f"PRIMARY_METRIC_DRIFT:{key}:{a}:{b}")
    selected, bars_by = _bind_geometry(source, selected)
    candidates = []
    for timeout in TIMEOUT_BARS:
        for stop in STOP_SCALES:
            for be in BE_TRIGGERS_R:
                c = core._candidate(selected, bars_by, stop_scale=stop, be_trigger_r=be, timeout_bars=timeout)
                passed, reasons = core._gate(c, baseline, int(baseline["wins"]))
                c["development_gate_pass"] = passed
                c["gate_reasons"] = reasons
                c["score"] = core._score(c["metrics"], baseline) if passed else 0.0
                candidates.append(c)
    passing = sorted((c for c in candidates if c["development_gate_pass"]), key=lambda x: x["score"], reverse=True)
    best = passing[0] if passing else None
    result = {
        "schema_version": SCHEMA,
        "strategy_id": "trend_rider",
        "lane_id": "trend_rider_primary_wr8125",
        "parent_metrics": baseline,
        "grid": {"stop_scales": list(STOP_SCALES), "be_triggers_r": list(BE_TRIGGERS_R), "timeout_bars": list(TIMEOUT_BARS)},
        "passing_count": len(passing),
        "best_candidate": best,
        "decision": "DEVELOPMENT_CANDIDATE_REQUIRES_FRESH_OOS" if best else "KEEP_INCUMBENT",
        "promotion_allowed": False,
        "requires_fresh_oos": True,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    r = run(Path(a.source), Path(a.out))
    b = r.get("best_candidate")
    if b:
        m = b["metrics"]
        print("PASS_TRENDRIDER_PRIMARY_LOSS_TAIL_CANDIDATE", b["candidate_id"], f"T={m['completed_trades']}", f"WR={m['win_rate']:.6f}", f"PNL_BPS={m['net_pnl_bps']:.6f}", f"PF={m['profit_factor']:.6f}", f"PAYOFF={m['realized_payoff']:.6f}", f"DD_BPS={m['max_drawdown_bps']:.6f}")
    else:
        print("KEEP_TRENDRIDER_PRIMARY_NO_VALID_LOSS_TAIL_CANDIDATE")


if __name__ == "__main__":
    main()
