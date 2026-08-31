#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research.prep import g5_trendrider_broad30_product_oos_v1 as g5
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import trend_policy_batch_v1 as parent
from backend.research.rebuild import trend_rider_transition_freshness_child_policy_v1 as transition
from backend.research.rebuild.policy_kernel_v1 import atr

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/g5_trendrider_preentry_interaction_child_v1.json"
MANIFEST = ROOT / "backend/research/prep/g5_trendrider_broad30_product_manifest_v1.json"
MATCHED = ROOT / "backend/research/rebuild/a1_top5_matched_exit_attribution_latest.json"
PRODUCT = ROOT / "backend/research/prep/g5_trendrider_broad30_product_latest.json"
SCHEMA = "zel.g5.trendrider.preentry_interaction_child.receipt.v1"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def trade_id(row: Mapping[str, Any]) -> str:
    return sha({
        "symbol": row.get("symbol"), "signal_ts": row.get("signal_ts"),
        "entry_ts": row.get("entry_ts"), "exit_ts": row.get("exit_ts"),
        "side": row.get("side"), "intent_sha": row.get("intent_sha"),
    })


def profit_factor(rows: list[Mapping[str, Any]]) -> float | str | None:
    gp = sum(max(0.0, float(x.get("net_bps") or 0.0)) for x in rows)
    gl = sum(max(0.0, -float(x.get("net_bps") or 0.0)) for x in rows)
    if not rows:
        return None
    if gl == 0.0:
        return "INF" if gp > 0.0 else None
    return gp / gl


def metrics(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    pnl = [float(x.get("net_bps") or 0.0) for x in rows]
    wins = sum(1 for x in pnl if x > 0.0)
    equity = peak = dd = 0.0
    for value in pnl:
        equity += value
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return {
        "T": len(rows), "wins": wins, "losses": len(rows) - wins,
        "win_rate": wins / len(rows) if rows else None,
        "net_pnl_bps": sum(pnl),
        "net_expectancy_bps": sum(pnl) / len(rows) if rows else None,
        "profit_factor": profit_factor(rows), "drawdown_bps": dd,
    }


def _valid_contract(c: Mapping[str, Any]) -> None:
    if c.get("schema_version") != "zel.g5.trendrider.preentry_interaction_child.contract.v1":
        raise RuntimeError("CHILD_CONTRACT_SCHEMA_MISMATCH")
    if c.get("stage") != "G5" or c.get("state") != "FROZEN_G5_PREENTRY_INTERACTION_CHILDREN":
        raise RuntimeError("CHILD_CONTRACT_NOT_FROZEN")
    p = c.get("parent") or {}
    if p.get("mutation_forbidden") is not True or p.get("threshold_retune_forbidden") is not True:
        raise RuntimeError("PARENT_FREEZE_REQUIRED")
    q = c.get("parameter_provenance") or {}
    if q.get("numeric_threshold_sweep") is not False or q.get("outcome_optimized_cutoff") is not False or q.get("symbol_sweep") is not False:
        raise RuntimeError("FORBIDDEN_CHILD_TUNING")
    a = c.get("authority") or {}
    if a.get("selection_authority") is not False or a.get("promotion_authority") is not False:
        raise RuntimeError("CHILD_AUTHORITY_DRIFT")
    if a.get("execution_authority") != "NONE" or a.get("order_authority") != "BLOCKED" or a.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("CHILD_EXECUTION_AUTHORITY_DRIFT")
    if a.get("g6_promotion_eligible") is not False:
        raise RuntimeError("G6_MUST_REMAIN_BLOCKED")


def _atr_pct_at(bars: list[dict[str, Any]], idx: int) -> float:
    prefix = bars[: idx + 1]
    a = float(atr(prefix, 14))
    close = float(prefix[-1]["close"])
    return a / max(close, 1e-12) * 100.0


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def enrich(rows: list[dict[str, Any]]) -> None:
    """Attach only features knowable at signal_ts. No exit/future outcome enters any gate."""
    if not rows:
        return
    for symbol in sorted({str(x["symbol"]) for x in rows}):
        bars = [dict(x) for x in ev.fetch_bars(symbol, "1h", 1000)]
        by_ts = {int(b["ts_ms"]): i for i, b in enumerate(bars)}
        symbol_rows = [x for x in rows if str(x["symbol"]) == symbol]
        for row in symbol_rows:
            signal_ts = int(row.get("signal_ts") or 0)
            idx = by_ts.get(signal_ts)
            if idx is None or idx < 64:
                raise RuntimeError(f"PREENTRY_FEATURE_SOURCE_MISSING:{symbol}:{signal_ts}")
            base = parent.compute_trend_rider_feature(bars[: idx + 1], symbol=symbol, now_ts_ms=signal_ts)
            trans = transition.compute_trend_rider_feature(bars[: idx + 1], symbol=symbol, now_ts_ms=signal_ts)
            atr_pct = float(base.atr / max(base.close, 1e-12) * 100.0)

            trailing_start = max(13, idx - 100)
            trailing = [_atr_pct_at(bars, j) for j in range(trailing_start, idx)]
            preceding_end = trailing_start
            preceding_start = max(13, preceding_end - 100)
            preceding = [_atr_pct_at(bars, j) for j in range(preceding_start, preceding_end)]
            trailing_mean = _mean(trailing)
            preceding_mean = _mean(preceding)
            if trailing_mean is None or preceding_mean is None or len(trailing) < 50 or len(preceding) < 50:
                raise RuntimeError(f"INSUFFICIENT_PREENTRY_REGIME_HISTORY:{symbol}:{signal_ts}")

            side = str(row.get("side") or "")
            transition_fresh = bool(
                trans.values.get("long_transition_fresh") if side == "long" else trans.values.get("short_transition_fresh")
            )
            elevated = bool(trailing_mean > preceding_mean)
            cooling = bool(atr_pct <= trailing_mean)
            row.update({
                "atr_pct": atr_pct,
                "atr_pct_trailing100_mean": trailing_mean,
                "atr_pct_preceding100_mean": preceding_mean,
                "vol_regime_ratio": trailing_mean / max(preceding_mean, 1e-12),
                "elevated_volatility_regime": elevated,
                "local_volatility_cooling": cooling,
                "st_gap_atr": float(base.values.get("st_gap_atr")),
                "chase_atr": float(base.values.get("chase_atr")),
                "transition_fresh": transition_fresh,
                "interaction_risk": bool(elevated and cooling),
            })


def child_keep(row: Mapping[str, Any], child_id: str) -> bool:
    risk = bool(row.get("interaction_risk"))
    if child_id == "trend_rider_elevatedvol_cooling_veto_v1":
        return not risk
    if child_id == "trend_rider_elevatedvol_reconfirmation_v1":
        return (not risk) or bool(row.get("transition_fresh"))
    raise RuntimeError(f"UNKNOWN_CHILD:{child_id}")


def select(rows: list[dict[str, Any]], child_id: str) -> list[dict[str, Any]]:
    return [dict(x) for x in rows if child_keep(x, child_id)]


def deterministic_same_count_control(rows: list[dict[str, Any]], block_n: int) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=trade_id)
    blocked = {trade_id(x) for x in ranked[:block_n]}
    return [dict(x) for x in rows if trade_id(x) not in blocked]


