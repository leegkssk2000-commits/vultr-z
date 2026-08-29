#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_top5_additive_entry_union_v1 as addu
from backend.research.rebuild import a1_top5_highamp_rescue_scan_v1 as rescue
from backend.research.rebuild import a1_trend_ma_macd_ablation_child_v1 as ab
from backend.research.rebuild import trend_policy_batch_v1 as policy
from backend.research.rebuild.a1_exact25_generic_evaluator_v1 import stable_sha

ROOT = Path(__file__).resolve().parents[3]
BAD = ROOT / "backend/research/rebuild/a1_trendma_chase_atr_up_long_fresh25_latest.json"
CHASE = ROOT / "backend/research/rebuild/a1_trendma_chase_atr_up_fresh25_latest.json"
EMA_BUNDLE = ROOT / "backend/research/rebuild/a1_finalist_good_regime_fresh25_latest.json"
LONG_REF = ROOT / "backend/research/rebuild/a1_top6_trend_ma_macd_long_rebound_latest.json"
FRESH_OOS = ROOT / "backend/research/rebuild/a1_top6_trend_ma_macd_fresh_oos_latest.json"
PRIMARY = ROOT / "backend/research/rebuild/a1_trendrider_wr8125_exact16_trade_receipt_v1.json"
COST = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
SCHEMA = "zel.a1.trendma52.top5_salvage.v1"
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


def mean(rows: list[dict[str, Any]], key: str) -> float | None:
    vals: list[float] = []
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        x = float(value)
        if math.isfinite(x):
            vals.append(x)
    return sum(vals) / len(vals) if vals else None


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
        previous = policy.compute_trend_ma_macd_feature(
            bars[:i], symbol=symbol, now_ts_ms=int(bars[i - 1]["ts_ms"]), config=cfg,
        )
        v, pv = dict(feature.values), dict(previous.values)
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
            "ema_fast_up": float(v["ema_fast"]) > float(pv["ema_fast"]),
            "chase_atr_up": float(v["chase_atr"]) > float(pv["chase_atr"]),
        })


def near_overlap(parent: list[dict[str, Any]], donor: list[dict[str, Any]], hours: int = 3) -> dict[str, Any]:
    horizon = hours * 3600 * 1000
    matched = 0
    for d in donor:
        ds = int(d.get("signal_ts") or 0)
        if any(
            str(p.get("symbol")) == str(d.get("symbol"))
            and str(p.get("side")).lower() == str(d.get("side")).lower()
            and abs(int(p.get("signal_ts") or 0) - ds) <= horizon
            for p in parent
        ):
            matched += 1
    return {
        "donor_T": len(donor),
        "same_symbol_side_within_3h_T": matched,
        "near_overlap_pct": 100.0 * matched / max(1, len(donor)),
    }


def parent_lanes(trend70_path: Path, a4_dir: Path, break_dir: Path) -> dict[str, dict[str, Any]]:
    trend70 = read(trend70_path)
    primary = read(PRIMARY)
    kdoc = read(rescue.KELTNER)
    sdoc = read(rescue.SUPER)
    kbroad = read(a4_dir / "keltner_trend_exact_parent.json")
    sbroad = read(a4_dir / "supertrend_pullback_exact_parent.json")
    bbroad = read(break_dir / "break_and_continue_exact_parent.json")
    kparent = rescue.select_semantic_parent(kbroad, kdoc)
    sparent = rescue.select_semantic_parent(sbroad, sdoc)
    bparent = rescue.select_break_parent(bbroad)
    lanes = {
        "trend_rider_primary_wr8125": {"strategy_id": "trend_rider", "trades": [dict(x) for x in primary.get("trades") or []]},
        "trend_rider_broad_wr7000": {"strategy_id": "trend_rider", "trades": [dict(x) for x in trend70.get("trades") or []]},
        "break_and_continue_main": {"strategy_id": "break_and_continue", "trades": bparent},
        "keltner_trend_main": {"strategy_id": "keltner_trend", "trades": kparent},
        "supertrend_pullback_main": {"strategy_id": "supertrend_pullback", "trades": sparent},
    }
    expected = {"trend_rider_primary_wr8125": 16, "trend_rider_broad_wr7000": 30, "break_and_continue_main": 9, "keltner_trend_main": 12, "supertrend_pullback_main": 11}
    for lane_id, n in expected.items():
        got = len(lanes[lane_id]["trades"])
        if got != n:
            raise RuntimeError(f"TOP5_PARENT_T_MISMATCH:{lane_id}:{got}/{n}")
    return lanes


