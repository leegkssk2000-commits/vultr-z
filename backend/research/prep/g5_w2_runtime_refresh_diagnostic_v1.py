#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import tempfile
from pathlib import Path
from typing import Any

from backend.research.prep import g5_trendrider_broad30_product_oos_v1 as g5
from backend.research.prep import g5_trendrider_w2_forensic_v1 as forensic
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_top5_matched_exit_attribution_v1 as matched

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "backend/research/prep/g5_trendrider_broad30_product_manifest_v1.json"
MATCHED = ROOT / "backend/research/rebuild/a1_top5_matched_exit_attribution_latest.json"
SCHEMA = "zel.g5.trendrider.w2.runtime_refresh_diagnostic.v1"
LANE_ID = "trend_rider_broad_wr7000"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def pf(rows: list[dict[str, Any]]) -> float | str | None:
    wins = sum(max(0.0, float(x.get("net_bps") or 0.0)) for x in rows)
    losses = sum(max(0.0, -float(x.get("net_bps") or 0.0)) for x in rows)
    if not rows:
        return None
    if losses == 0.0:
        return "INF" if wins > 0.0 else None
    return wins / losses


def run(out: Path) -> dict[str, Any]:
    manifest = read(MANIFEST)
    matched_receipt = read(MATCHED)
    if manifest.get("state") != "FROZEN_G5_PRODUCT_MANIFEST":
        raise RuntimeError("G5_MANIFEST_NOT_FROZEN")

    with tempfile.TemporaryDirectory(prefix="g5-w2-runtime-refresh-") as td:
        replay_path = Path(td) / "current_policy.json"
        receipt = g5.current_policy_replay(
            out_path=replay_path,
            boundary_utc=str(manifest["prospective_boundary_utc"]),
        )

    boundary_ms = int(manifest["prospective_boundary_ms"])
    raw0 = sorted(
        [
            dict(x)
            for x in (receipt.get("trades") or [])
            if int(x.get("signal_ts") or 0) > boundary_ms
            and int(x.get("exit_ts") or 0) > boundary_ms
        ],
        key=lambda x: (int(x["signal_ts"]), str(x["symbol"]), str(x["side"])),
    )
    dedup: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    for row in raw0:
        dedup[g5.trade_key(row)] = row
    raw = list(dedup.values())

    target = int(manifest["windows"]["W2"]["target_closed_trades"])
    w2_src = raw[:target]
    symbols = sorted({str(x["symbol"]) for x in w2_src})
    bars_by = {symbol: ev.fetch_bars(symbol, "1h", 1000) for symbol in symbols}
    w2_rows = [matched.row_path(row, bars_by[str(row["symbol"])]) for row in w2_src]

    broad = next(
        (x for x in (matched_receipt.get("lanes") or []) if x.get("lane") == "trend_rider_broad"),
        None,
    )
    if not isinstance(broad, dict):
        raise RuntimeError("MATCHED_BROAD_REFERENCE_MISSING")
    reference_rows = [dict(x) for x in (broad.get("rows") or [])]

    forensic.enrich_preentry(receipt, w2_rows)
    forensic.enrich_preentry(receipt, reference_rows)
    status, axis, route, candidates = forensic.forensic_axis(w2_rows, reference_rows)

    net = sum(float(x.get("net_bps") or 0.0) for x in w2_rows)
    wins = sum(1 for x in w2_rows if float(x.get("net_bps") or 0.0) > 0.0)
    t = len(w2_rows)
    remaining = max(0, target - t)
    required_to_zero = max(0.0, -net)
    required_per_remaining = (
        required_to_zero / remaining if remaining > 0 else (math.inf if required_to_zero > 0 else 0.0)
    )
    profit_factor = pf(w2_rows)
    early_futility = (
        t >= 6
        and wins == 0
        and net <= 0.0
        and (profit_factor == 0.0 or profit_factor is None)
    )

    result = {
        "schema_version": SCHEMA,
        "stage": "G5_DIAGNOSTIC_ONLY",
        "lane_id": LANE_ID,
        "state": "PASS_RUNTIME_REFRESH_DIAGNOSTIC",
        "canonical_parent_mutated": False,
        "promotion_authority": False,
        "selection_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "boundary_utc": manifest.get("prospective_boundary_utc"),
        "w2": {
            "observed_T": t,
            "target_T": target,
            "remaining_T": remaining,
            "wins": wins,
            "losses": t - wins,
            "win_rate": (wins / t) if t else None,
            "net_pnl_bps": net,
            "net_expectancy_bps": (net / t) if t else None,
            "profit_factor": profit_factor,
            "required_future_net_bps_to_cross_zero": required_to_zero,
            "required_average_bps_per_remaining_trade_to_cross_zero": required_per_remaining,
            "summary": matched.summary(w2_rows),
            "reason_counts": forensic.counts(w2_rows, "reason"),
            "side_counts": forensic.counts(w2_rows, "side"),
            "symbol_counts": forensic.counts(w2_rows, "symbol"),
            "rows": w2_rows,
        },
        "forensic": {
            "causal_status": status,
            "selected_axis": axis,
            "recommended_route": route,
            "ranked_preentry_hypotheses": candidates,
        },
        "integrity": {
            "duplicate_count": len(raw0) - len(dedup),
            "integrity_defects": list(receipt.get("integrity_defects") or []),
            "leakage_lookahead": int(receipt.get("leakage_lookahead") or 0),
        },
        "early_futility": early_futility,
        "next": "USE_REFRESHED_PREENTRY_RANKING_TO_FREEZE_ONE_INTERACTION_CHILD;DO_NOT_RETUNE_PARENT",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="out/g5_w2_runtime_refresh_diagnostic_v1.json")
    args = p.parse_args()
    result = run(Path(args.out))
    print(json.dumps({
        "state": result["state"],
        "w2_T": result["w2"]["observed_T"],
        "net_pnl_bps": result["w2"]["net_pnl_bps"],
        "required_avg_remaining_bps": result["w2"]["required_average_bps_per_remaining_trade_to_cross_zero"],
        "axis": result["forensic"]["selected_axis"],
        "early_futility": result["early_futility"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
