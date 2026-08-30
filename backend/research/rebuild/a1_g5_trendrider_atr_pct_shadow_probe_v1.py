#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT = ROOT / "backend/research/contracts/a1_g5_trendrider_atr_pct_shadow_probe_v1.json"
DEFAULT_FORENSIC = ROOT / "backend/research/prep/g5_trendrider_w2_forensic_latest.json"
DEFAULT_PRODUCT = ROOT / "backend/research/prep/g5_trendrider_broad30_product_latest.json"
DEFAULT_OUT = ROOT / "out/a1_g5_trendrider_atr_pct_shadow_probe_latest.json"


def read(path: Path) -> dict[str, Any]:
    x = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(x, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return x


def sha(v: Any) -> str:
    b = json.dumps(v, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(b).hexdigest()


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sorted(rows, key=lambda x: (int(x.get("exit_ts") or 0), int(x.get("entry_ts") or 0), str(x.get("symbol") or "")))
    vals = [float(x.get("net_bps") or 0.0) for x in rows]
    wins = sum(1 for x in vals if x > 0)
    gross_win = sum(x for x in vals if x > 0)
    gross_loss = -sum(x for x in vals if x < 0)
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for x in vals:
        eq += x
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)
    n = len(vals)
    return {
        "closed_T": n,
        "wins": wins,
        "losses": n - wins,
        "win_rate": (wins / n) if n else None,
        "net_pnl_bps": sum(vals),
        "net_expectancy_bps": (sum(vals) / n) if n else None,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
        "drawdown_bps": max_dd,
    }


def run(contract_path: Path, forensic_path: Path, product_path: Path, out: Path) -> dict[str, Any]:
    c = read(contract_path)
    f = read(forensic_path)
    p = read(product_path)

    assert c["state"] == "PREREGISTERED_SHADOW_ONLY"
    assert c["target_lane_id"] == "trend_rider_broad_wr7000"
    assert c["target_stage"] == "G5"
    assert c["causal_axis"] == "ATR_PCT"
    assert c["rule"]["numeric_threshold_sweep"] is False
    assert c["rule"]["outcome_derived_cutoff"] is False
    assert c["parent_policy"]["parent_retune"] is False
    assert c["evidence_policy"]["current_four_w2_rows_consumable"] is False

    assert f["lane_id"] == "trend_rider_broad_wr7000"
    assert f["parent_stage"] == "G5"
    assert f["state"] == "PASS_W2_FORENSIC_COMPLETE"
    assert f["selected_causal_axis"] == "ATR_PCT"
    assert f["causal_policy"]["parent_retune_forbidden"] is True
    assert int(f["w2_product_T"]) == int(p["postlock_closed_T"])
    assert p["policy_retune"] is False and p["threshold_retune"] is False

    boundary = int(c["probe_boundary_ms"])
    ledger = [dict(x) for x in ((f.get("w2") or {}).get("rows") or [])]
    future_parent = [x for x in ledger if int(x.get("signal_ts") or 0) >= boundary]
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for x in future_parent:
        atr_pct = x.get("atr_pct")
        ref = x.get("atr_pct_rolling100_mean")
        cool = x.get("atr_pct_self_normalized_cool")
        if atr_pct is None or ref is None or cool is None:
            raise RuntimeError("MISSING_PREENTRY_ATR_PCT_FEATURE")
        recomputed = float(atr_pct) <= float(ref)
        if bool(cool) != recomputed:
            raise RuntimeError("ATR_PCT_SELF_NORMALIZED_PARITY_FAIL")
        row = {
            k: x.get(k) for k in (
                "symbol", "side", "signal_ts", "entry_ts", "exit_ts", "reason", "net_bps",
                "atr_pct", "atr_pct_rolling100_mean", "atr_pct_self_normalized_cool",
                "chase_atr", "st_gap_atr", "mae_r", "mfe_r", "realized_r", "giveback_r", "hold_bars"
            ) if k in x
        }
        if recomputed:
            accepted.append(row)
        else:
            rejected.append(row)

    parent_metrics = metrics(future_parent)
    shadow_metrics = metrics(accepted)
    min_t = int(c["evidence_policy"]["shadow_min_T_for_causal_read"])
    if not future_parent:
        state = "WAIT_FRESH_G5_PARENT_T_AFTER_SHADOW_BOUNDARY"
    elif not accepted:
        state = "G5_ATR_PCT_SHADOW_ACTIVE_NO_ACCEPTED_T_YET"
    elif len(accepted) < min_t:
        state = "G5_ATR_PCT_SHADOW_ACCUMULATING"
    else:
        state = "G5_ATR_PCT_SHADOW_CAUSAL_READ_READY"

    result: dict[str, Any] = {
        "schema_version": "zel.g5.trendrider.atr_pct.shadow_probe.receipt.v1",
        "state": state,
        "action": "hold",
        "lane_id": "trend_rider_broad_wr7000",
        "stage": "G5_SHADOW_CAUSAL",
        "target_gate": c["target_gate"],
        "probe_boundary_utc": c["probe_boundary_utc"],
        "probe_boundary_ms": boundary,
        "rule": c["rule"],
        "parent_source_path": str(product_path.relative_to(ROOT)),
        "parent_receipt_sha256": p.get("receipt_sha256"),
        "forensic_source_path": str(forensic_path.relative_to(ROOT)),
        "forensic_receipt_sha256": f.get("receipt_sha256"),
        "parent_w2_total_T": int(p["postlock_closed_T"]),
        "parent_future_T_after_probe_boundary": len(future_parent),
        "shadow_accepted_T": len(accepted),
        "shadow_rejected_T": len(rejected),
        "shadow_min_T_for_causal_read": min_t,
        "parent_future_metrics": parent_metrics,
        "shadow_metrics": shadow_metrics,
        "accepted_trades": accepted,
        "rejected_trade_ids": [sha({k: x.get(k) for k in ("symbol", "signal_ts", "entry_ts", "exit_ts")}) for x in rejected],
        "g4_backport_activation_gate_unchanged": True,
        "current_w2_rows_reused_as_shadow_T": 0,
        "parent_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "paid_provider_calls": 0,
        "next": "CONTINUE_PARENT_W2_AND_REFRESH_SHADOW_ON_EACH_FORENSIC_UPDATE",
    }
    result["receipt_sha256"] = sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert metrics([])["closed_T"] == 0
    m = metrics([
        {"exit_ts": 2, "entry_ts": 1, "symbol": "BTC-USDT", "net_bps": 50},
        {"exit_ts": 4, "entry_ts": 3, "symbol": "ETH-USDT", "net_bps": -20},
    ])
    assert m["closed_T"] == 2 and m["net_pnl_bps"] == 30 and m["profit_factor"] == 2.5
    print("PASS_G5_TRENDRIDER_ATR_PCT_SHADOW_PROBE_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    ap.add_argument("--forensic", type=Path, default=DEFAULT_FORENSIC)
    ap.add_argument("--product", type=Path, default=DEFAULT_PRODUCT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.contract, args.forensic, args.product, args.out)
    print(json.dumps({
        "state": r["state"],
        "parent_w2_total_T": r["parent_w2_total_T"],
        "parent_future_T_after_probe_boundary": r["parent_future_T_after_probe_boundary"],
        "shadow_accepted_T": r["shadow_accepted_T"],
        "shadow_net_pnl_bps": r["shadow_metrics"]["net_pnl_bps"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
