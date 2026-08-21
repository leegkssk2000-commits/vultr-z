from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
TAXONOMY = ROOT / "backend/research/prep/a3_regime_taxonomy_v1.json"
A3_READY = ROOT / "backend/research/prep/A3_PREP_READY_v1.json"
AUTH = {
    "selection_authority": False, "promotion_authority": False,
    "execution_authority": "NONE", "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED", "protected_mutations": 0, "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def capture_ms(row: Mapping[str, Any]) -> int | None:
    try:
        raw = row.get("snapshot_capture_completed_at_ms")
        return int(raw) if raw is not None else None
    except Exception:
        return None


def classify(row: Mapping[str, Any]) -> dict[str, str]:
    trend = float(row["trend_strength"])
    vol = float(row["realized_vol_pct"])
    spread = float(row["spread_bps"])
    depth = float(row["depth_usdt"])
    funding = float(row["funding_8h_pct"])
    oi = float(row["oi_change_pct"])
    hour = int(row.get("session_utc_hour") or 0)
    return {
        "trend_state": "TREND" if abs(trend) >= 0.35 else "RANGE",
        "vol_state": "HIGH_VOL" if vol >= 1.0 else "LOW_VOL",
        "liquidity_state": "THIN" if spread > 8.0 or depth < 100000.0 else "NORMAL",
        "session_state": "ASIA" if 0 <= hour <= 7 else "EU" if hour <= 15 else "US",
        "funding_oi_state": "CROWDED" if abs(funding) >= 0.03 and abs(oi) >= 3.0 else "NEUTRAL",
    }


def match_context(trade: Mapping[str, Any], rows: list[Mapping[str, Any]], stale_after_ms: int) -> tuple[Mapping[str, Any] | None, str, int | None]:
    symbol = str(trade.get("symbol") or "")
    entry_ts = int(trade.get("entry_ts") or 0)
    eligible: list[tuple[int, Mapping[str, Any]]] = []
    for row in rows:
        if str(row.get("symbol") or "") != symbol:
            continue
        if row.get("valid_for_a3") is not True or row.get("causal_snapshot_eligible") is not True:
            continue
        captured = capture_ms(row)
        if captured is None:
            continue
        try:
            feature_cutoff = int(row.get("bar_feature_cutoff_ts_ms") or 0)
        except Exception:
            continue
        if captured > entry_ts:
            continue
        if feature_cutoff > entry_ts:
            continue
        age = entry_ts - captured
        if age < 0 or age > stale_after_ms:
            continue
        eligible.append((captured, row))
    if not eligible:
        return None, "NO_CAUSAL_CONTEXT_WITHIN_STALENESS", None
    captured, row = max(eligible, key=lambda x: x[0])
    return row, "MATCHED", entry_ts - captured


def _aggregate(joined: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in joined:
        groups[str((row.get("regime") or {}).get(key) or "UNKNOWN")].append(row)
    out: dict[str, Any] = {}
    for name, rows in sorted(groups.items()):
        vals = [float(x["net_bps"]) for x in rows]
        gross = [float(x["gross_bps"]) for x in rows]
        out[name] = {
            "trade_count": len(rows),
            "net_pnl_bps": sum(vals),
            "net_expectancy_bps": sum(vals) / len(vals),
            "gross_expectancy_bps": sum(gross) / len(gross),
            "win_rate": sum(1 for x in vals if x > 0) / len(vals),
        }
    return out


def evaluate(receipt: Mapping[str, Any], a2: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    if a2.get("state") != "PASS_A2_COST_TURNOVER":
        raise RuntimeError("A2_PASS_REQUIRED")
    candidate_id = str(receipt.get("strategy_id") or "")
    if not candidate_id or a2.get("candidate_id") != candidate_id:
        raise RuntimeError("A2_A3_IDENTITY_MISMATCH")
    if a2.get("candidate_receipt_sha256") != receipt.get("receipt_sha256"):
        raise RuntimeError("A2_A3_RECEIPT_LINEAGE_MISMATCH")

    taxonomy = read(TAXONOMY); ready = read(A3_READY)
    if taxonomy.get("stage") != "A3_PREP" or ready.get("state") != "A3_PREP_READY":
        raise RuntimeError("A3_PREP_NOT_READY")
    stale_after_ms = int((taxonomy.get("input_contract") or {}).get("stale_after_ms") or 0)
    if stale_after_ms <= 0:
        raise RuntimeError("A3_STALENESS_NOT_SEALED")

    rows = [x for x in (context.get("rows") or []) if isinstance(x, Mapping)]
    trades = [x for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    joined: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    ages: list[int] = []
    for trade in trades:
        ctx, state, age = match_context(trade, rows, stale_after_ms)
        if ctx is None:
            unmatched.append({"symbol": trade.get("symbol"), "signal_ts": trade.get("signal_ts"), "entry_ts": trade.get("entry_ts"), "reason": state})
            continue
        assert age is not None
        ages.append(age)
        joined.append({
            "symbol": trade.get("symbol"), "signal_ts": trade.get("signal_ts"), "entry_ts": trade.get("entry_ts"), "exit_ts": trade.get("exit_ts"),
            "side": trade.get("side"), "gross_bps": float(trade["gross_bps"]), "net_bps": float(trade["net_bps"]),
            "context_capture_completed_at_ms": capture_ms(ctx), "context_age_ms_at_entry": age,
            "context_row_sha256": stable_sha(ctx), "regime": classify(ctx),
        })

    dimensions = {name: _aggregate(joined, name) for name in ("trend_state", "vol_state", "liquidity_state", "session_state", "funding_oi_state")}
    coverage = {
        "candidate_trade_count": len(trades),
        "matched_trade_count": len(joined),
        "unmatched_trade_count": len(unmatched),
        "matched_fraction": len(joined) / len(trades) if trades else 0.0,
        "context_valid_row_count": sum(1 for x in rows if x.get("valid_for_a3") is True and x.get("causal_snapshot_eligible") is True),
        "context_legacy_ineligible_count": sum(1 for x in rows if x.get("legacy_causal_ineligible") is True),
        "maximum_context_age_ms_observed": max(ages) if ages else None,
        "minimum_context_age_ms_observed": min(ages) if ages else None,
        "sealed_stale_after_ms": stale_after_ms,
    }

    # The existing SSOT deliberately says actual survivor regime performance has
    # not yet been evaluated and contains no sealed sample/performance threshold.
    # Produce the complete causal evidence surface but never manufacture A3 PASS.
    blockers: list[str] = []
    if not joined:
        blockers.append("NO_CAUSALLY_MATCHED_A3_TRADES")
    if unmatched:
        blockers.append("A3_COVERAGE_INCOMPLETE")
    blockers.append("A3_DURABILITY_PASS_CONTRACT_UNSEALED")
    result = {
        "schema_version": "zel.a3_exact25.forward_durability.v1",
        "stage": "A3", "candidate_id": candidate_id,
        "state": "HOLD_A3_DURABILITY_CONTRACT_UNSEALED",
        "candidate_receipt_sha256": receipt.get("receipt_sha256"),
        "a2_receipt_sha256": a2.get("receipt_sha256"), "context_receipt_sha256": context.get("receipt_sha256"),
        "taxonomy_sha256": stable_sha(taxonomy), "a3_ready_sha256": stable_sha(ready),
        "decision_time_semantics": "entry_ts is next-bar open; context capture must complete no later than entry_ts",
        "stale_after_ms": stale_after_ms,
        "coverage": coverage, "joined_trades": joined, "unmatched_trades": unmatched,
        "regime_performance": dimensions,
        "entry_time_regime_owner": None, "owned_regime_net_positive": None,
        "fail_closed_outside_owned_regime": True, "outcome_defined_regime": False,
        "global_durability_pass": False,
        "blockers": blockers,
        "next_required_action": "SEAL_A3_DURABILITY_PASS_CONTRACT_THEN_EVALUATE_WITHOUT_RETUNE",
        "note": "Taxonomy labels are sealed before outcomes. This receipt joins only causal, non-stale context to already-fixed trades and exposes PnL afterward for durability analysis; it does not use PnL to define regimes.",
        **AUTH,
    }
    result["receipt_sha256"] = stable_sha({k:v for k,v in result.items() if k != "receipt_sha256"})
    return result


def self_test() -> int:
    taxonomy = read(TAXONOMY)
    assert int((taxonomy.get("input_contract") or {}).get("stale_after_ms") or 0) == 7_200_000
    assert classify({"trend_strength":0.4,"realized_vol_pct":1.2,"spread_bps":9,"depth_usdt":200000,"funding_8h_pct":0.04,"oi_change_pct":4,"session_utc_hour":17}) == {
        "trend_state":"TREND","vol_state":"HIGH_VOL","liquidity_state":"THIN","session_state":"US","funding_oi_state":"CROWDED"
    }
    print("PASS_A3_EXACT25_FORWARD_DURABILITY_V1_SELF_TEST")
    return 0


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--receipt",type=Path); ap.add_argument("--a2",type=Path); ap.add_argument("--context",type=Path); ap.add_argument("--output",type=Path,default=Path("out/a3_exact25_forward_durability_v1.json")); ap.add_argument("--self-test",action="store_true"); args=ap.parse_args()
    if args.self_test:return self_test()
    if not args.receipt or not args.a2 or not args.context: raise SystemExit("--receipt --a2 --context required")
    result=evaluate(read(args.receipt),read(args.a2),read(args.context)); args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"state":result["state"],"candidate_id":result["candidate_id"],"coverage":result["coverage"],"blockers":result["blockers"],"next":result["next_required_action"],"receipt_sha256":result["receipt_sha256"]},sort_keys=True)); return 0


if __name__=="__main__": raise SystemExit(main())
