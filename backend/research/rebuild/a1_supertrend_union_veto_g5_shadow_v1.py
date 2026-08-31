#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_top5_entry_transplant_replay_v1 as transplant
from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as market

ROOT = Path(__file__).resolve().parents[3]
FREEZE = ROOT / "backend/research/contracts/a1_supertrend_union_veto_g5_shadow_freeze_v1.json"
V2_FREEZE = ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json"
PARENT = ROOT / "backend/research/rebuild/a1_top5_replacement_child_prospective_v2_latest.json"
LATEST = ROOT / "backend/research/rebuild/a1_supertrend_union_veto_g5_shadow_latest.json"
SCHEMA = "zel.a1.supertrend.union_veto_g5_shadow.receipt.v1"
INTERVAL_MS = 14_400_000
PARENT_LANE = "supertrend_pullback_main"
BREAK_ID = "break_replacement_breakout50_long_4h_h6_v2"
KELTNER_ID = "keltner_replacement_trend_pull_long_4h_h12_v2"
BREAK_ALLOW = {"HYPE-USDT", "LINK-USDT"}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def metrics(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    vals = [float(x["net_bps"]) for x in rows]
    gp = sum(x for x in vals if x > 0)
    gl = -sum(x for x in vals if x < 0)
    wins = sum(1 for x in vals if x > 0)
    losses = sum(1 for x in vals if x < 0)
    eq = peak = dd = 0.0
    for value in vals:
        eq += value
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "closed_T": len(vals),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(vals) if vals else None,
        "net_pnl_bps": sum(vals),
        "net_expectancy_bps": sum(vals) / len(vals) if vals else None,
        "profit_factor": gp / gl if gl > 0 else None,
        "drawdown_bps": dd,
    }


def key(row: Mapping[str, Any]) -> str:
    return str(row.get("closed_trade_id") or "")


def previous_ids(previous: Mapping[str, Any] | None, field: str) -> set[str]:
    if not isinstance(previous, Mapping) or previous.get("schema_version") != SCHEMA:
        return set()
    return {str(x) for x in previous.get(field) or []}