def fresh_evidence() -> dict[str, dict[str, Any]]:
    bad = read(BAD)
    chase = read(CHASE)
    bundle = read(EMA_BUNDLE)
    fresh = read(FRESH_OOS)
    ema = ((bundle.get("targets") or {}).get("trend_ma_macd_ema_fast_up_good_v1") or {})
    return {
        "LONG_ONLY_PREEXISTING": {
            "state": fresh.get("state"),
            "T": int(fresh.get("post_boundary_long_child_T") or 0),
            "metrics": fresh.get("pilot_metrics") or {},
            "fresh_pass": str(fresh.get("state") or "").startswith("PASS_"),
        },
        "LONG_EMA_FAST_UP_PREEXISTING": {
            "state": ema.get("state"),
            "T": int(ema.get("completed_trades") or 0),
            "metrics": ema.get("metrics") or {},
            "fresh_pass": str(ema.get("state") or "").startswith("PASS_"),
        },
        "LONG_CHASE_ATR_UP_PREEXISTING": {
            "state": chase.get("state"),
            "T": int(chase.get("completed_trades") or 0),
            "metrics": chase.get("metrics") or {},
            "fresh_pass": str(chase.get("state") or "").startswith("PASS_"),
        },
        "LONG_EMA_AND_CHASE_EXPLORATORY": {
            "state": bad.get("state"),
            "T": int(bad.get("completed_trades") or 0),
            "metrics": bad.get("metrics") or {},
            "fresh_pass": str(bad.get("state") or "").startswith("PASS_"),
        },
    }


