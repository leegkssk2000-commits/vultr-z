from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Mapping

v5: Any = importlib.import_module(
    "backend.research.rebuild.a1_active5_180d_frozen_v5_replay_v1"
)
rt: Any = importlib.import_module(
    "backend.research.rebuild.a1_active5_runner_trailing_v1"
)

RECENT_V6_PATH = Path("/home/z/z/runtime/active5_multimetric_v6_exact.json")
RECENT_V5_PATH = Path("/home/z/z/runtime/active5_multimetric_v5_exact.json")
OUT = Path("/home/z/z/runtime/active5_v6_recovered_180d_v1.json")


def apply_v6(
    sid: str,
    trades: list[dict[str, Any]],
    bars_by_symbol: Mapping[str, list[dict[str, float | int]]],
    btc_ctx: Mapping[int, tuple[float, float, float, float]],
) -> tuple[list[dict[str, Any]], list[float]]:
    if sid == "supertrend_pullback":
        selected = [t for t in trades if v5.weak_keep(t, btc_ctx, 1.25)]
    elif sid == "keltner_trend":
        selected = [t for t in trades if v5.weak_keep(t, btc_ctx, 1.0)]
    elif sid in {"break_and_continue", "trend_ma_macd", "trend_rider"}:
        selected = [t for t in trades if v5.aligned_keep(t, btc_ctx)]
    else:
        selected = list(trades)
    rule = dict(rt.SELECTED[sid][1])
    if rule.get("stale_bars"):
        rule["stale_frac"] = 1.0
    vals = [
        rt.simulate(t, bars_by_symbol[str(t["symbol"])], rule, {}) for t in selected
    ]
    return selected, vals


def recent_recovery_receipt() -> dict[str, Any]:
    recent_v5 = json.loads(RECENT_V5_PATH.read_text())
    recent_v6 = json.loads(RECENT_V6_PATH.read_text())
    expected_delta = float(recent_v6["full"]["Net_bps"]) - float(
        recent_v5["full"]["Net_bps"]
    )
    per_strategy = {}
    for sid in v5.ACTIVE5:
        per_strategy[sid] = {
            "v5_net_bps": recent_v5["strategies"][sid]["full"]["Net_bps"],
            "v6_net_bps": recent_v6["strategies"][sid]["full"]["Net_bps"],
            "delta_bps": float(recent_v6["strategies"][sid]["full"]["Net_bps"])
            - float(recent_v5["strategies"][sid]["full"]["Net_bps"]),
        }
    return {
        "mechanism_recovered": "stale_frac 0.50 -> 1.00 at the existing frozen MFE/deadline; entry filters unchanged",
        "expected_recent_net_delta_bps": expected_delta,
        "expected_recent_v6": recent_v6["full"],
        "per_strategy_expected": per_strategy,
    }