def run(out: Path, previous_path: Path | None = None) -> dict[str, Any]:
    freeze = read(FREEZE)
    v2freeze = read(V2_FREEZE)
    parent = read(PARENT)
    assert freeze["schema_version"] == "zel.a1.supertrend.union_veto_g5_shadow.freeze.v1"
    assert freeze["state"] == "FROZEN_CONFIRMED_RISK_OVERLAY_FOR_G5_SHADOW_ONLY"
    assert freeze["parent_lane_id"] == PARENT_LANE
    assert freeze["selected_overlay"]["overlay_id"] == "supertrend_breakout50_or_keltner_reclaim_union_veto_v1"
    assert freeze["shadow_policy"]["g5_shadow_only"] is True
    assert freeze["component_policy"]["no_post_confirmation_retune"] is True
    assert freeze["component_policy"]["no_threshold_sweep"] is True
    assert parent["schema_version"] == "zel.a1.top5.replacement_child.prospective.receipt.v2"
    assert parent["state"] == "PASS_PROSPECTIVE_V2_CHILD_COLLECTION_ACTIVE"
    lane = parent["lanes"][PARENT_LANE]
    rows = [dict(x) for x in lane.get("closed_trades") or []]
    if int(lane.get("closed_T") or 0) != len(rows):
        raise RuntimeError("PARENT_T_MISMATCH")
    if len({key(x) for x in rows}) != len(rows):
        raise RuntimeError("DUPLICATE_PARENT_TRADE")

    specs = {str(x["child_id"]): dict(x["executable_spec"]) for x in v2freeze["children"]}
    if BREAK_ID not in specs or KELTNER_ID not in specs:
        raise RuntimeError("DONOR_SPEC_MISSING")
    symbols = sorted({str(x["symbol"]) for x in rows})
    bars: dict[str, list[dict[str, float]]] = {}
    engines: dict[tuple[str, str], Any] = {}
    if rows:
        min_signal = min(int(x["signal_ts"]) for x in rows)
        max_signal = max(int(x["signal_ts"]) for x in rows)
        for symbol in symbols:
            b = market._bars(symbol, "4h", min_signal, max_signal + INTERVAL_MS)
            bars[symbol] = b
            for donor_id in (BREAK_ID, KELTNER_ID):
                _, engine = market._features(b, specs[donor_id])
                engine.validate(str(specs[donor_id]["entry_rule"]))
                engines[(donor_id, symbol)] = engine

    kept: list[dict[str, Any]] = []
    vetoed: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row["symbol"])
        keltner_hit, _ = transplant.architecture_accepts(row, bars[symbol], engines[(KELTNER_ID, symbol)], specs[KELTNER_ID])
        break_hit = False
        if symbol in BREAK_ALLOW:
            break_hit, _ = transplant.architecture_accepts(row, bars[symbol], engines[(BREAK_ID, symbol)], specs[BREAK_ID])
        veto = bool(keltner_hit or break_hit)
        trace.append({
            "parent_closed_trade_id": key(row),
            "symbol": symbol,
            "signal_ts": int(row["signal_ts"]),
            "breakout50_veto": bool(break_hit),
            "keltner_reclaim_veto": bool(keltner_hit),
            "union_veto": veto,
        })
        (vetoed if veto else kept).append(row)

    previous = read(previous_path) if previous_path and previous_path.is_file() else (read(LATEST) if LATEST.is_file() else None)
    kept_ids = {key(x) for x in kept}
    vetoed_ids = {key(x) for x in vetoed}
    if not previous_ids(previous, "kept_parent_trade_ids").issubset(kept_ids):
        raise RuntimeError("APPEND_ONLY_KEPT_REGRESSION")
    if not previous_ids(previous, "vetoed_parent_trade_ids").issubset(vetoed_ids):
        raise RuntimeError("APPEND_ONLY_VETO_REGRESSION")

    parent_m = metrics(rows)
    shadow_m = metrics(kept)
    state = "WAIT_FRESH_SUPERTREND_PARENT_T" if not rows else "PASS_G5_SHADOW_OVERLAY_ACTIVE"
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "freeze_path": str(FREEZE.relative_to(ROOT)),
        "parent_source_path": str(PARENT.relative_to(ROOT)),
        "parent_source_receipt_sha256": parent.get("receipt_sha256"),
        "parent_lane_id": PARENT_LANE,
        "overlay_id": freeze["selected_overlay"]["overlay_id"],
        "mode": "NEGATIVE_VETO_ON_FRESH_PARENT_SUPERTREND_T",
        "parent_closed_T": len(rows),
        "shadow_kept_T": len(kept),
        "shadow_vetoed_T": len(vetoed),
        "new_trade_admission_count": 0,
        "parent_payload_mutation_count": 0,
        "parent_exit_mutation_count": 0,
        "cost_rededuction_count": 0,
        "parent_metrics": parent_m,
        "shadow_metrics": shadow_m,
        "kept_parent_trade_ids": sorted(kept_ids),
        "vetoed_parent_trade_ids": sorted(vetoed_ids),
        "decision_trace": trace,
        "historical_formal_g4_credit": 0,
        "historical_formal_g5_credit": 0,
        "fresh_formal_g5_credit": 0,
        "economic_roi_credit": False,
        "roadmap_blocking": False,
        "post_confirmation_retune": False,
        "threshold_sweep": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "next": "ACCUMULATE_FRESH_PARENT_T_AND_COMPARE_SHADOW" if not rows else "KEEP_G5_SHADOW_ONLY_UNTIL_CANONICAL_FRESH_GATE",
    }
    result["receipt_sha256"] = market._sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    freeze = read(FREEZE)
    assert freeze["selected_overlay"]["overlay_id"] == "supertrend_breakout50_or_keltner_reclaim_union_veto_v1"
    assert BREAK_ALLOW == {"HYPE-USDT", "LINK-USDT"}
    print("PASS_SUPERTREND_UNION_VETO_G5_SHADOW_SELF_TEST")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path("out/a1_supertrend_union_veto_g5_shadow_latest.json"))
    p.add_argument("--previous", type=Path)
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        return self_test()
    r = run(a.out, a.previous)
    print(json.dumps({
        "state": r["state"],
        "parent_T": r["parent_closed_T"],
        "kept_T": r["shadow_kept_T"],
        "vetoed_T": r["shadow_vetoed_T"],
        "shadow_metrics": r["shadow_metrics"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