def root_forensic(parent_all: list[dict[str, Any]], bars_by: dict[str, list[dict[str, Any]]], maps: dict[str, dict[int, int]]) -> dict[str, Any]:
    bad = read(BAD)
    chase = read(CHASE)
    bundle = read(EMA_BUNDLE)
    long_ref = read(LONG_REF)
    fresh_oos = read(FRESH_OOS)
    ema = ((bundle.get("targets") or {}).get("trend_ma_macd_ema_fast_up_good_v1") or {})
    bad_rows = [dict(x) for x in bad.get("trades") or []]
    chase_rows = [dict(x) for x in chase.get("trades") or []]
    ema_rows = [dict(x) for x in ema.get("trades") or []]
    fresh_losses = [x for x in bad_rows if float(x.get("net_bps") or 0.0) <= 0.0]
    if len(bad_rows) != 9 or len(fresh_losses) != 8:
        raise RuntimeError(f"FRESH9_EXPECTED:{len(bad_rows)}:{len(fresh_losses)}")

    boundary_utc = str(fresh_oos.get("prospective_boundary_utc") or "")
    boundary_ms = ab.parse_boundary(boundary_utc)
    pre = [dict(x) for x in parent_all if int(x.get("signal_ts") or 0) < boundary_ms]
    post = [dict(x) for x in parent_all if int(x.get("signal_ts") or 0) >= boundary_ms]
    long_pre = [x for x in pre if str(x.get("side")).lower() == "long"]
    long_post = [x for x in post if str(x.get("side")).lower() == "long"]
    recorded_native = int((((long_ref.get("native") or {}).get("metrics") or {}).get("trades") or 0))
    recorded_long = int((((long_ref.get("candidate") or {}).get("metrics") or {}).get("trades") or 0))
    chronology_contamination = recorded_native - len(pre)
    chronology_long_contamination = recorded_long - len(long_pre)
    if len(parent_all) != 52 or recorded_native != 52 or recorded_long != 33:
        raise RuntimeError(f"FROZEN_52_33_REFERENCE_REQUIRED:{len(parent_all)}:{recorded_native}:{recorded_long}")
    if chronology_contamination != 1 or chronology_long_contamination != 1 or len(post) != 1 or len(long_post) != 1:
        raise RuntimeError(f"EXPECTED_ONE_POSTBOUNDARY_CONTAMINATION:{len(pre)}:{len(long_pre)}:{len(post)}:{len(long_post)}")

    dev_winners = [dict(x) for x in long_pre if float(x.get("net_bps") or 0.0) > 0.0]
    enrich(dev_winners, bars_by, maps)
    enrich(fresh_losses, bars_by, maps)
    numeric: list[dict[str, Any]] = []
    for key in ("atr_pct", "chase_atr", "impulse_atr", "ema_spread_atr", "ema_fast_slope_atr", "ema_slow_slope_atr", "hist_atr", "hist_delta_atr"):
        lm, wm = mean(fresh_losses, key), mean(dev_winners, key)
        if lm is None or wm is None:
            continue
        rel = (lm - wm) / max(abs(wm), 1e-9)
        numeric.append({"axis": key.upper(), "fresh_loss_mean": lm, "development_winner_mean": wm, "relative_delta": rel, "absolute_relative_separation": abs(rel), "preentry_observable": True})
    numeric.sort(key=lambda x: (-float(x["absolute_relative_separation"]), str(x["axis"])))

    categorical: list[dict[str, Any]] = []
    for key in ("session", "symbol"):
        value, n = Counter(str(x.get(key)) for x in fresh_losses).most_common(1)[0]
        ls = n / len(fresh_losses)
        ws = sum(1 for x in dev_winners if str(x.get(key)) == value) / max(1, len(dev_winners))
        categorical.append({"axis": key.upper(), "value": value, "fresh_loss_share": ls, "development_winner_share": ws, "delta_share": ls - ws, "preentry_observable": True})
    categorical.sort(key=lambda x: (-float(x["delta_share"]), str(x["axis"])))

    def ids(rows: list[dict[str, Any]]) -> set[tuple[str, int, str]]:
        return {(str(x.get("symbol")), int(x.get("signal_ts") or 0), str(x.get("side")).lower()) for x in rows}
    bset, cset, eset = ids(bad_rows), ids(chase_rows), ids(ema_rows)
    chase_overlap = len(bset & cset) / max(1, len(bset))
    ema_overlap = len(bset & eset) / max(1, len(bset))
    strong = [x for x in numeric if float(x["absolute_relative_separation"]) >= 0.25]
    root = strong[0] if strong else (categorical[0] if categorical and float(categorical[0]["delta_share"]) >= 0.25 else None)
    return {
        "boundary_utc": boundary_utc,
        "historical_recorded_native_T": recorded_native,
        "historical_recorded_long_T": recorded_long,
        "chronology_clean_preboundary_native_T": len(pre),
        "chronology_clean_preboundary_long_T": len(long_pre),
        "postboundary_in_recorded_history_T": len(post),
        "postboundary_long_in_recorded_history_T": len(long_post),
        "chronology_contamination_T": chronology_contamination,
        "chronology_long_contamination_T": chronology_long_contamination,
        "development_winner_T": len(dev_winners),
        "fresh_loss_T": len(fresh_losses),
        "fresh_loss_reason_counts": dict(Counter(str(x.get("reason")) for x in fresh_losses)),
        "bad_vs_chase_parent_overlap_pct": 100.0 * chase_overlap,
        "bad_vs_ema_fast_overlap_pct": 100.0 * ema_overlap,
        "numeric_preentry_separation": numeric,
        "categorical_preentry_separation": categorical,
        "top_root_axis": root,
        "numeric_threshold_sweep": False,
        "outcome_fitted_cutoff_forbidden": True,
    }