def main() -> int:
    bars = v5.local_1h_bars()
    inventory = v5.ev.load_json(v5.ev.INVENTORY_PATH)
    authority = v5.ev.load_json(v5.ev.COST_PATH)
    costs: dict[str, float] = {}
    cost_receipts: dict[str, Any] = {}
    for sym in v5.v2.SYMS6:
        snap = v5.ev.fetch_execution_snapshot(sym, authority)
        cost_receipts[sym] = snap
        costs[sym] = float(snap["pretrade_verified_cost_bps"])
    ctx = v5.btc_context(bars["BTC-USDT"])
    report: dict[str, Any] = {
        "schema": "zel.a1.active5.v6_recovered_180d.v1",
        "state": "RESEARCH_ONLY_V6_RECOVERED_180D_REPLAY",
        "window": "180d_exact_5m_cache_resampled_to_1h",
        "recovery_receipt": recent_recovery_receipt(),
        "costs_bps": costs,
        "strategies": {},
        "research_only": True,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    agg_v5: list[tuple[int, str, float]] = []
    agg_v6: list[tuple[int, str, float]] = []
    for sid in v5.ACTIVE5:
        raw = v5.replay_raw_strategy(sid, bars, costs, inventory)
        selected5, vals5 = v5.apply_v5(sid, raw, bars, ctx)
        selected6, vals6 = apply_v6(sid, raw, bars, ctx)
        if [t["signal_ts"] for t in selected5] != [t["signal_ts"] for t in selected6]:
            raise RuntimeError(f"V6_ENTRY_SET_CHANGED:{sid}")
        report["strategies"][sid] = {
            "v5_frozen": v5.split_vals(vals5),
            "v6_recovered": v5.split_vals(vals6),
            "T": len(selected6),
            "delta_net_bps": sum(vals6) - sum(vals5),
        }
        for t, val in zip(selected5, vals5):
            agg_v5.append((int(t["exit_ts"]), sid, float(val)))
        for t, val in zip(selected6, vals6):
            agg_v6.append((int(t["exit_ts"]), sid, float(val)))
        print(
            "ACTIVE5_V6_180D_ROW="
            + json.dumps(
                {
                    "strategy_id": sid,
                    "T": len(selected6),
                    "v5": report["strategies"][sid]["v5_frozen"]["full"],
                    "v6": report["strategies"][sid]["v6_recovered"]["full"],
                    "v6_hold": report["strategies"][sid]["v6_recovered"]["holdout40"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    agg_v5.sort(key=lambda z: (z[0], z[1]))
    agg_v6.sort(key=lambda z: (z[0], z[1]))
    report["aggregate_v5"] = v5.split_vals([v for _, _, v in agg_v5])
    report["aggregate_v6"] = v5.split_vals([v for _, _, v in agg_v6])
    report["aggregate_delta_net_bps"] = (
        report["aggregate_v6"]["full"]["Net_bps"]
        - report["aggregate_v5"]["full"]["Net_bps"]
    )
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        "ACTIVE5_V6_180D_AGG="
        + json.dumps(
            {
                "v5": report["aggregate_v5"]["full"],
                "v6": report["aggregate_v6"]["full"],
                "v6_hold": report["aggregate_v6"]["holdout40"],
                "delta_net_bps": report["aggregate_delta_net_bps"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# appended below main for import-time availability; main dispatch is rebound at file end.
def verify_recent_exact() -> dict[str, Any]:
    bars = rt.load_bars()
    ctx = v5.btc_context(bars["BTC-USDT"])
    target = json.loads(RECENT_V6_PATH.read_text())
    rows: list[tuple[int, str, float]] = []
    got_by: dict[str, Any] = {}
    for sid, selected_spec in rt.SELECTED.items():
        source = selected_spec[0]
        trades = sorted(
            json.loads(Path(source).read_text())["trades"],
            key=lambda t: int(t["exit_ts"]),
        )
        selected, vals = apply_v6(sid, trades, bars, ctx)
        got = rt.metrics(vals)
        want = target["strategies"][sid]["full"]
        for key in ("T", "WR", "Net_bps", "PF", "DD_bps"):
            a, b = got[key], want[key]
            if a is None or b is None or abs(float(a) - float(b)) > 1e-8:
                raise RuntimeError(f"RECENT_V6_RECOVERY_MISMATCH:{sid}:{key}:{a}:{b}")
        got_by[sid] = got
        rows.extend((int(t["exit_ts"]), sid, float(v)) for t, v in zip(selected, vals))
    rows.sort(key=lambda z: (z[0], z[1]))
    agg = rt.metrics([v for _, _, v in rows])
    for key in ("T", "WR", "Net_bps", "PF", "DD_bps"):
        if abs(float(agg[key]) - float(target["full"][key])) > 1e-8:
            raise RuntimeError(
                f"RECENT_V6_AGG_MISMATCH:{key}:{agg[key]}:{target['full'][key]}"
            )
    return {"state": "PASS_EXACT_RECOVERY", "aggregate": agg, "strategies": got_by}
