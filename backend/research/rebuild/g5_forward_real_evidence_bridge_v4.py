#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.rebuild import g5_forward_real_evidence_bridge_v1 as base
from backend.research.rebuild import g5_forward_real_evidence_bridge_v3 as v3

ORIGINAL_EVIDENCE_ROW = base.evidence_row
POST_CUTOVER_PATH = v3.POST_CUTOVER_PATH
FIVE_MIN_MS = 300_000


def _top_notional(levels: Sequence[Sequence[Any]], n: int = 5) -> float:
    total = 0.0
    for raw in list(levels)[:n]:
        if len(raw) < 2:
            continue
        px, qty = float(raw[0]), float(raw[1])
        if px > 0 and qty > 0:
            total += px * qty
    return total


def _imbalance(bid_notional: float | None, ask_notional: float | None) -> float | None:
    if bid_notional is None or ask_notional is None:
        return None
    denom = float(bid_notional) + float(ask_notional)
    if denom <= 0:
        return None
    return (float(bid_notional) - float(ask_notional)) / denom


class ExitResearchBingXProvider(base.PublicBingXProvider):
    """Forward-real provider with point-in-time book quantities for exit research.

    These fields are observer-only.  They do not change entry, exit, strategy, order,
    or economic authority.  The original depth/VWAP semantics are preserved.
    """

    def depth(self, symbol: str, reference_notional: float) -> dict[str, Any]:
        requested_at = base.now_ms()
        payload = base.request_json(base.DEPTH_API, {"symbol": symbol, "limit": 50})
        observed_at = base.now_ms()
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        bids = data.get("bids") or []
        asks = data.get("asks") or []
        if not bids or not asks:
            raise RuntimeError(f"DEPTH_EMPTY:{symbol}")
        bid = float(bids[0][0]); ask = float(asks[0][0])
        if bid <= 0 or ask <= bid:
            raise RuntimeError(f"DEPTH_TOP_INVALID:{symbol}:{bid}:{ask}")
        mid = (bid + ask) / 2.0
        buy_vwap = base._depth_vwap(asks, reference_notional)
        sell_vwap = base._depth_vwap(bids, reference_notional)
        top5_bid_notional = _top_notional(bids, 5)
        top5_ask_notional = _top_notional(asks, 5)
        row = {
            "schema_version": "zel.g5.forward_real_depth_snapshot.v2",
            "symbol": symbol,
            "requested_at_ms": requested_at,
            "observed_at_ms": observed_at,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "best_bid_qty": float(bids[0][1]),
            "best_ask_qty": float(asks[0][1]),
            "top5_bid_notional": top5_bid_notional,
            "top5_ask_notional": top5_ask_notional,
            "top5_book_imbalance": _imbalance(top5_bid_notional, top5_ask_notional),
            "buy_vwap": buy_vwap,
            "sell_vwap": sell_vwap,
            "reference_notional_usdt": reference_notional,
            "source_endpoint": "/openApi/swap/v2/quote/depth",
            "point_in_time": True,
            "exit_research_observer_only": True,
        }
        row["snapshot_sha256"] = base.stable(row)
        return row


