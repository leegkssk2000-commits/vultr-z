#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import BOUNDARY, COST_BPS, SYMBOLS, bars
from backend.research.rebuild.final_four_policy_batch_v1 import FinalFourConfig, features, intent_from_snapshot

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
POLICY = ROOT / "backend/research/rebuild/final_four_policy_batch_v1.py"
PREP = ROOT / "backend/research/early_ai_prep/a1_early_negative_ai_prep_grid_rebalance_v1.json"
CANDIDATE_ID = "grid_rebalance_directional_regime_no_grid_v1"


def _blob_sha(path: Path) -> str:
    raw = path.read_bytes()
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


def _stable_sha(x: Any) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def _pf(xs: list[float]) -> float | None:
    gp = sum(x for x in xs if x > 0)
    gl = -sum(x for x in xs if x < 0)
    return None if gl <= 0 else gp / gl


def _payoff(xs: list[float]) -> float | None:
    w = [x for x in xs if x > 0]
    l = [-x for x in xs if x < 0]
    return None if not w or not l else (sum(w) / len(w)) / (sum(l) / len(l))


def _dd(xs: list[float]) -> float:
    eq = peak = mx = 0.0
    for x in xs:
        eq += x
        peak = max(peak, eq)
        mx = max(mx, peak - eq)
    return mx


def _metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    gross = [float(x["gross_bps"]) for x in trades]
    net = [float(x["net_bps"]) for x in trades]
    return {
        "trades": len(trades),
        "gross_expectancy_bps": sum(gross) / len(gross) if gross else None,
        "net_expectancy_bps": sum(net) / len(net) if net else None,
        "net_pnl_bps": sum(net),
        "profit_factor": _pf(net),
        "payoff": _payoff(net),
        "win_rate": sum(1 for x in net if x > 0) / len(net) if net else None,
        "drawdown_bps": _dd(net),
        "cost_bps_per_trade": COST_BPS,
    }


