#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_trend_ma_macd_ablation_child_v1 as ab
from backend.research.rebuild import trend_policy_batch_v1 as policy
from backend.research.rebuild.a1_exact25_generic_evaluator_v1 import stable_sha

ROOT = Path(__file__).resolve().parents[3]
BAD = ROOT / "backend/research/rebuild/a1_trendma_chase_atr_up_long_fresh25_latest.json"
CHASE_PARENT = ROOT / "backend/research/rebuild/a1_trendma_chase_atr_up_fresh25_latest.json"
EMA_BUNDLE = ROOT / "backend/research/rebuild/a1_finalist_good_regime_fresh25_latest.json"
LONG_REF = ROOT / "backend/research/rebuild/a1_top6_trend_ma_macd_long_rebound_latest.json"
FRESH_OOS = ROOT / "backend/research/rebuild/a1_top6_trend_ma_macd_fresh_oos_latest.json"
COST = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
SCHEMA = "zel.a1.trendma.fresh9.preentry_forensic.v1"
SYMBOLS = [
    "BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "1INCH-USDT", "ETHFI-USDT",
    "HYPE-USDT", "BCH-USDT", "APE-USDT", "1000PEPE-USDT", "DOGE-USDT", "LINK-USDT",
]
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


def session(ts_ms: int) -> str:
    hour = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).hour
    return "APAC" if hour < 8 else "EU" if hour < 16 else "US"


def ident(row: dict[str, Any]) -> tuple[str, int, str]:
    return str(row.get("symbol")), int(row.get("signal_ts") or 0), str(row.get("side")).lower()


def mean(rows: list[dict[str, Any]], key: str) -> float | None:
    xs: list[float] = []
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        x = float(value)
        if math.isfinite(x):
            xs.append(x)
    return sum(xs) / len(xs) if xs else None


def enrich(rows: list[dict[str, Any]], bars_by: dict[str, list[dict[str, Any]]], maps: dict[str, dict[int, int]]) -> None:
    cfg = policy.TrendPolicyConfig()
    for row in rows:
        symbol = str(row["symbol"])
        signal_ts = int(row["signal_ts"])
        i = maps[symbol].get(signal_ts)
        if i is None or i < 64:
            raise RuntimeError(f"SIGNAL_BAR_NOT_FOUND:{symbol}:{signal_ts}")
        bars = bars_by[symbol]
        feature = policy.compute_trend_ma_macd_feature(bars[: i + 1], symbol=symbol, now_ts_ms=signal_ts, config=cfg)
        prev = policy.compute_trend_ma_macd_feature(
            bars[:i], symbol=symbol, now_ts_ms=int(bars[i - 1]["ts_ms"]), config=cfg,
        )
        v, pv = dict(feature.values), dict(prev.values)
        atr = max(float(feature.atr), 1e-12)
        row.update({
            "session": session(signal_ts),
            "atr_pct": 100.0 * float(feature.atr) / max(float(feature.close), 1e-12),
            "chase_atr": float(v["chase_atr"]),
            "impulse_atr": float(v["impulse_atr"]),
            "ema_spread_atr": abs(float(v["ema_fast"]) - float(v["ema_slow"])) / atr,
            "ema_fast_slope_atr": (float(v["ema_fast"]) - float(pv["ema_fast"])) / atr,
            "ema_slow_slope_atr": (float(v["ema_slow"]) - float(pv["ema_slow"])) / atr,
            "hist_atr": float(v["hist"]) / atr,
            "hist_delta_atr": (float(v["hist"]) - float(v["hist_prev"])) / atr,
        })


