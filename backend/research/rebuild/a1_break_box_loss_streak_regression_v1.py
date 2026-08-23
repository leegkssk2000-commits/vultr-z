#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild.a1_fresh_boundary_shadow_replay_v1 import run_terminal_shadow
from backend.research.rebuild.a1_exact25_generic_evaluator_v1 import stable_sha

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
INVENTORY = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
CHILD = ROOT / "backend/research/rebuild/break_and_continue_box_break_child_policy_v1.py"
STRATEGY_ID = "break_and_continue"
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


def ordered_trades(receipt: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [dict(x) for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    return sorted(rows, key=lambda x: (int(x.get("exit_ts") or 0), int(x.get("entry_ts") or 0), str(x.get("symbol") or "")))


def loss_streaks(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    for row in rows:
        if float(row.get("net_bps") or 0.0) < 0.0:
            cur.append(row)
        else:
            if cur:
                groups.append(cur)
                cur = []
    if cur:
        groups.append(cur)
    return groups


def compact_trade(row: Mapping[str, Any]) -> dict[str, Any]:
    return {k: row.get(k) for k in ("symbol", "side", "signal_ts", "entry_ts", "exit_ts", "reason", "gross_bps", "realized_cost_bps", "net_bps")}


def summarize(receipt: Mapping[str, Any]) -> dict[str, Any]:
    rows = ordered_trades(receipt)
    streaks = loss_streaks(rows)
    worst = max(streaks, key=lambda g: (len(g), -sum(float(x.get("net_bps") or 0.0) for x in g)), default=[])
    losses = [x for x in rows if float(x.get("net_bps") or 0.0) < 0.0]
    m = receipt.get("metrics") if isinstance(receipt.get("metrics"), Mapping) else {}
    return {
        "trades": len(rows),
        "wins": sum(1 for x in rows if float(x.get("net_bps") or 0.0) > 0.0),
        "losses": len(losses),
        "win_rate": m.get("win_rate"),
        "net_pnl_bps": m.get("net_pnl_bps"),
        "net_expectancy_bps": m.get("net_expectancy_bps"),
        "profit_factor": m.get("net_profit_factor"),
        "max_drawdown_bps": m.get("max_drawdown_bps"),
        "max_consecutive_losses": len(worst),
        "worst_streak_net_bps": sum(float(x.get("net_bps") or 0.0) for x in worst),
        "worst_streak_symbols": dict(Counter(str(x.get("symbol")) for x in worst)),
        "worst_streak_reasons": dict(Counter(str(x.get("reason")) for x in worst)),
        "worst_streak_trades": [compact_trade(x) for x in worst],
        "largest_single_loss_bps": min((float(x.get("net_bps") or 0.0) for x in losses), default=None),
        "integrity_defects": list(receipt.get("integrity_defects") or []),
        "leakage_lookahead": int(receipt.get("leakage_lookahead") or 0),
        "source_quality_state": ((receipt.get("source_quality_gate") or {}).get("state") if isinstance(receipt.get("source_quality_gate"), Mapping) else None),
    }


def compare(parent: Mapping[str, Any], child: Mapping[str, Any], boundary: str) -> dict[str, Any]:
    p = summarize(parent)
    c = summarize(child)
    streak_delta = int(c["max_consecutive_losses"]) - int(p["max_consecutive_losses"])
    worst_loss_delta = float(c["worst_streak_net_bps"]) - float(p["worst_streak_net_bps"])
    child_econ_positive = bool(
        c.get("net_pnl_bps") is not None and float(c["net_pnl_bps"]) > 0.0
        and c.get("net_expectancy_bps") is not None and float(c["net_expectancy_bps"]) > 0.0
        and (c.get("profit_factor") is None or float(c["profit_factor"]) >= 1.0)
    )
    integrity_ok = not c["integrity_defects"] and int(c["leakage_lookahead"]) == 0
    streak_improved = int(c["max_consecutive_losses"]) < int(p["max_consecutive_losses"])
    streak_loss_improved = float(c["worst_streak_net_bps"]) > float(p["worst_streak_net_bps"])
    if streak_improved and streak_loss_improved and child_econ_positive and integrity_ok:
        state = "PASS_BOX_CHILD_REDUCES_HISTORICAL_LOSS_CLUSTER"
    elif child_econ_positive and integrity_ok:
        state = "HOLD_BOX_CHILD_ECONOMIC_BUT_STREAK_NOT_CLEANLY_REDUCED"
    else:
        state = "HOLD_BOX_CHILD_REGRESSION_OR_INTEGRITY_BLOCK"
    out = {
        "schema_version": "zel.a1.break_box_loss_streak_regression.v1",
        "state": state,
        "strategy_id": STRATEGY_ID,
        "comparison_boundary_utc": boundary,
        "scope": "RETROSPECTIVE_DIAGNOSTIC_ONLY_NOT_FRESH_PROMOTION_EVIDENCE",
        "changed_axis": "BREAKOUT_REFERENCE_PRIOR20_RANGE_TO_EXISTING_8BAR_BOX",
        "parent": p,
        "box_child": c,
        "delta": {
            "trade_count": int(c["trades"]) - int(p["trades"]),
            "max_consecutive_losses": streak_delta,
            "worst_streak_net_bps": worst_loss_delta,
            "win_rate": None if p.get("win_rate") is None or c.get("win_rate") is None else float(c["win_rate"]) - float(p["win_rate"]),
            "net_pnl_bps": None if p.get("net_pnl_bps") is None or c.get("net_pnl_bps") is None else float(c["net_pnl_bps"]) - float(p["net_pnl_bps"]),
            "max_drawdown_bps": None if p.get("max_drawdown_bps") is None or c.get("max_drawdown_bps") is None else float(c["max_drawdown_bps"]) - float(p["max_drawdown_bps"]),
        },
        "historical_parent_five_loss_cluster_confirmed": int(p["max_consecutive_losses"]) >= 5,
        "streak_count_improved": streak_improved,
        "streak_loss_improved": streak_loss_improved,
        "child_economics_positive": child_econ_positive,
        "integrity_ok": integrity_ok,
        "fresh_child_boundary_unchanged": True,
        "promotion_claim": False,
        **AUTH,
    }
    out["receipt_sha256"] = stable_sha(out)
    return out


def run(out: Path) -> dict[str, Any]:
    ledger = read(LEDGER)
    inventory = read(INVENTORY)
    row = (ledger.get("strategies") or {}).get(STRATEGY_ID)
    if not isinstance(row, Mapping):
        raise RuntimeError("BREAK_STRATEGY_MISSING")
    boundary = str(row.get("prospective_boundary_utc") or "")
    if not boundary:
        raise RuntimeError("BREAK_BOUNDARY_MISSING")
    parent_path = ROOT / str(inventory["strategies"][STRATEGY_ID]["policy_owner"])
    with tempfile.TemporaryDirectory(prefix="break_box_streak_regression_") as td:
        td_path = Path(td)
        parent, _ = run_terminal_shadow(strategy_id=STRATEGY_ID, policy_path=parent_path, fresh_boundary_utc=boundary, out=td_path / "parent.json")
        child, _ = run_terminal_shadow(strategy_id=STRATEGY_ID, policy_path=CHILD, fresh_boundary_utc=boundary, out=td_path / "child.json")
    result = compare(parent, child, boundary)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    fake_parent = {
        "trades": [
            {"exit_ts": i, "entry_ts": i, "symbol": "BTC-USDT", "reason": "SL", "net_bps": (-10 if i in (2,3,4,5,6) else 20)}
            for i in range(1, 8)
        ],
        "metrics": {"win_rate": 2/7, "net_pnl_bps": -10, "net_expectancy_bps": -10/7, "net_profit_factor": 0.8, "max_drawdown_bps": 50},
        "integrity_defects": [], "leakage_lookahead": 0,
    }
    fake_child = {
        "trades": [
            {"exit_ts": i, "entry_ts": i, "symbol": "BTC-USDT", "reason": "SL" if i in (2,3) else "TP", "net_bps": (-8 if i in (2,3) else 20)}
            for i in range(1, 9)
        ],
        "metrics": {"win_rate": 0.75, "net_pnl_bps": 104, "net_expectancy_bps": 13, "net_profit_factor": 6.5, "max_drawdown_bps": 16},
        "integrity_defects": [], "leakage_lookahead": 0,
    }
    r = compare(fake_parent, fake_child, "2026-01-01T00:00:00Z")
    assert r["parent"]["max_consecutive_losses"] == 5
    assert r["box_child"]["max_consecutive_losses"] == 2
    assert r["state"] == "PASS_BOX_CHILD_REDUCES_HISTORICAL_LOSS_CLUSTER"
    assert r["promotion_claim"] is False
    print("PASS_A1_BREAK_BOX_LOSS_STREAK_REGRESSION_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_break_box_loss_streak_regression_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({
        "state": r["state"],
        "parent_max_loss_streak": r["parent"]["max_consecutive_losses"],
        "child_max_loss_streak": r["box_child"]["max_consecutive_losses"],
        "parent_worst_streak_bps": r["parent"]["worst_streak_net_bps"],
        "child_worst_streak_bps": r["box_child"]["worst_streak_net_bps"],
        "child_dd_bps": r["box_child"]["max_drawdown_bps"],
        "child_pnl_bps": r["box_child"]["net_pnl_bps"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
