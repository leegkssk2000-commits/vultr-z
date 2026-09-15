from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

v6: Any = importlib.import_module(
    "backend.research.rebuild.a1_active5_v6_recovered_180d_v1"
)
RESULT_PATH = Path(
    "/home/z/worktrees/three-lane-20260913/backend/research/rebuild/active5_v6_recovered_180d_v1_results.json"
)
OUT = Path("/home/z/z/runtime/active5_v6_180d_ledger_v2.json")


def main() -> int:
    frozen = json.loads(RESULT_PATH.read_text())
    costs = {k: float(v) for k, v in frozen["costs_bps"].items()}
    bars = v6.v5.local_1h_bars()
    inventory = v6.v5.ev.load_json(v6.v5.ev.INVENTORY_PATH)
    ctx = v6.v5.btc_context(bars["BTC-USDT"])
    all_rows: list[dict[str, Any]] = []
    per_strategy: dict[str, Any] = {}
    for sid in v6.v5.ACTIVE5:
        raw = v6.v5.replay_raw_strategy(sid, bars, costs, inventory)
        selected, vals = v6.apply_v6(sid, raw, bars, ctx)
        rows: list[dict[str, Any]] = []
        for trade, value in zip(selected, vals):
            row = dict(trade)
            row["v6_net_bps"] = float(value)
            row["v6_full_scratch"] = bool(v6.rt.SELECTED[sid][1].get("stale_bars"))
            rows.append(row)
            all_rows.append(row)
        per_strategy[sid] = {
            "T": len(rows),
            "metrics": v6.rt.metrics([float(r["v6_net_bps"]) for r in rows]),
        }
        print(
            "ACTIVE5_V6_LEDGER_ROW="
            + json.dumps({"strategy_id": sid, **per_strategy[sid]}, sort_keys=True),
            flush=True,
        )
    all_rows.sort(
        key=lambda r: (int(r["exit_ts"]), str(r["strategy_id"]), str(r["symbol"]))
    )
    values = [float(r["v6_net_bps"]) for r in all_rows]
    cut = int(len(all_rows) * 0.60)
    report = {
        "schema": "zel.a1.active5.v6_180d_ledger.v2",
        "state": "RESEARCH_ONLY_LEDGER_COMPLETE",
        "source": str(RESULT_PATH),
        "costs_bps": costs,
        "T": len(all_rows),
        "full": v6.rt.metrics(values),
        "train60": v6.rt.metrics(values[:cut]),
        "holdout40": v6.rt.metrics(values[cut:]),
        "per_strategy": per_strategy,
        "trades": all_rows,
        "research_only": True,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        "ACTIVE5_V6_LEDGER_AGG="
        + json.dumps(
            {
                "T": report["T"],
                "full": report["full"],
                "holdout40": report["holdout40"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
