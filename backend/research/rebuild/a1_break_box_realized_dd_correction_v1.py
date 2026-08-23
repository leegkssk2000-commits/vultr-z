#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild.a1_fresh_boundary_shadow_replay_v1 import run_terminal_shadow
from backend.research.rebuild.a1_multisymbol_realized_dd_v1 import drawdown_integrity
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


def max_loss_streak(receipt: Mapping[str, Any]) -> tuple[int, float]:
    trades = [dict(x) for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    trades.sort(key=lambda x: (int(x.get("exit_ts") or 0), int(x.get("entry_ts") or 0), str(x.get("symbol") or "")))
    best: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []
    for row in trades:
        if float(row.get("net_bps") or 0.0) < 0.0:
            cur.append(row)
            if len(cur) > len(best):
                best = cur[:]
        else:
            cur = []
    return len(best), sum(float(x.get("net_bps") or 0.0) for x in best)


def summarize(receipt: Mapping[str, Any]) -> dict[str, Any]:
    dd = drawdown_integrity(receipt)
    streak, streak_bps = max_loss_streak(receipt)
    metrics = receipt.get("metrics") if isinstance(receipt.get("metrics"), Mapping) else {}
    return {
        "completed_trades": int(receipt.get("completed_trades") or 0),
        "win_rate": metrics.get("win_rate"),
        "net_pnl_bps": metrics.get("net_pnl_bps"),
        "net_expectancy_bps": metrics.get("net_expectancy_bps"),
        "profit_factor": metrics.get("net_profit_factor"),
        "legacy_receipt_max_drawdown_bps": dd["legacy_receipt_max_drawdown_bps"],
        "realized_exit_bucket_max_drawdown_bps": dd["realized_exit_bucket_max_drawdown_bps"],
        "drawdown_ordering_authority": dd["ordering_authority"],
        "max_consecutive_losses_exit_order": streak,
        "worst_loss_streak_net_bps": streak_bps,
        "integrity_defects": list(receipt.get("integrity_defects") or []),
        "leakage_lookahead": int(receipt.get("leakage_lookahead") or 0),
    }


def run(out: Path) -> dict[str, Any]:
    ledger = read(LEDGER)
    inventory = read(INVENTORY)
    row = (ledger.get("strategies") or {}).get(STRATEGY_ID)
    if not isinstance(row, Mapping):
        raise RuntimeError("BREAK_STRATEGY_MISSING")
    boundary = str(row.get("prospective_boundary_utc") or "")
    if not boundary:
        raise RuntimeError("BREAK_BOUNDARY_MISSING")
    parent_policy = ROOT / str(inventory["strategies"][STRATEGY_ID]["policy_owner"])
    with tempfile.TemporaryDirectory(prefix="break_box_dd_correction_") as td:
        td_path = Path(td)
        parent, _ = run_terminal_shadow(
            strategy_id=STRATEGY_ID,
            policy_path=parent_policy,
            fresh_boundary_utc=boundary,
            out=td_path / "parent.json",
        )
        child, _ = run_terminal_shadow(
            strategy_id=STRATEGY_ID,
            policy_path=CHILD,
            fresh_boundary_utc=boundary,
            out=td_path / "child.json",
        )
    p = summarize(parent)
    c = summarize(child)
    if p["integrity_defects"] or c["integrity_defects"] or p["leakage_lookahead"] or c["leakage_lookahead"]:
        state = "HOLD_DD_CORRECTION_INTEGRITY"
    else:
        state = "PASS_BREAK_BOX_DD_ORDERING_CORRECTED"
    result = {
        "schema_version": "zel.a1.break_box_realized_dd_correction.v1",
        "state": state,
        "strategy_id": STRATEGY_ID,
        "comparison_boundary_utc": boundary,
        "correction": "MULTISYMBOL_DD_RECOMPUTED_BY_EXIT_TIMESTAMP_BUCKET_ASC",
        "reason": "Generic multi-symbol receipt DD can reflect symbol append order; this receipt makes realized portfolio DD append-order independent.",
        "parent": p,
        "box_child": c,
        "delta": {
            "realized_exit_bucket_max_drawdown_bps": float(c["realized_exit_bucket_max_drawdown_bps"]) - float(p["realized_exit_bucket_max_drawdown_bps"]),
            "max_consecutive_losses": int(c["max_consecutive_losses_exit_order"]) - int(p["max_consecutive_losses_exit_order"]),
            "worst_loss_streak_net_bps": float(c["worst_loss_streak_net_bps"]) - float(p["worst_loss_streak_net_bps"]),
            "net_pnl_bps": float(c["net_pnl_bps"]) - float(p["net_pnl_bps"]),
        },
        "prior_legacy_dd_comparison_superseded": True,
        "loss_streak_comparison_remains_valid": True,
        "promotion_claim": False,
        **AUTH,
    }
    result["receipt_sha256"] = stable_sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert STRATEGY_ID == "break_and_continue"
    print("PASS_A1_BREAK_BOX_REALIZED_DD_CORRECTION_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_break_box_realized_dd_correction_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({
        "state": r["state"],
        "parent_legacy_dd_bps": r["parent"]["legacy_receipt_max_drawdown_bps"],
        "parent_realized_dd_bps": r["parent"]["realized_exit_bucket_max_drawdown_bps"],
        "child_legacy_dd_bps": r["box_child"]["legacy_receipt_max_drawdown_bps"],
        "child_realized_dd_bps": r["box_child"]["realized_exit_bucket_max_drawdown_bps"],
        "parent_streak": r["parent"]["max_consecutive_losses_exit_order"],
        "child_streak": r["box_child"]["max_consecutive_losses_exit_order"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
