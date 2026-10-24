"""Independent G5 closed-row accounting; no market data, no economic replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_pinned(repo: Path, ref: str, path: str, digest: str) -> dict[str, Any]:
    raw = subprocess.run(
        ["git", "-C", str(repo), "show", ref + ":" + path],
        check=True,
        capture_output=True,
    ).stdout
    if sha(raw) != digest:
        raise ValueError("SOURCE_PIN_SHA_DRIFT:" + path)
    obj: dict[str, Any] = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("PINNED_JSON_OBJECT_REQUIRED")
    return obj


def trade_net(trade: dict[str, Any], cost_multiple: int) -> float:
    gross = float(trade["gross_bps"])
    cost = float(trade["cost_bps"])
    if not math.isfinite(gross) or not math.isfinite(cost) or cost < 0:
        raise ValueError("NONFINITE_OR_NEGATIVE_COST")
    if not math.isclose(gross - cost, float(trade["net_bps"]), abs_tol=1e-7, rel_tol=0):
        raise ValueError("PUBLISHED_NET_GROSS_COST_PARITY_FAILED")
    return gross - cost * cost_multiple


def admitted(
    trades: list[dict[str, Any]], boundary: int, observed_at: int, expected: int
) -> list[dict[str, Any]]:
    selected = [t for t in trades if int(t["signal_ts"]) >= boundary]
    ids: set[str] = set()
    events: set[tuple[str, int, str]] = set()
    for t in selected:
        sid = str(t["closed_trade_id"])
        event = (str(t["symbol"]), int(t["signal_ts"]), str(t["side"]))
        if not sid or sid in ids or event in events:
            raise ValueError("DUPLICATE_SOURCE_TRADE_ID")
        ids.add(sid)
        events.add(event)
        if t["side"] != "long":
            raise ValueError("UNEXPECTED_SIDE")
        a, b, c = (int(t[k]) for k in ("signal_ts", "entry_ts", "exit_ts"))
        if not (boundary <= a <= b < c <= observed_at):
            raise ValueError("SOURCE_TIME_OR_G5_BOUNDARY_INVALID")
        trade_net(t, 1)
        trade_net(t, 2)
    if len(selected) != expected:
        raise ValueError("G5_CLOSED_T_COUNT_MISMATCH")
    return sorted(
        selected,
        key=lambda x: (int(x["exit_ts"]), str(x["symbol"]), str(x["closed_trade_id"])),
    )


def metrics(trades: list[dict[str, Any]], multiple: int) -> dict[str, Any]:
    completed = sorted(
        trades,
        key=lambda x: (int(x["exit_ts"]), str(x["symbol"]), str(x["closed_trade_id"])),
    )
    pnls = [trade_net(t, multiple) for t in completed]
    net = sum(pnls)
    positive = sum(x for x in pnls if x > 0)
    negative = -sum(x for x in pnls if x < 0)
    all_positive = sorted((v for v in pnls if v > 0), reverse=True)
    top2 = sum(all_positive[:2])
    per_month: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"T": 0, "net_trade_bps": 0.0}
    )
    cohorts: dict[int, float] = defaultdict(float)
    wins = 0
    running_loss = longest_loss = 0
    for t, value in zip(completed, pnls):
        k = datetime.fromtimestamp(
            int(t["signal_ts"]) / 1000, tz=timezone.utc
        ).strftime("%Y-%m")
        per_month[k]["T"] += 1
        per_month[k]["net_trade_bps"] += value
        cohorts[int(t["exit_ts"])] += value
        if value > 0:
            wins += 1
            running_loss = 0
        elif value < 0:
            running_loss += 1
            longest_loss = max(longest_loss, running_loss)
    eq = peak = drawdown = 0.0
    for ts in sorted(cohorts):
        eq += cohorts[ts]
        peak = max(peak, eq)
        drawdown = max(drawdown, peak - eq)
    profit_contrib = top2 / positive if positive else None
    topwinners = sorted(
        (
            {
                "symbol": t["symbol"],
                "signal_ts": t["signal_ts"],
                "net_trade_bps": trade_net(t, multiple),
            }
            for t in completed
        ),
        key=lambda t: t["net_trade_bps"],
        reverse=True,
    )[:2]
    return {
        "T": len(completed),
        "Net_sum_trade_bps": net,
        "PF": positive / negative if negative else None,
        "WR_pct": 100 * wins / len(completed) if completed else None,
        "MaxLossStreak_exit_sorted": longest_loss,
        "DD_exit_cohort_trade_bps": drawdown,
        "top2_positive_winner_contribution": profit_contrib,
        "top2_winner_net_trade_bps": top2,
        "Net_excluding_top2_trade_bps": net - top2,
        "worst_trade_net_bps": min(pnls) if pnls else None,
        "cost_sum_bps": sum(float(t["cost_bps"]) * multiple for t in completed),
        "by_signal_month": dict(sorted(per_month.items())),
        "top_two": topwinners,
        "same_exit_cohorts": sum(
            len([t for t in completed if int(t["exit_ts"]) == k]) > 1 for k in cohorts
        ),
    }


def overlap_count(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> dict[str, int]:
    pairs = [
        (x, y)
        for x in a
        for y in b
        if int(x["entry_ts"]) < int(y["exit_ts"])
        and int(y["entry_ts"]) < int(x["exit_ts"])
    ]
    return {
        "overlapping_trade_pairs": len(pairs),
        "same_symbol_pairs": sum(x["symbol"] == y["symbol"] for x, y in pairs),
        "distinct_a_trade_keys": len({x["closed_trade_id"] for x, _ in pairs}),
        "distinct_b_trade_keys": len({y["closed_trade_id"] for _, y in pairs}),
    }


def execute(repo: Path, folder: Path) -> dict[str, Any]:
    pin_bytes = (folder / "PIN.json").read_bytes()
    pin = json.loads(pin_bytes)
    if pin["schema"] != "zel.g5.fresh_accountant_exact_snapshot.v1":
        raise ValueError("AUDIT_SCOPE_CHANGED")
    rows = read_pinned(
        repo,
        pin["source_commit"],
        pin["inputs"]["closed_trades"]["path"],
        pin["inputs"]["closed_trades"]["sha256"],
    )
    g5 = read_pinned(
        repo,
        pin["source_commit"],
        pin["inputs"]["g5_status"]["path"],
        pin["inputs"]["g5_status"]["sha256"],
    )
    if g5.get("formal_pass_authority") is not False:
        raise ValueError("UNEXPECTED_FORMAL_AUTHORITY")
    observed = int(g5["observed_at_ms"])
    if rows.get("total_new_closed_T") != 0:
        # V2-specific new-T metric must not be confused with total past-boundary T.
        raise ValueError("V2_NEW_CREDIT_UNEXPECTED")
    result: dict[str, Any] = {
        "schema": "zel.g5.future_closed_trade_readonly_audit.v1",
        "pin_file_sha256": sha(pin_bytes),
        "inputs": pin["inputs"],
        "source_commit": pin["source_commit"],
        "g5_observed_at_ms": observed,
        "model_observed_at_utc": rows["observed_at_utc"],
        "lanes": {},
        "restrictions": {
            "formal_G5_PASS": False,
            "account_NAV": None,
            "real_fee_and_funding": None,
            "real_market_fill_and_received_at": None,
            "marks_to_market": None,
            "cost_1x_2x": "synthetic 20bp or 40bp round-trip based on saved20bp rows",
            "new_economic_FULL": 0,
            "new_orders": 0,
            "new_collectors": 0,
        },
        "action": "hold",
    }
    selected: dict[str, list[dict[str, Any]]] = {}
    for lane, name in pin["lane_map"].items():
        r = rows["lanes"][lane]["closed_trades"]
        status = g5["lanes"][name]
        if status["integrity"]["state"] != "PENDING_LANE_LOCAL_ACCOUNTANT":
            raise ValueError("UNEXPECTED_ACCOUNTING_ADMISSION_STATE")
        chosen = admitted(
            r, int(status["boundary_ms"]), observed, int(status["fresh_closed_T"])
        )
        selected[lane] = chosen
        result["lanes"][name] = {
            "strategy_id": lane,
            "fresh_T": len(chosen),
            "cost1": metrics(chosen, 1),
            "cost2": metrics(chosen, 2),
            "input_trade_keys_sha256": sha(
                json.dumps(
                    [t["closed_trade_id"] for t in chosen], sort_keys=True
                ).encode()
            ),
            "integrity": "SAVED_ROW_ARITHMETIC_AND_G5_BOUNDARY_PARITY_ONLY",
            "decision": "NO_FORMAL_G5_PASS",
        }
    result["cooccupancy"] = overlap_count(
        selected["keltner_trend_main"], selected["supertrend_pullback_main"]
    )
    encoded = (
        json.dumps(
            result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
        + "\n"
    ).encode()
    with (folder / "RESULT.json").open("xb") as out:
        out.write(encoded)
    print("RESULT_SHA256", sha(encoded), flush=True)
    print(
        json.dumps(
            {
                "Supertrend": result["lanes"]["Supertrend Momentum"]["cost2"],
                "Keltner": result["lanes"]["Keltner Reclaim"]["cost2"],
                "cooccupancy": result["cooccupancy"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    execute(args.repo, args.out)
