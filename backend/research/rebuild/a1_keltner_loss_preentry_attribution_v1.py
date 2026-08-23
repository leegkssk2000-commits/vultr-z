#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_recent_loss_cluster_diagnostic_v1 as diag
from backend.research.rebuild import breakout_policy_batch_v1 as policy

SCHEMA = "zel.a1.keltner.loss_preentry_attribution.v1"
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
}


def _session(ts_ms: int) -> str:
    h = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).hour
    return "APAC" if h < 8 else "EU" if h < 16 else "US"


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    xs = [float(x[key]) for x in rows if x.get(key) is not None and math.isfinite(float(x[key]))]
    return sum(xs) / len(xs) if xs else None


def _enrich(receipt: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    interval = str((receipt.get("source") or {}).get("interval") or "1h")
    cfg = policy.BreakoutPolicyConfig()
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    index: dict[str, dict[int, int]] = {}
    for symbol in sorted({str(x["symbol"]) for x in rows}):
        bars = [dict(x) for x in ev.fetch_bars(symbol, interval, 1000)]
        by_symbol[symbol] = bars
        index[symbol] = {int(b["ts_ms"]): i for i, b in enumerate(bars)}
    for row in rows:
        symbol = str(row["symbol"])
        signal_ts = int(row["signal_ts"])
        i = index[symbol].get(signal_ts)
        if i is None or i < 64:
            continue
        f = policy.compute_keltner_trend_feature(by_symbol[symbol][: i + 1], symbol=symbol, now_ts_ms=signal_ts, config=cfg)
        v = dict(f.values)
        row["session"] = _session(signal_ts)
        row["expansion_ratio"] = float(v["expansion_ratio"])
        row["chase_atr"] = float(v["chase_atr"])
        row["atr_pct"] = float(f.atr / max(f.close, 1e-12) * 100.0)
        row["ema_spread_atr"] = float(abs(float(v["ema_fast"]) - float(v["ema_slow"])) / max(f.atr, 1e-12))


def run(out: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="keltner_loss_preentry_") as td:
        receipt = diag._run_receipt("keltner_trend", Path(td) / "keltner.json")
    rows = [dict(x) for x in (receipt.get("trades") or [])]
    rows.sort(key=lambda x: (int(x.get("entry_ts") or 0), str(x.get("symbol") or "")))
    _enrich(receipt, rows)

    streak: list[dict[str, Any]] = []
    for x in reversed(rows):
        if float(x.get("net_bps") or 0.0) <= 0.0:
            streak.append(x)
        else:
            break
    streak.reverse()
    prior = rows[:-len(streak)] if streak else rows[:]
    winners = [x for x in prior if float(x.get("net_bps") or 0.0) > 0.0]

    numeric = []
    for key in ("expansion_ratio", "chase_atr", "atr_pct", "ema_spread_atr"):
        a = _mean(streak, key)
        b = _mean(winners or prior, key)
        if a is None or b is None:
            continue
        rel = (a - b) / max(abs(b), 1e-9)
        numeric.append({
            "axis": key.upper(),
            "loss_streak_mean": a,
            "winner_reference_mean": b,
            "relative_delta": rel,
            "absolute_relative_separation": abs(rel),
            "preentry_observable": True,
        })
    numeric.sort(key=lambda x: (-float(x["absolute_relative_separation"]), str(x["axis"])))

    categorical = []
    for key in ("session", "side", "symbol"):
        if not streak:
            continue
        value, n = Counter(str(x.get(key)) for x in streak).most_common(1)[0]
        streak_share = n / len(streak)
        prior_share = sum(1 for x in prior if str(x.get(key)) == value) / max(1, len(prior))
        categorical.append({
            "axis": key.upper(),
            "value": value,
            "loss_streak_share": streak_share,
            "prior_share": prior_share,
            "delta_share": streak_share - prior_share,
            "preentry_observable": True,
        })
    categorical.sort(key=lambda x: (-float(x["delta_share"]), str(x["axis"])))

    strong_numeric = [x for x in numeric if float(x["absolute_relative_separation"]) >= 0.25]
    strong_categorical = [x for x in categorical if float(x["loss_streak_share"]) >= 0.75 and float(x["delta_share"]) >= 0.25]
    roots = strong_categorical + strong_numeric
    root = roots[0] if roots else None
    if len(streak) < 3:
        state = "NO_LOSS_CLUSTER_TRIGGER"
        nxt = "CONTINUE_COLLECTION"
    elif root is None:
        state = "LOSS_CLUSTER_NO_MATERIAL_PREENTRY_SEPARATOR"
        nxt = "CONTINUE_COLLECTION_AND_DO_NOT_RETUNE"
    else:
        state = "MATERIAL_PREENTRY_SEPARATOR_FOUND"
        nxt = f"PREREGISTER_ONE_AXIS_CHILD_WITHOUT_OUTCOME_FITTED_THRESHOLD:{root['axis']}"

    compact = [{k: x.get(k) for k in (
        "symbol", "side", "signal_ts", "reason", "net_bps", "session",
        "expansion_ratio", "chase_atr", "atr_pct", "ema_spread_atr"
    )} for x in streak]
    row = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": "keltner_trend",
        "completed_trades": len(rows),
        "current_loss_streak": len(streak),
        "loss_streak_net_bps": sum(float(x.get("net_bps") or 0.0) for x in streak),
        "loss_streak_trades": compact,
        "prior_trade_count": len(prior),
        "prior_win_count": len(winners),
        "numeric_preentry_separation": numeric,
        "categorical_preentry_separation": categorical,
        "actionable_root_cause": root,
        "post_outcome_axes_forbidden": ["REASON", "HOLD_BARS", "REALIZED_COST_BPS", "COST_TO_ABS_GROSS"],
        "session_taxonomy": "APAC_UTC_00_07__EU_UTC_08_15__US_UTC_16_23",
        "numeric_threshold_sweep": False,
        "incumbent_mutated": False,
        "source_quality_state": ((receipt.get("source_quality_gate") or {}).get("state") if isinstance(receipt.get("source_quality_gate"), dict) else None),
        "integrity_defects": list(receipt.get("integrity_defects") or []),
        "leakage_lookahead": int(receipt.get("leakage_lookahead") or 0),
        "next": nxt,
        **AUTH,
    }
    row["receipt_sha256"] = ev.stable_sha(row)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(row, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return row


def self_test() -> int:
    assert _session(15 * 3600 * 1000) == "EU"
    assert _session(16 * 3600 * 1000) == "US"
    print("PASS_A1_KELTNER_LOSS_PREENTRY_ATTRIBUTION_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_keltner_loss_preentry_attribution_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({
        "state": r["state"],
        "completed_trades": r["completed_trades"],
        "loss_streak": r["current_loss_streak"],
        "root": r["actionable_root_cause"],
        "next": r["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