def overlap(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> dict[str, Any]:
    aa, bb = {ident(x) for x in a}, {ident(x) for x in b}
    common = aa & bb
    return {
        "left_T": len(aa), "right_T": len(bb), "common_T": len(common),
        "left_overlap_pct": 100.0 * len(common) / max(1, len(aa)),
        "right_overlap_pct": 100.0 * len(common) / max(1, len(bb)),
    }


def run(parent_path: Path, out: Path) -> dict[str, Any]:
    bad = read(BAD)
    chase_parent = read(CHASE_PARENT)
    bundle = read(EMA_BUNDLE)
    long_ref = read(LONG_REF)
    fresh_oos = read(FRESH_OOS)
    authority = read(COST)
    exact_parent = read(parent_path)

    bad_rows = [dict(x) for x in bad.get("trades") or []]
    chase_rows = [dict(x) for x in chase_parent.get("trades") or []]
    ema_target = ((bundle.get("targets") or {}).get("trend_ma_macd_ema_fast_up_good_v1") or {})
    ema_rows = [dict(x) for x in ema_target.get("trades") or []]
    if len(bad_rows) != 9 or int(bad.get("metrics", {}).get("wins") or 0) != 1:
        raise RuntimeError("EXPECTED_FRESH9_1WIN_RECEIPT")
    if str(bad.get("source_quality_state")) != "PASS" or bad.get("integrity_defects"):
        raise RuntimeError("BAD_RECEIPT_INTEGRITY_NOT_CLEAN")
    if str(exact_parent.get("strategy_id")) != "trend_ma_macd":
        raise RuntimeError("EXACT_TRENDMA_PARENT_REQUIRED")

    development_end_utc = str(fresh_oos.get("prospective_boundary_utc") or "")
    if not development_end_utc:
        raise RuntimeError("FROZEN_DEVELOPMENT_END_REQUIRED")
    development_end_ms = ab.parse_boundary(development_end_utc)
    parent_all = [dict(x) for x in exact_parent.get("trades") or []]
    parent_frozen = [x for x in parent_all if int(x.get("signal_ts") or 0) < development_end_ms]
    expected_native_T = int((((long_ref.get("native") or {}).get("metrics") or {}).get("trades") or 0))
    expected_long_T = int((((long_ref.get("candidate") or {}).get("metrics") or {}).get("trades") or 0))
    long_dev = [x for x in parent_frozen if str(x.get("side")).lower() == "long"]
    if len(parent_frozen) != expected_native_T or len(long_dev) != expected_long_T:
        raise RuntimeError(
            f"EXACT_PARENT_LINEAGE_MISMATCH:native={len(parent_frozen)}/{expected_native_T}:long={len(long_dev)}/{expected_long_T}:cut={development_end_utc}"
        )

    dev_winners = [x for x in long_dev if float(x.get("net_bps") or 0.0) > 0.0]
    fresh_losses = [x for x in bad_rows if float(x.get("net_bps") or 0.0) <= 0.0]
    if len(fresh_losses) != 8 or not dev_winners:
        raise RuntimeError("REFERENCE_GROUPS_NOT_AS_EXPECTED")

    bars_by, maps, _snapshots = ab.load_shared_inputs(SYMBOLS, authority)
    enrich(dev_winners, bars_by, maps)
    enrich(fresh_losses, bars_by, maps)

    numeric: list[dict[str, Any]] = []
    for key in (
        "atr_pct", "chase_atr", "impulse_atr", "ema_spread_atr",
        "ema_fast_slope_atr", "ema_slow_slope_atr", "hist_atr", "hist_delta_atr",
    ):
        loss_mean, winner_mean = mean(fresh_losses, key), mean(dev_winners, key)
        if loss_mean is None or winner_mean is None:
            continue
        rel = (loss_mean - winner_mean) / max(abs(winner_mean), 1e-9)
        numeric.append({
            "axis": key.upper(), "fresh_loss_mean": loss_mean, "development_winner_mean": winner_mean,
            "relative_delta": rel, "absolute_relative_separation": abs(rel), "preentry_observable": True,
        })
    numeric.sort(key=lambda x: (-float(x["absolute_relative_separation"]), str(x["axis"])))

    categorical: list[dict[str, Any]] = []
    for key in ("session", "symbol"):
        value, n = Counter(str(x.get(key)) for x in fresh_losses).most_common(1)[0]
        loss_share = n / len(fresh_losses)
        winner_share = sum(1 for x in dev_winners if str(x.get(key)) == value) / max(1, len(dev_winners))
        categorical.append({
            "axis": key.upper(), "value": value, "fresh_loss_share": loss_share,
            "development_winner_share": winner_share, "delta_share": loss_share - winner_share,
            "preentry_observable": True,
        })
    categorical.sort(key=lambda x: (-float(x["delta_share"]), str(x["axis"])))

    strong_numeric = [x for x in numeric if float(x["absolute_relative_separation"]) >= 0.25]
    strong_categorical = [x for x in categorical if float(x["fresh_loss_share"]) >= 0.75 and float(x["delta_share"]) >= 0.25]
    roots = strong_categorical + strong_numeric
    root = roots[0] if roots else None

    chase_long_overlap = overlap(chase_rows, bad_rows)
    chase_ema_overlap = overlap(bad_rows, ema_rows)
    shared_parent_failure = (
        chase_long_overlap["left_overlap_pct"] >= 80.0
        and chase_ema_overlap["left_overlap_pct"] >= 70.0
        and int(ema_target.get("metrics", {}).get("wins") or 0) <= 1
    )
    if root is not None and shared_parent_failure:
        state = "SHARED_PARENT_REGIME_SEPARATOR_FOUND"
        nxt = f"SEARCH_PREEXISTING_NON_OUTCOME_FITTED_GEOMETRY:{root['axis']}"
    elif root is not None:
        state = "MATERIAL_PREENTRY_SEPARATOR_FOUND"
        nxt = f"SEARCH_PREEXISTING_NON_OUTCOME_FITTED_GEOMETRY:{root['axis']}"
    else:
        state = "NO_MATERIAL_PREENTRY_SEPARATOR"
        nxt = "HANDOFF_EXIT_OR_ARCHITECTURE_REPLACEMENT_NO_RETUNE"

    compact_losses = [{k: x.get(k) for k in (
        "symbol", "signal_ts", "reason", "net_bps", "session", "atr_pct", "chase_atr", "impulse_atr",
        "ema_spread_atr", "ema_fast_slope_atr", "ema_slow_slope_atr", "hist_atr", "hist_delta_atr",
    )} for x in fresh_losses]
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": "trend_ma_macd",
        "bad_child_identity": bad.get("candidate_identity"),
        "bad_child_T": len(bad_rows),
        "bad_child_wins": int(bad.get("metrics", {}).get("wins") or 0),
        "bad_child_net_bps": float(bad.get("net_pnl_bps") or 0.0),
        "bad_child_pf": float(bad.get("profit_factor") or 0.0),
        "fresh_loss_T": len(fresh_losses),
        "fresh_loss_reason_counts": dict(Counter(str(x.get("reason")) for x in fresh_losses)),
        "exact_parent_current_T": len(parent_all),
        "frozen_native_reference_T": len(parent_frozen),
        "development_long_reference_T": len(long_dev),
        "development_winner_T": len(dev_winners),
        "development_frozen_end_utc": development_end_utc,
        "development_frozen_end_source": "a1_top6_trend_ma_macd_fresh_oos_latest.prospective_boundary_utc",
        "comparator_source": "A1_EXACT25_GENERIC_EVALUATOR_V2_TERMINAL_REPLAY_EXACT_PARENT_TRADES",
        "chase_parent_vs_long_child_overlap": chase_long_overlap,
        "chase_vs_ema_fast_overlap": chase_ema_overlap,
        "shared_parent_failure_supported": shared_parent_failure,
        "numeric_preentry_separation": numeric,
        "categorical_preentry_separation": categorical,
        "actionable_root_cause": root,
        "fresh_loss_rows": compact_losses,
        "post_outcome_root_axes_forbidden": ["REASON", "EXIT_TS", "REALIZED_COST_BPS", "NET_BPS"],
        "side_axis_excluded_reason": "ALL_TARGET_ROWS_LONG_BY_CONSTRUCTION",
        "fixed_rr_rescue_reuse_forbidden": True,
        "numeric_threshold_sweep": False,
        "outcome_fitted_cutoff_forbidden": True,
        "fresh_child_created": False,
        "integrity_defects": [],
        "next": nxt,
        **AUTH,
    }
    result["receipt_sha256"] = stable_sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert session(0) == "APAC"
    assert session(10 * 3600 * 1000) == "EU"
    assert session(18 * 3600 * 1000) == "US"
    a = [{"symbol": "BTC", "signal_ts": 1, "side": "long"}]
    assert overlap(a, a)["left_overlap_pct"] == 100.0
    print("PASS_A1_TRENDMA_FRESH9_PREENTRY_FORENSIC_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_trendma_fresh9_preentry_forensic_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.parent is None:
        raise SystemExit("--parent required")
    r = run(args.parent, args.out)
    print(json.dumps({
        "state": r["state"], "root": r["actionable_root_cause"],
        "chase_long_overlap": r["chase_parent_vs_long_child_overlap"],
        "ema_overlap": r["chase_vs_ema_fast_overlap"], "next": r["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