def rotated_risk_control(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    ordered = sorted(rows, key=lambda x: (int(x.get("signal_ts") or 0), str(x.get("symbol") or ""), str(x.get("side") or "")))
    flags = [bool(x.get("interaction_risk")) for x in ordered]
    rotated = flags[-1:] + flags[:-1]
    return [dict(row) for row, block in zip(ordered, rotated) if not block]


def development(rows: list[dict[str, Any]], child_id: str) -> dict[str, Any]:
    kept = select(rows, child_id)
    blocked = [x for x in rows if not child_keep(x, child_id)]
    base = metrics(rows)
    cm = metrics(kept)
    blocked_wins = sum(1 for x in blocked if float(x.get("net_bps") or 0.0) > 0.0)
    blocked_losses = len(blocked) - blocked_wins
    elevated_only = [dict(x) for x in rows if not bool(x.get("elevated_volatility_regime"))]
    cooling_only = [dict(x) for x in rows if not bool(x.get("local_volatility_cooling"))]
    transition_only = [dict(x) for x in rows if bool(x.get("transition_fresh"))]
    return {
        "base": base, "child": cm,
        "retention_pct": 100.0 * len(kept) / len(rows) if rows else None,
        "blocked_T": len(blocked), "blocked_wins": blocked_wins, "blocked_losses": blocked_losses,
        "net_delta_bps": float(cm["net_pnl_bps"]) - float(base["net_pnl_bps"]),
        "negative_controls": {
            "same_count_deterministic_veto": metrics(deterministic_same_count_control(rows, len(blocked))),
            "timestamp_rotated_interaction": metrics(rotated_risk_control(rows)),
            "elevated_regime_only_ablation": metrics(elevated_only),
            "local_cooling_only_ablation": metrics(cooling_only),
            "transition_fresh_only_ablation": metrics(transition_only),
        },
    }


def current_parent_receipt() -> dict[str, Any]:
    manifest = read(MANIFEST)
    with tempfile.TemporaryDirectory(prefix="g5-child-parent-") as td:
        return g5.current_policy_replay(out_path=Path(td) / "parent.json", boundary_utc=str(manifest["prospective_boundary_utc"]))


def dedup_post_boundary(receipt: Mapping[str, Any], boundary_ms: int) -> list[dict[str, Any]]:
    raw = sorted(
        [dict(x) for x in (receipt.get("trades") or [])
         if int(x.get("signal_ts") or 0) > boundary_ms and int(x.get("exit_ts") or 0) > boundary_ms],
        key=lambda x: (int(x.get("signal_ts") or 0), str(x.get("symbol") or ""), str(x.get("side") or "")),
    )
    dedup: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    for row in raw:
        dedup[g5.trade_key(row)] = row
    return list(dedup.values())


def compact(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "symbol", "side", "signal_ts", "entry_ts", "exit_ts", "net_bps",
        "atr_pct", "atr_pct_trailing100_mean", "atr_pct_preceding100_mean", "vol_regime_ratio",
        "elevated_volatility_regime", "local_volatility_cooling", "st_gap_atr", "chase_atr",
        "transition_fresh", "interaction_risk",
    )
    return {k: row.get(k) for k in keys}


def _dev_viable(ref: Mapping[str, Any], w2: Mapping[str, Any]) -> bool:
    child = ref.get("child") or {}
    pf = child.get("profit_factor")
    pf_ok = pf == "INF" or (isinstance(pf, (int, float)) and float(pf) > 1.0)
    return bool(
        float(ref.get("retention_pct") or 0.0) >= 50.0
        and float(child.get("net_pnl_bps") or 0.0) > 0.0
        and float(child.get("net_expectancy_bps") or 0.0) > 0.0
        and pf_ok
        and int(w2.get("blocked_losses") or 0) >= 2
    )


def run(out: Path) -> dict[str, Any]:
    contract = read(CONTRACT)
    _valid_contract(contract)
    product = read(PRODUCT)
    if product.get("policy_retune") is not False or product.get("threshold_retune") is not False:
        raise RuntimeError("CURRENT_PARENT_RETUNED")
    if product.get("lane_id") != "trend_rider_broad_wr7000":
        raise RuntimeError("CURRENT_PARENT_LANE_DRIFT")

    receipt = current_parent_receipt()
    manifest = read(MANIFEST)
    parent_post = dedup_post_boundary(receipt, int(manifest["prospective_boundary_ms"]))
    w2_target = int(manifest["windows"]["W2"]["target_closed_trades"])
    w2 = [dict(x) for x in parent_post[:w2_target]]

    matched_receipt = read(MATCHED)
    broad = next((x for x in (matched_receipt.get("lanes") or []) if x.get("lane") == "trend_rider_broad"), None)
    if not isinstance(broad, Mapping):
        raise RuntimeError("G4_REFERENCE_MISSING")
    reference = [dict(x) for x in (broad.get("rows") or [])]

    enrich(w2)
    enrich(reference)

    fresh_boundary = int((contract.get("prospective") or {})["boundary_ms"])
    fresh_parent = dedup_post_boundary(receipt, fresh_boundary)
    enrich(fresh_parent)

    children: dict[str, Any] = {}
    viable_count = 0
    for spec in contract.get("children") or []:
        child_id = str(spec["child_id"])
        ref_dev = development(reference, child_id)
        w2_dev = development(w2, child_id)
        dev_ok = _dev_viable(ref_dev, w2_dev)
        viable_count += int(dev_ok)
        fresh = select(fresh_parent, child_id)
        fm = metrics(fresh)
        pf = fm.get("profit_factor")
        pf_ok = pf == "INF" or (isinstance(pf, (int, float)) and float(pf) > 1.0)
        base12 = bool(
            len(fresh) >= int((contract.get("prospective") or {})["formal_decision_T"])
            and float(fm.get("net_pnl_bps") or 0.0) > 0.0
            and float(fm.get("net_expectancy_bps") or 0.0) > 0.0
            and pf_ok
        )
        children[child_id] = {
            "mechanism": spec["mechanism"],
            "development_viable": dev_ok,
            "historical_reference_development": ref_dev,
            "existing_W2_diagnostic_only": w2_dev,
            "fresh": {
                "boundary_ms": fresh_boundary,
                "boundary_utc": (contract.get("prospective") or {})["boundary_utc"],
                "parent_postboundary_T": len(fresh_parent),
                "child_closed_T": len(fresh), "formal_credit_T": len(fresh),
                "metrics": fm, "trade_ids": [trade_id(x) for x in fresh],
                "base_12T_gate_pass": base12,
                "stress_state": "PENDING_DEDICATED_G5_STRESS_REPLAY" if len(fresh) >= 6 else "WAIT_MIN_6T",
                "terminal_G5_pass": False,
            },
        }

    result: dict[str, Any] = {
        "schema_version": SCHEMA,
        "state": "WAIT_TRUE_FRESH_CHILD_T" if viable_count else "FAIL_DEVELOPMENT_MECHANISM_RESELECT",
        "stage": "G5_CHILD_PROSPECTIVE",
        "strategy_id": "trend_rider", "lane_id": "trend_rider_broad_wr7000",
        "parent": {
            "current_product_receipt_sha256": product.get("receipt_sha256"),
            "current_W2_T": int(((product.get("windows") or {}).get("W2") or {}).get("metrics", {}).get("trades") or 0),
            "current_W2_target_T": int(((product.get("windows") or {}).get("W2") or {}).get("target_T") or 0),
            "mutated": False,
        },
        "causal_hypothesis": "ELEVATED_VOLATILITY_BASELINE_PLUS_LOCAL_VOLATILITY_COOLING_FALSE_CONTINUATION_ENTRY",
        "prior_candidate_falsified": "CURRENT_ATR_ABOVE_TRAILING100_AND_CHASE_COOLING_BLOCKED_0_OF_8_W2",
        "preentry_only": True, "numeric_threshold_sweep": False,
        "outcome_optimized_cutoff": False, "symbol_sweep": False,
        "existing_W2_formal_child_credit": 0,
        "W2_preentry_audit": [compact(x) for x in w2],
        "children": children,
        "integrity": {
            "parent_replay_duplicate_T": len(parent_post) - len({g5.trade_key(x) for x in parent_post}),
            "source_integrity_defects": list(receipt.get("integrity_defects") or []),
            "leakage_lookahead": int(receipt.get("leakage_lookahead") or 0),
            "fresh_boundary_backfill_forbidden": True,
        },
        "selection_authority": False, "promotion_authority": False,
        "execution_authority": "NONE", "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED",
        "g6_promotion_eligible": False, "action": "hold",
        "next": "COLLECT_TRUE_FRESH_CHILD_T_IN_PARALLEL_WITH_FROZEN_PARENT_W2_TO_12T" if viable_count else "RESELECT_PREENTRY_MECHANISM_WITHOUT_NUMERIC_SWEEP",
    }
    if viable_count and any(x["fresh"]["child_closed_T"] >= 6 for x in children.values()):
        result["state"] = "G5_CHILD_DIAGNOSTIC_CHECKPOINT_READY"
    if viable_count and any(x["fresh"]["child_closed_T"] >= 12 for x in children.values()):
        result["state"] = "G5_CHILD_12T_BASE_GATE_READY_STRESS_REQUIRED"
    result["receipt_sha256"] = sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    c = read(CONTRACT)
    _valid_contract(c)
    risk_stale = {"interaction_risk": True, "transition_fresh": False}
    risk_fresh = {"interaction_risk": True, "transition_fresh": True}
    safe = {"interaction_risk": False, "transition_fresh": False}
    assert not child_keep(risk_stale, "trend_rider_elevatedvol_cooling_veto_v1")
    assert not child_keep(risk_fresh, "trend_rider_elevatedvol_cooling_veto_v1")
    assert not child_keep(risk_stale, "trend_rider_elevatedvol_reconfirmation_v1")
    assert child_keep(risk_fresh, "trend_rider_elevatedvol_reconfirmation_v1")
    assert child_keep(safe, "trend_rider_elevatedvol_reconfirmation_v1")
    assert c["prospective"]["existing_W2_8T_formal_credit"] == 0
    assert c["authority"]["g6_promotion_eligible"] is False
    print("PASS_G5_TRENDRIDER_PREENTRY_INTERACTION_CHILD_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/g5_trendrider_preentry_interaction_child_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({
        "state": r["state"], "parent_W2_T": r["parent"]["current_W2_T"],
        "children": {k: {"dev":v["development_viable"],"fresh_T":v["fresh"]["child_closed_T"]} for k,v in r["children"].items()},
        "receipt": r["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