def directional_path(side: str, entry_mid: float, entry_ts: int, path: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in path.get("rows") or []:
        if not isinstance(raw, Mapping):
            continue
        ts = int(raw["ts_ms"])
        hi, lo, close = float(raw["high"]), float(raw["low"]), float(raw["close"])
        if side == "long":
            fav = max(0.0, hi / entry_mid - 1.0) * 10_000.0
            adv = max(0.0, 1.0 - lo / entry_mid) * 10_000.0
            close_dir = (close / entry_mid - 1.0) * 10_000.0
        elif side == "short":
            fav = max(0.0, 1.0 - lo / entry_mid) * 10_000.0
            adv = max(0.0, hi / entry_mid - 1.0) * 10_000.0
            close_dir = (1.0 - close / entry_mid) * 10_000.0
        else:
            raise RuntimeError(f"SIDE_INVALID:{side}")
        out.append({
            "t_min": max(0.0, (ts - entry_ts) / 60_000.0),
            "favorable_bps": fav,
            "adverse_bps": adv,
            "close_directional_bps": close_dir,
        })
    return out


def path_vol_bps(path: Mapping[str, Any]) -> float | None:
    closes = [float(x["close"]) for x in path.get("rows") or [] if isinstance(x, Mapping) and float(x.get("close") or 0) > 0]
    if len(closes) < 3:
        return None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    return statistics.pstdev(rets) * math.sqrt(len(rets)) * 10_000.0


def exit_research_features(opened: Mapping[str, Any], exit_depth: Mapping[str, Any], path: Mapping[str, Any]) -> dict[str, Any]:
    entry_depth = opened.get("entry_depth") if isinstance(opened.get("entry_depth"), Mapping) else {}
    side = str(opened["side"])
    entry_mid = float(entry_depth["mid"])
    exit_mid = float(exit_depth["mid"])
    entry_ts = int(opened["entry_ts"])
    exit_ts = int(exit_depth["observed_at_ms"])
    points = directional_path(side, entry_mid, entry_ts, path)
    if points:
        max_fav = max(points, key=lambda x: (float(x["favorable_bps"]), -float(x["t_min"])))
        max_adv = max(points, key=lambda x: (float(x["adverse_bps"]), -float(x["t_min"])))
        mfe = float(max_fav["favorable_bps"])
        mae = float(max_adv["adverse_bps"])
        t_mfe = float(max_fav["t_min"])
        t_mae = float(max_adv["t_min"])
    else:
        mfe = mae = t_mfe = t_mae = None
    direction = 1.0 if side == "long" else -1.0
    gross = direction * (exit_mid / entry_mid - 1.0) * 10_000.0
    path_eff = None if not mfe or mfe <= 0 else gross / mfe
    entry_bid = entry_depth.get("top5_bid_notional")
    entry_ask = entry_depth.get("top5_ask_notional")
    exit_bid = exit_depth.get("top5_bid_notional")
    exit_ask = exit_depth.get("top5_ask_notional")
    feature = {
        "schema_version": "zel.g5.exit_research_features.v1",
        "observer_only": True,
        "formal_credit": 0,
        "hold_min": max(0.0, (exit_ts - entry_ts) / 60_000.0),
        "MFE_bps": mfe,
        "MAE_bps": mae,
        "time_to_MFE_min": t_mfe,
        "time_to_MAE_min": t_mae,
        "MFE_before_MAE": (None if t_mfe is None or t_mae is None else t_mfe <= t_mae),
        "path_efficiency": path_eff,
        "realized_path_vol_bps": path_vol_bps(path),
        "entry_book_imbalance": entry_depth.get("top5_book_imbalance", _imbalance(entry_bid, entry_ask)),
        "exit_book_imbalance": exit_depth.get("top5_book_imbalance", _imbalance(exit_bid, exit_ask)),
        "directional_path_5m": points,
        "path_interval_ms": FIVE_MIN_MS,
        "path_sha256": path.get("path_sha256"),
        "post_exit_1h_directional_bps": None,
        "post_exit_4h_directional_bps": None,
        "post_exit_enrichment_pending": True,
    }
    feature["feature_sha256"] = base.stable(feature)
    return feature


def evidence_row_v4(**kwargs: Any) -> dict[str, Any]:
    row = ORIGINAL_EVIDENCE_ROW(**kwargs)
    opened = kwargs["opened"]
    exit_depth = kwargs["exit_depth"]
    path = kwargs["path"]
    row["exit_research_features"] = exit_research_features(opened, exit_depth, path)
    row["exit_research_contract"] = "backend/research/contracts/g5_exit_research_contract_v1.json"
    row["exit_research_formal_credit"] = 0
    row.pop("evidence_row_sha256", None)
    row["evidence_row_sha256"] = base.stable(row)
    return row


def run_process(**kwargs: Any):
    original = base.evidence_row
    base.evidence_row = evidence_row_v4
    try:
        return v3.run_process(**kwargs)
    finally:
        base.evidence_row = original


def self_test() -> int:
    depth = {
        "mid": 100.0,
        "top5_bid_notional": 60.0,
        "top5_ask_notional": 40.0,
        "top5_book_imbalance": 0.2,
    }
    opened = {"side": "long", "entry_ts": 1_000_000, "entry_depth": depth}
    exit_depth = {**depth, "mid": 101.0, "observed_at_ms": 1_600_000}
    path = {"rows": [
        {"ts_ms": 1_000_000, "high": 101.0, "low": 99.5, "close": 100.5},
        {"ts_ms": 1_300_000, "high": 102.0, "low": 100.0, "close": 101.5},
    ], "path_sha256": "x"}
    f = exit_research_features(opened, exit_depth, path)
    assert f["formal_credit"] == 0
    assert round(float(f["MFE_bps"]), 6) == 200.0
    assert round(float(f["MAE_bps"]), 6) == 50.0
    assert f["MFE_before_MAE"] is False
    assert round(float(f["entry_book_imbalance"]), 6) == 0.2
    assert len(f["directional_path_5m"]) == 2
    print("PASS_G5_FORWARD_REAL_EXIT_RESEARCH_V4_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--source-state", default=str(base.STATE_PATH))
    ap.add_argument("--bridge-state", default=str(base.BRIDGE_STATE_PATH))
    ap.add_argument("--bridge-ledger", default=str(base.BRIDGE_LEDGER_PATH))
    ap.add_argument("--canonical-ledger", default=str(base.CANONICAL_LEDGER_PATH))
    ap.add_argument("--out-dir", default="out")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    contract = base.read_json(base.CONTRACT_PATH)
    base.validate_contract(contract)
    post = base.read_json(POST_CUTOVER_PATH)
    view = __import__("backend.research.rebuild.g5_forward_real_evidence_bridge_v2", fromlist=["durable_cutover_view"]).durable_cutover_view(post)
    effective = base.read_json(base.EFFECTIVE_PATH)
    stale = base.read_json(base.STALE_PATH)
    cost = base.read_json(base.COST_PATH)
    source_rows = base.read_jsonl(Path(args.source_state))
    bridge_rows = base.read_jsonl(Path(args.bridge_state))
    bridge_evidence = base.read_jsonl(Path(args.bridge_ledger))
    canonical_evidence = base.read_jsonl(Path(args.canonical_ledger))
    current = base.now_ms()

    bridge_rows, bridge_evidence, canonical_evidence, status = run_process(
        source_rows=source_rows,
        bridge_rows=bridge_rows,
        bridge_evidence=bridge_evidence,
        canonical_evidence=canonical_evidence,
        effective=effective,
        cutover=view,
        stale=stale,
        cost=cost,
        provider=ExitResearchBingXProvider(),
        current_ms=current,
        fee_authority_sha=base.git_blob_sha(base.COST_PATH),
    )
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base.write_jsonl(out / "g5_forward_real_bridge_state_v1.jsonl", bridge_rows)
    base.write_jsonl(out / "g5_forward_real_evidence_ledger_v1.jsonl", bridge_evidence)
    base.write_jsonl(out / "g5_economic_evidence_ledger_v1.jsonl", canonical_evidence)
    status.update({
        "generated_at_ms": current,
        "generated_at_utc": base.iso_ms(current),
        "contract_blob_sha": base.git_blob_sha(base.CONTRACT_PATH),
        "effective_contract_blob_sha": base.git_blob_sha(base.EFFECTIVE_PATH),
        "cost_authority_blob_sha": base.git_blob_sha(base.COST_PATH),
        "post_cutover_authority_blob_sha": base.git_blob_sha(POST_CUTOVER_PATH),
        "post_cutover_authority_ready": view["production_ready"],
        "post_cutover_source_receipt_sha256": view["source_receipt_sha256"],
        "entry_capture_retry_safe": True,
        "exit_research_features_v1": True,
        "exit_research_formal_credit": 0,
    })
    status["receipt_sha256"] = base.stable({k: v for k, v in status.items() if k != "receipt_sha256"})
    base.write_json(out / "g5_forward_real_bridge_latest_v1.json", status)
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
