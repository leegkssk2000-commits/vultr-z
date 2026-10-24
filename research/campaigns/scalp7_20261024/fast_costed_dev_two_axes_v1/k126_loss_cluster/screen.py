"""Pre-frozen K126 cheap opportunity-only causal cooldown screen. Not an economic FULL."""

from pathlib import Path
import argparse
import gzip
import hashlib
import json
import math
import importlib
from datetime import datetime, timezone

strategy = importlib.import_module("ops.scalp7_keltner_fresh_touch_successor_v1")

WINDOW_MS = 24 * 3600_000
EMBARGO_MS = 12 * 3600_000


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def p2(t):
    return float(t["gross_bps"]) - 2 * float(t["cost_bps"])


def key(t):
    return (int(t["signal_ts_ms"]), str(t["symbol"]), str(t.get("identity", "")))


def decision(t, kept):
    now = int(t["signal_ts_ms"])
    past = [
        x
        for x in kept
        if 0 < now - int(x["outcome_available_ts_ms"]) <= WINDOW_MS and p2(x) < 0
    ]
    # Only closed trades seen at decision time; skipped trades are never future triggers.
    past.sort(key=lambda x: (int(x["outcome_available_ts_ms"]), str(x["symbol"])))
    blocked = (
        len(past) >= 2 and now - int(past[-1]["outcome_available_ts_ms"]) <= EMBARGO_MS
    )
    return blocked, {
        "known_closed_losses_24h": len(past),
        "latest_loss_available_ts_ms": (
            int(past[-1]["outcome_available_ts_ms"]) if past else None
        ),
    }


def screen(rows):
    kept = []
    removed = []
    trace = []
    for t in sorted(rows, key=key):
        block, meta = decision(t, kept)
        if block:
            removed.append(t)
        else:
            kept.append(t)
        trace.append(
            {
                "signal_ts_ms": int(t["signal_ts_ms"]),
                "symbol": t["symbol"],
                "decision": "BLOCK" if block else "KEEP",
                **meta,
            }
        )
    return kept, removed, trace


def load(folder):
    freeze_raw = (folder / "FREEZE.json").read_bytes()
    if not freeze_raw:
        raise ValueError("FREEZE_MISSING")
    f = json.loads(freeze_raw)
    if (
        f["id"] != "K126_CAUSAL_LOSS_CLUSTER_COOLDOWN_24H12H_V1"
        or f["loss_lookback_hours"] != 24
        or f["embargo_hours_from_latest_loss"] != 12
    ):
        raise ValueError("FROZEN_RULE_DRIFT")
    raw = (folder / "CHRONO_ROWS.json.gz").read_bytes()
    ref_raw = (folder / "CONTROL_SUMMARY.json").read_bytes()
    if (
        digest(raw) != f["input_control_sha256"]
        or digest(ref_raw) != f["baseline_receipt_sha256"]
    ):
        raise ValueError("FROZEN_INPUT_BYTES_CHANGED")
    data = json.loads(gzip.decompress(raw))
    control = json.loads(ref_raw)
    rows = data["carry_scenario_trades"]
    if (
        len(rows) != 126
        or len({(t["symbol"], t["side"], t["signal_ts_ms"]) for t in rows}) != 126
    ):
        raise ValueError("CONTROL_COHORT_DRIFT")
    original = strategy._metrics(rows)
    for c, expected in [
        ("cost1x", control["net1x_child_carry_scenario"]),
        ("cost2x", control["net2x_child_carry_scenario"]),
    ]:
        if not math.isclose(original[c]["Net_bps"], expected, abs_tol=1e-8, rel_tol=0):
            raise ValueError("PARENT_ECONOMIC_PARITY_FAILED")
    return f, rows, original


def run(folder):
    f, rows, original = load(folder)
    kept, removed, trace = screen(rows)
    child = strategy._metrics(kept)
    avoid = sum(-p2(t) for t in removed if p2(t) < 0)
    lost = sum(p2(t) for t in removed if p2(t) > 0)
    audit = {
        "schema": "zel.k126.cheap_causal_cluster_screen.v1",
        "frozen_at_utc": f["frozen_at_utc"],
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_id": f["id"],
        "state": "USED_DEV_OPPORTUNITY_SCREEN_ONLY",
        "parent_T": len(rows),
        "retained_T": len(kept),
        "blocked_T": len(removed),
        "parent": {
            c: {
                n: original[c].get(n)
                for n in ("T", "Net_bps", "PF", "WR_pct", "MaxLossStreak", "DD_bps")
            }
            for c in ["cost1x", "cost2x"]
        },
        "screen": {
            c: {
                n: child[c].get(n)
                for n in ("T", "Net_bps", "PF", "WR_pct", "MaxLossStreak", "DD_bps")
            }
            for c in ["cost1x", "cost2x"]
        },
        "delta1_bps": child["cost1x"]["Net_bps"] - original["cost1x"]["Net_bps"],
        "delta2_bps": child["cost2x"]["Net_bps"] - original["cost2x"]["Net_bps"],
        "avoided_cost2_losses_bps": avoid,
        "foregone_cost2_winners_bps": lost,
        "blocked_loss_count_cost2": sum(p2(t) < 0 for t in removed),
        "blocked_winner_count_cost2": sum(p2(t) > 0 for t in removed),
        "blocked_keys": [
            (t["symbol"], t["signal_ts_ms"], round(p2(t), 4)) for t in removed
        ],
        "opportunity_limited_no_full_chronology": True,
        "newly_freed_entry_opportunities_unobserved": True,
        "source_manifest_sha256": digest((folder / "CHRONO_ROWS.json.gz").read_bytes()),
        "freeze_sha256": digest((folder / "FREEZE.json").read_bytes()),
        "actual_funding_and_account_nav_confirmed": False,
        "strategy_economic_pass": False,
        "orders": 0,
        "market_gets": 0,
        "economic_FULL": 0,
        "action": "hold",
    }
    raw = (
        json.dumps(audit, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode()
    out = folder / "RESULT.json"
    with out.open("xb") as h:
        h.write(raw)
    with (folder / "DECISIONS.json").open("x") as h:
        json.dump(trace, h, indent=2, ensure_ascii=False)
    print("RESULT_SHA256", digest(raw))
    print(
        json.dumps(
            {
                k: v
                for k, v in audit.items()
                if k
                in (
                    "candidate_id",
                    "parent_T",
                    "retained_T",
                    "blocked_T",
                    "delta1_bps",
                    "delta2_bps",
                    "avoided_cost2_losses_bps",
                    "foregone_cost2_winners_bps",
                    "blocked_loss_count_cost2",
                    "blocked_winner_count_cost2",
                    "blocked_keys",
                    "parent",
                    "screen",
                )
            },
            ensure_ascii=False,
        )
    )
    return audit


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    run(ap.parse_args().root)
