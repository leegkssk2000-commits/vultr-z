#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
MAIN = ROOT / "backend/research/rebuild/a1_break_and_continue_production_main_v1.json"
POLICY = ROOT / "backend/research/rebuild/a1_a4_production_candidate_policy_v1.json"


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def metrics(trades: list[dict[str, Any]]) -> dict[str, float | int]:
    net = [float(x["net_bps"]) for x in trades]
    gross = [float(x["gross_bps"]) for x in trades]
    wins = [x for x in net if x > 0]
    losses = [x for x in net if x < 0]
    cumulative = peak = dd = 0.0
    for x in net:
        cumulative += x
        peak = max(peak, cumulative)
        dd = max(dd, peak - cumulative)
    return {
        "trades": len(trades),
        "wins": len(wins),
        "win_rate": len(wins) / len(trades),
        "gross_pnl_bps": sum(gross),
        "gross_expectancy_bps": sum(gross) / len(trades),
        "net_pnl_bps": sum(net),
        "net_expectancy_bps": sum(net) / len(trades),
        "profit_factor": sum(wins) / -sum(losses),
        "payoff": (sum(wins) / len(wins)) / (-sum(losses) / len(losses)),
        "drawdown_bps": dd,
    }


def close(a: float, b: float, eps: float = 1e-9) -> bool:
    return abs(float(a) - float(b)) <= eps


def main() -> int:
    r = json.loads(MAIN.read_text())
    p = json.loads(POLICY.read_text())
    assert r["schema_version"] == "zel.a1.break_and_continue.production_main.v1"
    assert r["state"] == "FROZEN_PRODUCTION_MAIN" and r["role"] == "MAIN" and r["frozen"] is True
    assert r["strategy_id"] == "break_and_continue"
    assert r["execution_authority"] == "NONE" and r["order_authority"] == "BLOCKED" and r["live_trade_authority"] == "BLOCKED"
    assert r["selection_authority"] is False and r["promotion_authority"] is False and r["protected_mutations"] == 0
    assert r["parameter_sweep"] is False and r["exchange_order_submitted"] is False
    assert r["lineage_axis"] == "SESSION_PRICE_DISCOVERY_OWNER_ONLY"
    assert r["lineage_rule"] == {"outcome_blind": True, "post_outcome_trade_deletion": False, "signal_hour_utc_in": [13, 14, 15]}

    unsigned = dict(r); receipt = unsigned.pop("receipt_sha256")
    assert stable(unsigned) == receipt
    assert r["source_artifact"]["workflow_run_id"] == 32957470368
    assert r["source_artifact"]["artifact_id"] == 9603011773
    assert r["source_artifact"]["artifact_digest"] == "sha256:124f5cb2e3b6f8705a8d8a4b90955c572863df688ae47a17d26b084f0aaaa06a"
    assert r["source_artifact"]["parent_receipt_sha256"] == "401cc362e0ad9a4fc0f7d076c9827b5cfdb8e1ae8713918890605bb40069ecaf"

    trades = r["trades"]
    assert len(trades) == r["completed_trades"] == 9
    assert len({x["intent_sha"] for x in trades}) == 9
    for x in trades:
        hour = (int(x["signal_ts"]) // 3_600_000) % 24
        assert hour in (13, 14, 15)
        assert x["intent_geometry"]["strategy_id"] == "break_and_continue"
        assert x["intent_geometry"]["intent_sha"] == x["intent_sha"]
        assert x["intent_geometry"]["tp"] is None
        assert x["intent_geometry"]["timeout"]["bars"] == 48

    got = metrics(trades); stored = r["metrics"]
    for k in ("trades", "wins"):
        assert int(got[k]) == int(stored[k])
    for k in ("win_rate", "gross_pnl_bps", "gross_expectancy_bps", "net_pnl_bps", "net_expectancy_bps", "profit_factor", "payoff", "drawdown_bps"):
        assert close(float(got[k]), float(stored[k]))

    expected = p["strategies"]["break_and_continue"]["production_main"]
    assert expected["source_path"] == "backend/research/rebuild/a1_break_and_continue_production_main_v1.json"
    for k in ("trades", "win_rate", "net_pnl_bps", "net_expectancy_bps", "profit_factor", "drawdown_bps"):
        assert close(float(stored[k]), float(expected["metrics"][k]))

    print(json.dumps({"state":"PASS_BREAK_PRODUCTION_MAIN_VERIFIED","trades":stored["trades"],"wins":stored["wins"],"wr":stored["win_rate"],"pnl":stored["net_pnl_bps"],"exp":stored["net_expectancy_bps"],"pf":stored["profit_factor"],"payoff":stored["payoff"],"dd":stored["drawdown_bps"],"receipt":receipt}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
