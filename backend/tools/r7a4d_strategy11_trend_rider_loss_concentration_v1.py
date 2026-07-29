from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

VERSION = "R7A4D_STRATEGY11_TREND_RIDER_LOSS_CONCENTRATION_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def metric(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def grouped(trades: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        buckets[str(trade.get(key) or "UNKNOWN")].append(trade)
    rows = []
    for label, items in sorted(buckets.items()):
        values = [metric(t.get("net_return_pct")) for t in items]
        losses = [metric(t.get("net_loss_r")) for t in items if metric(t.get("net_return_pct")) <= 0]
        rows.append({
            key: label,
            "trades": len(items),
            "win_rate_pct": sum(v > 0 for v in values) / max(1, len(values)) * 100.0,
            "net_pct": sum(values),
            "average_trade_pct": sum(values) / max(1, len(values)),
            "average_loss_r": sum(losses) / len(losses) if losses else None,
            "worst_loss_r": min(losses) if losses else None,
            "mean_mfe_r": sum(metric(t.get("mfe_r")) for t in items) / len(items),
            "mean_mae_r": sum(metric(t.get("mae_r")) for t in items) / len(items),
            "mean_bars_held": sum(metric(t.get("bars_held")) for t in items) / len(items),
        })
    return rows


def feature_contrast(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    winners = [t for t in trades if metric(t.get("net_return_pct")) > 0]
    losses = [t for t in trades if metric(t.get("net_return_pct")) <= 0]
    names = sorted({k for t in trades for k, v in (t.get("features") or {}).items() if isinstance(v, (int, float, bool))})
    rows = []
    for name in names:
        w = sorted(metric((t.get("features") or {}).get(name)) for t in winners)
        l = sorted(metric((t.get("features") or {}).get(name)) for t in losses)
        if not w or not l:
            continue
        wm = w[len(w)//2]
        lm = l[len(l)//2]
        rows.append({"feature": name, "winner_median": wm, "loss_median": lm, "absolute_gap": abs(wm-lm)})
    rows.sort(key=lambda x: (-x["absolute_gap"], x["feature"]))
    return rows


def sha_trades(trades: Iterable[dict[str, Any]]) -> str:
    return stable_sha(list(trades))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    root = args.artifact_root
    a = json.loads((root / "trend_rider/FIX_FIRST_VALID_ATR_SEED/replay-A.json").read_text())
    b = json.loads((root / "trend_rider/FIX_FIRST_VALID_ATR_SEED/replay-B.json").read_text())
    final = json.loads((root / "final.json").read_text())
    ta = a.get("trades") or []
    tb = b.get("trades") or []
    if sha_trades(ta) != sha_trades(tb):
        raise RuntimeError("A_B_TRADE_LINEAGE_MISMATCH")
    if len(ta) != 24:
        raise RuntimeError(f"UNEXPECTED_TRADE_COUNT:{len(ta)}")
    if final.get("strategy_id") != "trend_rider":
        raise RuntimeError("WRONG_STRATEGY")

    by_symbol = grouped(ta, "symbol")
    by_window = grouped(ta, "window_id")
    by_exit = grouped(ta, "exit_reason")
    contrast = feature_contrast(ta)

    f2 = next(r for r in by_window if r["window_id"] == "F2")
    f1 = next(r for r in by_window if r["window_id"] == "F1")
    sol = next(r for r in by_symbol if r["symbol"] == "SOLUSDT")
    xrp = next(r for r in by_symbol if r["symbol"] == "XRPUSDT")

    giveback_losses = [t for t in ta if metric(t.get("net_return_pct")) <= 0 and metric(t.get("mfe_r")) >= 1.0]
    immediate_losses = [t for t in ta if metric(t.get("net_return_pct")) <= 0 and metric(t.get("mfe_r")) < 0.5]
    htf_feature = next((r for r in contrast if r["feature"] == "htf_trend_up"), None)

    findings = {
        "f1_net_pct": f1["net_pct"],
        "f2_net_pct": f2["net_pct"],
        "f2_win_rate_pct": f2["win_rate_pct"],
        "sol_net_pct": sol["net_pct"],
        "xrp_net_pct": xrp["net_pct"],
        "giveback_loss_count_mfe_ge_1r": len(giveback_losses),
        "immediate_loss_count_mfe_lt_0_5r": len(immediate_losses),
        "htf_trend_up_contrast": htf_feature,
    }

    if htf_feature and htf_feature["winner_median"] > htf_feature["loss_median"] and f2["net_pct"] < 0:
        next_axis = "TREND_REGIME_GATE_HTF_ALIGNMENT"
        reason = "Losses concentrate outside HTF-up alignment, especially in F2; test one portable regime-alignment gate, not a window exclusion."
    elif len(giveback_losses) >= 3:
        next_axis = "MFE_TRAILING"
        reason = "Multiple losing trades reached at least +1R before closing negative; test one path-derived trailing policy."
    else:
        next_axis = "ENTRY_CONTEXT_GATE"
        reason = "Losses are primarily immediate failures without a stable portable contrast."

    payload = {
        "schema_version": "strategy11.trend_rider_loss_concentration.v1",
        "version": VERSION,
        "state": "PASS_TREND_RIDER_LOSS_CONCENTRATION_DECOMPOSITION",
        "source_run_id": "30448483881",
        "source_artifact": "s11-trend-rider-seed-repair-v1-30448483881-attempt-1",
        "source_artifact_digest": "sha256:c1435764ac068ed759424b4261872d08db2dd7c377e322774e90d8ed1441c21e",
        "strategy_id": "trend_rider",
        "trade_count": len(ta),
        "trade_lineage_sha": sha_trades(ta),
        "parity_pass": True,
        "duplicate_trade_count": len(ta) - len({t.get("trade_id") for t in ta}),
        "by_symbol": by_symbol,
        "by_window": by_window,
        "by_exit_reason": by_exit,
        "top_feature_contrasts": contrast[:12],
        "findings": findings,
        "next_single_axis": next_axis,
        "next_axis_reason": reason,
        "window_whitelist_allowed": False,
        "threshold_sweep_allowed": False,
        "candidate_created": False,
        "ai_review_state": "WAIT_GROQ_QUOTA",
        "w1_confirmation_required": True,
        "new_sealed_required": True,
        **SAFETY,
    }
    payload["decomposition_sha"] = stable_sha(payload)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "decomposition.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"state": payload["state"], "next_axis": next_axis, "f2_net": f2["net_pct"], "giveback": len(giveback_losses)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