def run(parent_path: Path, trend70_path: Path, a4_dir: Path, break_dir: Path, out: Path) -> dict[str, Any]:
    exact = read(parent_path)
    parent_all = [dict(x) for x in exact.get("trades") or []]
    if str(exact.get("strategy_id")) != "trend_ma_macd" or len(parent_all) != 52:
        raise RuntimeError(f"EXACT_TRENDMA_52_REQUIRED:{exact.get('strategy_id')}:{len(parent_all)}")
    if exact.get("integrity_defects"):
        raise RuntimeError("TRENDMA_PARENT_INTEGRITY_DEFECT")

    authority = read(COST)
    bars_by, maps, _ = ab.load_shared_inputs(SYMBOLS, authority)
    enriched = [dict(x) for x in parent_all]
    enrich(enriched, bars_by, maps)

    cohorts: dict[str, dict[str, Any]] = {
        "ALL52_DIAGNOSTIC": {"rows": enriched, "preexisting": True, "promotable_from_history": False},
        "LONG_ONLY_PREEXISTING": {"rows": [x for x in enriched if str(x.get("side")).lower() == "long"], "preexisting": True, "promotable_from_history": False},
        "LONG_EMA_FAST_UP_PREEXISTING": {"rows": [x for x in enriched if str(x.get("side")).lower() == "long" and bool(x.get("ema_fast_up"))], "preexisting": True, "promotable_from_history": False},
        "LONG_CHASE_ATR_UP_PREEXISTING": {"rows": [x for x in enriched if str(x.get("side")).lower() == "long" and bool(x.get("chase_atr_up"))], "preexisting": True, "promotable_from_history": False},
        "LONG_EMA_AND_CHASE_EXPLORATORY": {"rows": [x for x in enriched if str(x.get("side")).lower() == "long" and bool(x.get("ema_fast_up")) and bool(x.get("chase_atr_up"))], "preexisting": False, "promotable_from_history": False},
        "LONG_EU_CONTEXT_SEED": {"rows": [x for x in enriched if str(x.get("side")).lower() == "long" and x.get("session") == "EU"], "preexisting": False, "promotable_from_history": False},
        "LONG_APAC_CONTEXT_SEED": {"rows": [x for x in enriched if str(x.get("side")).lower() == "long" and x.get("session") == "APAC"], "preexisting": False, "promotable_from_history": False},
        "LONG_US_CONTEXT_SEED": {"rows": [x for x in enriched if str(x.get("side")).lower() == "long" and x.get("session") == "US"], "preexisting": False, "promotable_from_history": False},
        "OUTCOME_ORACLE_LONG_WINNERS": {"rows": [x for x in enriched if str(x.get("side")).lower() == "long" and float(x.get("net_bps") or 0.0) > 0.0], "preexisting": False, "promotable_from_history": False, "outcome_selected_oracle": True},
    }
    fwd = fresh_evidence()
    lanes = parent_lanes(trend70_path, a4_dir, break_dir)
    cohort_out: dict[str, Any] = {}
    attachable_now: list[dict[str, Any]] = []
    latent_by_lane: dict[str, list[str]] = {k: [] for k in lanes}

    for name, meta in cohorts.items():
        rows = [dict(x) for x in meta["rows"]]
        m = addu.metrics(rows)
        evidence = fwd.get(name)
        unions: dict[str, Any] = {}
        for lane_id, parent in lanes.items():
            u = addu.evaluate(parent, {"strategy_id": "trend_ma_macd", "trades": rows})
            near = near_overlap(parent["trades"], rows)
            unions[lane_id] = {
                "state": u["state"],
                "parent_T": u["parent_trade_count"],
                "added_only_T": u["added_only_trade_count"],
                "overlap_T": u["overlap_trade_count"],
                "overlap_payload_mutation_T": u["overlap_payload_mutation_count"],
                "parent_metrics": u["parent_metrics"],
                "added_metrics": u["added_only_metrics"],
                "combined_metrics": u["combined_metrics"],
                "failed_checks": u["failed_checks"],
                "near_overlap": near,
            }
            if name == "OUTCOME_ORACLE_LONG_WINNERS" and u["state"] == "PASS_ADD_ONLY_ENTRY_LANE":
                latent_by_lane[lane_id].append(name)
            fresh_pass = bool(evidence and evidence.get("fresh_pass"))
            if meta.get("preexisting") and name != "ALL52_DIAGNOSTIC" and u["state"] == "PASS_ADD_ONLY_ENTRY_LANE" and fresh_pass:
                attachable_now.append({"lane_id": lane_id, "cohort": name})
        cohort_out[name] = {
            "historical_metrics": m,
            "preexisting_axis": bool(meta.get("preexisting")),
            "outcome_selected_oracle": bool(meta.get("outcome_selected_oracle")),
            "historical_outcome_promotable": False,
            "fresh_evidence": evidence,
            "top5_unions": unions,
        }

    root = root_forensic(parent_all, bars_by, maps)
    side = {
        "all52": addu.metrics(enriched),
        "long": addu.metrics([x for x in enriched if str(x.get("side")).lower() == "long"]),
        "short": addu.metrics([x for x in enriched if str(x.get("side")).lower() == "short"]),
    }
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_TRENDMA52_TOP5_SALVAGE_FORENSIC",
        "strategy_id": "trend_ma_macd",
        "exact_parent_T": len(parent_all),
        "side_decomposition": side,
        "fresh9_root_forensic": root,
        "cohorts": cohort_out,
        "attachable_now": attachable_now,
        "direct_attach_now_count": len(attachable_now),
        "latent_oracle_ceiling_by_lane": latent_by_lane,
        "interpretation": {
            "direct_attach_requires_preexisting_axis_and_strict_add_only_pass_and_fresh_pass": True,
            "outcome_oracle_is_ceiling_only": True,
            "context_seeds_require_new_preregistered_prospective_child": True,
            "parent_trade_delete_or_rewrite_forbidden": True,
            "top5_ssot_mutated": False,
            "strategy_runtime_mutated": False,
        },
        "next": "IF_DIRECT_ATTACH_ZERO_USE_ROOT_AXIS_TO_BUILD_ONE_NON_OUTCOME_FITTED_LONG_CONFIRMATION_CHILD_THEN_FRESH_PROSPECTIVE; OTHERWISE_VALIDATE_ATTACHABLE_CHILD",
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
    p = [{"symbol": "BTC", "signal_ts": 0, "side": "long"}]
    d = [{"symbol": "BTC", "signal_ts": 2 * 3600 * 1000, "side": "long"}]
    assert near_overlap(p, d)["near_overlap_pct"] == 100.0
    print("PASS_A1_TRENDMA52_TOP5_SALVAGE_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", type=Path)
    ap.add_argument("--trend70-source", type=Path)
    ap.add_argument("--a4-source-dir", type=Path)
    ap.add_argument("--break-source-dir", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_trendma52_top5_salvage_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not all((args.parent, args.trend70_source, args.a4_source_dir, args.break_source_dir)):
        raise SystemExit("--parent --trend70-source --a4-source-dir --break-source-dir required")
    r = run(args.parent, args.trend70_source, args.a4_source_dir, args.break_source_dir, args.out)
    print(json.dumps({
        "state": r["state"],
        "direct_attach_now_count": r["direct_attach_now_count"],
        "attachable_now": r["attachable_now"],
        "side": r["side_decomposition"],
        "root": r["fresh9_root_forensic"]["top_root_axis"],
        "latent": r["latent_oracle_ceiling_by_lane"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
