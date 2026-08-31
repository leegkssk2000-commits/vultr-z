#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research.prep import g5_trendrider_broad30_product_oos_v1 as g5
from backend.research.prep import g5_trendrider_w2_forensic_v1 as forensic
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_top5_matched_exit_attribution_v1 as matched
from backend.research.rebuild import trend_rider_transition_freshness_child_policy_v1 as transition

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


def pf(rows: list[Mapping[str, Any]]) -> float | str | None:
    gp = sum(max(0.0, float(x.get("net_bps") or 0.0)) for x in rows)
    gl = sum(max(0.0, -float(x.get("net_bps") or 0.0)) for x in rows)
    if not rows:
        return None
    if gl == 0.0:
        return "INF" if gp > 0.0 else None
    return gp / gl


def metrics(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    net = [float(x.get("net_bps") or 0.0) for x in rows]
    wins = sum(1 for x in net if x > 0.0)
    peak = 0.0
    equity = 0.0
    dd = 0.0
    for x in net:
        equity += x
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return {
        "T": len(rows),
        "wins": wins,
        "losses": len(rows) - wins,
        "win_rate": (wins / len(rows)) if rows else None,
        "net_pnl_bps": sum(net),
        "net_expectancy_bps": (sum(net) / len(rows)) if rows else None,
        "profit_factor": pf(rows),
        "drawdown_bps": dd,
    }


def _valid_contract(contract: Mapping[str, Any]) -> None:
    if contract.get("schema_version") != "zel.g5.trendrider.preentry_interaction_child.contract.v1":
        raise RuntimeError("CHILD_CONTRACT_SCHEMA_MISMATCH")
    if contract.get("stage") != "G5" or contract.get("state") != "FROZEN_G5_PREENTRY_INTERACTION_CHILDREN":
        raise RuntimeError("CHILD_CONTRACT_NOT_FROZEN")
    parent = contract.get("parent") or {}
    if parent.get("mutation_forbidden") is not True or parent.get("threshold_retune_forbidden") is not True:
        raise RuntimeError("PARENT_FREEZE_REQUIRED")
    prov = contract.get("parameter_provenance") or {}
    if prov.get("numeric_threshold_sweep") is not False or prov.get("outcome_optimized_cutoff") is not False:
        raise RuntimeError("OUTCOME_THRESHOLD_TUNING_FORBIDDEN")
    auth = contract.get("authority") or {}
    if auth.get("selection_authority") is not False or auth.get("promotion_authority") is not False:
        raise RuntimeError("CHILD_AUTHORITY_DRIFT")
    if auth.get("execution_authority") != "NONE" or auth.get("order_authority") != "BLOCKED" or auth.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("CHILD_EXECUTION_AUTHORITY_DRIFT")
    if auth.get("g6_promotion_eligible") is not False:
        raise RuntimeError("G6_MUST_REMAIN_BLOCKED")


def _add_transition_fresh(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    for symbol in sorted({str(x["symbol"]) for x in rows}):
        bars = [dict(x) for x in ev.fetch_bars(symbol, "1h", 1000)]
        by_ts = {int(b["ts_ms"]): i for i, b in enumerate(bars)}
        for row in [x for x in rows if str(x["symbol"]) == symbol]:
            signal_ts = int(row.get("signal_ts") or 0)
            idx = by_ts.get(signal_ts)
            if idx is None or idx < 64:
                row["transition_fresh"] = False
                continue
            f = transition.compute_trend_rider_feature(
                bars[: idx + 1], symbol=symbol, now_ts_ms=signal_ts
            )
            side = str(row.get("side") or "")
            row["transition_fresh"] = bool(
                f.values.get("long_transition_fresh") if side == "long" else f.values.get("short_transition_fresh")
            )


def enrich(rows: list[dict[str, Any]], receipt: Mapping[str, Any]) -> None:
    forensic.enrich_preentry(receipt, rows)
    _add_transition_fresh(rows)
    for row in rows:
        atr_pct = row.get("atr_pct")
        atr_ref = row.get("atr_pct_rolling100_mean")
        chase = row.get("chase_atr")
        prior_chase = row.get("prior_chase_atr")
        high_vol = bool(atr_pct is not None and atr_ref is not None and float(atr_pct) > float(atr_ref))
        weak_impulse = bool(chase is not None and prior_chase is not None and float(chase) <= float(prior_chase))
        row["high_vol_self_normalized"] = high_vol
        row["weak_impulse_self_normalized"] = weak_impulse
        row["interaction_risk"] = bool(high_vol and weak_impulse)


def child_keep(row: Mapping[str, Any], child_id: str) -> bool:
    risk = bool(row.get("interaction_risk"))
    if child_id == "trend_rider_highvol_weakimpulse_veto_v1":
        return not risk
    if child_id == "trend_rider_highvol_reconfirmation_v1":
        return (not risk) or bool(row.get("transition_fresh"))
    raise RuntimeError(f"UNKNOWN_CHILD:{child_id}")


def select(rows: list[dict[str, Any]], child_id: str) -> list[dict[str, Any]]:
    return [dict(x) for x in rows if child_keep(x, child_id)]


def deterministic_same_count_control(rows: list[dict[str, Any]], block_n: int) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=lambda x: sha({
        "symbol": x.get("symbol"), "signal_ts": x.get("signal_ts"), "entry_ts": x.get("entry_ts"), "side": x.get("side")
    }))
    blocked = {sha({"symbol": x.get("symbol"), "signal_ts": x.get("signal_ts"), "entry_ts": x.get("entry_ts"), "side": x.get("side")}) for x in ranked[:block_n]}
    return [dict(x) for x in rows if sha({"symbol": x.get("symbol"), "signal_ts": x.get("signal_ts"), "entry_ts": x.get("entry_ts"), "side": x.get("side")}) not in blocked]


def rotated_interaction_control(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    ordered = sorted(rows, key=lambda x: (int(x.get("signal_ts") or 0), str(x.get("symbol") or ""), str(x.get("side") or "")))
    flags = [bool(x.get("interaction_risk")) for x in ordered]
    rotated = flags[-1:] + flags[:-1]
    return [dict(row) for row, block in zip(ordered, rotated) if not block]


def label_development(rows: list[dict[str, Any]], child_id: str) -> dict[str, Any]:
    kept = select(rows, child_id)
    blocked = [x for x in rows if not child_keep(x, child_id)]
    base = metrics(rows)
    km = metrics(kept)
    blocked_wins = sum(1 for x in blocked if float(x.get("net_bps") or 0.0) > 0.0)
    blocked_losses = len(blocked) - blocked_wins
    random_kept = deterministic_same_count_control(rows, len(blocked))
    rotated_kept = rotated_interaction_control(rows)
    highvol_only = [dict(x) for x in rows if not bool(x.get("high_vol_self_normalized"))]
    weak_only = [dict(x) for x in rows if not bool(x.get("weak_impulse_self_normalized"))]
    return {
        "base": base,
        "child": km,
        "retention_pct": (100.0 * len(kept) / len(rows)) if rows else None,
        "blocked_T": len(blocked),
        "blocked_wins": blocked_wins,
        "blocked_losses": blocked_losses,
        "net_delta_bps": float(km["net_pnl_bps"]) - float(base["net_pnl_bps"]),
        "negative_controls": {
            "same_count_deterministic_veto": metrics(random_kept),
            "timestamp_rotated_interaction": metrics(rotated_kept),
            "highvol_only_ablation": metrics(highvol_only),
            "weak_impulse_only_ablation": metrics(weak_only),
        },
    }


def current_parent_receipt() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="g5-child-parent-") as td:
        return g5.current_policy_replay(out_path=Path(td) / "parent.json", boundary_utc=read(MANIFEST)["prospective_boundary_utc"])


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
    boundary_ms = int(manifest["prospective_boundary_ms"])
    parent_post = dedup_post_boundary(receipt, boundary_ms)
    target = int(manifest["windows"]["W2"]["target_closed_trades"])
    w2 = [dict(x) for x in parent_post[:target]]

    matched_receipt = read(MATCHED)
    broad = next((x for x in (matched_receipt.get("lanes") or []) if x.get("lane") == "trend_rider_broad"), None)
    if not isinstance(broad, Mapping):
        raise RuntimeError("G4_REFERENCE_MISSING")
    reference = [dict(x) for x in (broad.get("rows") or [])]

    enrich(w2, receipt)
    enrich(reference, receipt)

    fresh_boundary = int((contract.get("prospective") or {})["boundary_ms"])
    fresh_parent = dedup_post_boundary(receipt, fresh_boundary)
    enrich(fresh_parent, receipt)

    children: dict[str, Any] = {}
    for spec in contract.get("children") or []:
        child_id = str(spec["child_id"])
        fresh = select(fresh_parent, child_id)
        fm = metrics(fresh)
        base_pass = bool(
            len(fresh) >= int((contract.get("prospective") or {})["formal_decision_T"])
            and float(fm.get("net_pnl_bps") or 0.0) > 0.0
            and float(fm.get("net_expectancy_bps") or 0.0) > 0.0
            and ((fm.get("profit_factor") == "INF") or (isinstance(fm.get("profit_factor"), (int, float)) and float(fm["profit_factor"]) > 1.0))
        )
        children[child_id] = {
            "mechanism": spec["mechanism"],
            "historical_reference_development": label_development(reference, child_id),
            "existing_W2_diagnostic_only": label_development(w2, child_id),
            "fresh": {
                "boundary_ms": fresh_boundary,
                "boundary_utc": (contract.get("prospective") or {})["boundary_utc"],
                "parent_postboundary_T": len(fresh_parent),
                "child_closed_T": len(fresh),
                "metrics": fm,
                "trade_ids": [sha({"symbol":x.get("symbol"),"signal_ts":x.get("signal_ts"),"entry_ts":x.get("entry_ts"),"exit_ts":x.get("exit_ts"),"side":x.get("side"),"intent_sha":x.get("intent_sha")}) for x in fresh],
                "formal_credit_T": len(fresh),
                "base_12T_gate_pass": base_pass,
                "stress_state": "PENDING_DEDICATED_G5_STRESS_REPLAY" if len(fresh) >= 6 else "WAIT_MIN_6T",
                "terminal_G5_pass": False,
            },
        }

    parent_sha_preserved = str(product.get("receipt_sha256") or "") == str(read(PRODUCT).get("receipt_sha256") or "")
    result: dict[str, Any] = {
        "schema_version": SCHEMA,
        "state": "WAIT_TRUE_FRESH_CHILD_T",
        "stage": "G5_CHILD_PROSPECTIVE",
        "strategy_id": "trend_rider",
        "lane_id": "trend_rider_broad_wr7000",
        "parent": {
            "current_product_receipt_sha256": product.get("receipt_sha256"),
            "current_W2_T": int(((product.get("windows") or {}).get("W2") or {}).get("metrics", {}).get("trades") or 0),
            "current_W2_target_T": int(((product.get("windows") or {}).get("W2") or {}).get("target_T") or 0),
            "mutated": False,
            "receipt_preserved_during_evaluation": parent_sha_preserved,
        },
        "causal_hypothesis": "HIGH_VOLATILITY_PLUS_COOLING_DIRECTIONAL_IMPULSE_FALSE_CONTINUATION_ENTRY",
        "preentry_only": True,
        "numeric_threshold_sweep": False,
        "outcome_optimized_cutoff": False,
        "symbol_sweep": False,
        "existing_W2_formal_child_credit": 0,
        "children": children,
        "integrity": {
            "parent_replay_duplicate_T": len(parent_post) - len({g5.trade_key(x) for x in parent_post}),
            "source_integrity_defects": list(receipt.get("integrity_defects") or []),
            "leakage_lookahead": int(receipt.get("leakage_lookahead") or 0),
            "fresh_boundary_backfill_forbidden": True,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "g6_promotion_eligible": False,
        "action": "hold",
        "next": "COLLECT_TRUE_FRESH_CHILD_T_IN_PARALLEL_WITH_FROZEN_PARENT_W2_TO_12T",
    }
    if any((x["fresh"]["child_closed_T"] >= 6) for x in children.values()):
        result["state"] = "G5_CHILD_DIAGNOSTIC_CHECKPOINT_READY"
    if any((x["fresh"]["child_closed_T"] >= 12) for x in children.values()):
        result["state"] = "G5_CHILD_12T_BASE_GATE_READY_STRESS_REQUIRED"
    result["receipt_sha256"] = sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    contract = read(CONTRACT)
    _valid_contract(contract)
    a = {
        "interaction_risk": True, "transition_fresh": False,
        "symbol": "BTC-USDT", "signal_ts": 1, "entry_ts": 2, "side": "long", "net_bps": -100.0,
    }
    b = dict(a); b.update({"signal_ts": 3, "entry_ts": 4, "interaction_risk": False, "net_bps": 50.0})
    c = dict(a); c.update({"signal_ts": 5, "entry_ts": 6, "transition_fresh": True, "net_bps": -20.0})
    rows = [a, b, c]
    self_a = select(rows, "trend_rider_highvol_weakimpulse_veto_v1")
    self_b = select(rows, "trend_rider_highvol_reconfirmation_v1")
    assert len(self_a) == 1
    assert len(self_b) == 2
    assert contract["prospective"]["existing_W2_8T_formal_credit"] == 0
    assert contract["parameter_provenance"]["numeric_threshold_sweep"] is False
    assert contract["authority"]["g6_promotion_eligible"] is False
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
        "state": r["state"],
        "parent_W2_T": r["parent"]["current_W2_T"],
        "children": {k: {"fresh_T": v["fresh"]["child_closed_T"], "base12": v["fresh"]["base_12T_gate_pass"]} for k, v in r["children"].items()},
        "receipt": r["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