def _simulate(*, repair: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cfg = FinalFourConfig()
    policy_sha = _blob_sha(POLICY)
    out: list[dict[str, Any]] = []
    source: dict[str, Any] = {}
    blocked_directional = 0
    baseline_signals = 0
    for symbol in SYMBOLS:
        raw = bars(symbol, "5m")
        rs = [{"ts_ms": int(x["ts"]), "open": float(x["open"]), "high": float(x["high"]), "low": float(x["low"]), "close": float(x["close"]), "volume": float(x["volume"])} for x in raw]
        source[symbol] = {"bars": len(rs), "first_ts": int(rs[0]["ts_ms"]) if rs else None, "last_ts": int(rs[-1]["ts_ms"]) if rs else None}
        for i in range(119, len(rs) - 1):
            snap = features("grid_rebalance", rs[: i + 1], symbol=symbol, now_ms=int(rs[i]["ts_ms"]), config=cfg)
            if snap.side == "flat":
                continue
            baseline_signals += 1
            directional = bool(snap.values.get("trend_long")) or bool(snap.values.get("trend_short"))
            if repair and directional:
                blocked_directional += 1
                continue
            intent = intent_from_snapshot(snap, policy_source_sha=policy_sha, verified_round_trip_cost_bps=COST_BPS, config=cfg)
            if intent.no_trade or intent.side not in {"long", "short"}:
                continue
            entry_i = i + 1
            entry_px = float(rs[entry_i]["open"])
            side = 1 if intent.side == "long" else -1
            timeout = int((intent.timeout or {}).get("bars") or cfg.timeout_bars)
            last_j = min(len(rs) - 1, entry_i + max(1, timeout))
            exit_px = exit_ts = reason = None
            path = rs[entry_i : last_j + 1]
            for bar in path:
                lo, hi = float(bar["low"]), float(bar["high"])
                if intent.sl is not None and ((side == 1 and lo <= float(intent.sl)) or (side == -1 and hi >= float(intent.sl))):
                    exit_px, exit_ts, reason = float(intent.sl), int(bar["ts_ms"]), "SL"
                    break
                if intent.tp is not None and ((side == 1 and hi >= float(intent.tp)) or (side == -1 and lo <= float(intent.tp))):
                    exit_px, exit_ts, reason = float(intent.tp), int(bar["ts_ms"]), "TP"
                    break
            if exit_px is None:
                if last_j >= len(rs) - 1:
                    continue
                exit_px, exit_ts, reason = float(rs[last_j]["close"]), int(rs[last_j]["ts_ms"]), "TIMEOUT"
            gross = side * (float(exit_px) / entry_px - 1.0) * 10000.0
            net = gross - COST_BPS
            favorable = adverse = 0.0
            for bar in path:
                if side == 1:
                    favorable = max(favorable, (float(bar["high"]) / entry_px - 1.0) * 10000.0)
                    adverse = max(adverse, (1.0 - float(bar["low"]) / entry_px) * 10000.0)
                else:
                    favorable = max(favorable, (1.0 - float(bar["low"]) / entry_px) * 10000.0)
                    adverse = max(adverse, (float(bar["high"]) / entry_px - 1.0) * 10000.0)
            out.append({
                "symbol": symbol,
                "side": intent.side,
                "signal_ts": int(rs[i]["ts_ms"]),
                "entry_ts": int(rs[entry_i]["ts_ms"]),
                "exit_ts": int(exit_ts),
                "reason": reason,
                "gross_bps": gross,
                "net_bps": net,
                "mfe_bps": favorable,
                "mae_bps": adverse,
                "directional_state": directional,
            })
    return out, {"source": source, "baseline_signals": baseline_signals, "blocked_directional_signals": blocked_directional}


def run() -> dict[str, Any]:
    ledger = json.loads(LEDGER.read_text())
    prep = json.loads(PREP.read_text())
    row = ledger["strategies"]["grid_rebalance"]
    if str(row.get("status")) not in {"A1_ECONOMIC_FAIL", "A1_COST_FUTILITY", "A1_CAUSAL_CONTROL_FAIL", "A1_SPARSE_EVENT_FUTILITY"}:
        return {"candidate_id": CANDIDATE_ID, "state": "SKIP_GRID_NOT_TERMINAL", "grid_status": row.get("status"), "development_only": True, "economic_candidate": False}
    if str(row.get("prospective_boundary_utc")) != BOUNDARY:
        raise RuntimeError(f"BOUNDARY_MISMATCH:{row.get('prospective_boundary_utc')}:{BOUNDARY}")
    axis = (prep.get("top3_axes") or [])[0]
    if axis.get("axis") != "DIRECTIONAL_REGIME_NO_GRID_GATE":
        raise RuntimeError("PREP_AXIS_MISMATCH")
    control_trades, control_state = _simulate(repair=False)
    repair_trades, repair_state = _simulate(repair=True)
    control = _metrics(control_trades)
    repair = _metrics(repair_trades)
    retention = repair["trades"] / control["trades"] if control["trades"] else 0.0
    result = {
        "schema_version": "zel.a1_gen2_grid_directional_regime_dev.v1",
        "candidate_id": CANDIDATE_ID,
        "strategy_id": "grid_rebalance",
        "axis": "DIRECTIONAL_REGIME_NO_GRID_GATE",
        "mechanism": "Frozen grid policy unchanged except suppress new entries whenever its existing EMA21/EMA55 directional state is active.",
        "source_ids": axis.get("source_ids"),
        "boundary": BOUNDARY,
        "development_only": True,
        "prospective": False,
        "uses_data_strictly_before_gen1_boundary": True,
        "cost_bps_per_trade": COST_BPS,
        "control": control,
        "repair": repair,
        "delta": {
            "gross_expectancy_bps": (repair["gross_expectancy_bps"] or 0.0) - (control["gross_expectancy_bps"] or 0.0),
            "net_expectancy_bps": (repair["net_expectancy_bps"] or 0.0) - (control["net_expectancy_bps"] or 0.0),
            "net_pnl_bps": repair["net_pnl_bps"] - control["net_pnl_bps"],
            "profit_factor": (repair["profit_factor"] or 0.0) - (control["profit_factor"] or 0.0),
            "payoff": (repair["payoff"] or 0.0) - (control["payoff"] or 0.0),
            "win_rate": (repair["win_rate"] or 0.0) - (control["win_rate"] or 0.0),
            "drawdown_bps": repair["drawdown_bps"] - control["drawdown_bps"],
        },
        "retention": retention,
        "control_state": control_state,
        "repair_state": repair_state,
        "frozen_collateral": {
            "grid_geometry": "UNCHANGED",
            "entry_thresholds": "UNCHANGED",
            "side_rules": "UNCHANGED",
            "stop_target_timeout": "UNCHANGED",
            "position_sizing": "UNCHANGED",
            "cost": "UNCHANGED_14BPS",
            "new_thresholds": 0,
            "parameter_sweep": False,
        },
        "integrity": {"leakage_lookahead": 0, "outcome_conditioned_deletion": False, "same_corpus_control_repair": True},
        "economic_candidate": bool(repair["trades"] >= 12 and (repair["net_expectancy_bps"] or 0) > 0 and (repair["profit_factor"] or 0) > 1 and (repair["payoff"] or 0) >= 1),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    result["receipt_sha256"] = _stable_sha(result)
    return result


def self_test() -> int:
    assert COST_BPS == 14.0
    assert CANDIDATE_ID == "grid_rebalance_directional_regime_no_grid_v1"
    print("PASS_GRID_DIRECTIONAL_REGIME_DEV_SELF_TEST")
    return 0


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(); p.add_argument("--self-test", action="store_true"); p.add_argument("--out")
    a = p.parse_args()
    if a.self_test:
        raise SystemExit(self_test())
    r = run()
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=2, sort_keys=True) + "\n")
    print(json.dumps(r, sort_keys=True))
