#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from backend.research.prep import g5_trendrider_broad30_product_oos_v1 as g5
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_recent_loss_cluster_actionable_v2 as lc2
from backend.research.rebuild import a1_recent_loss_cluster_diagnostic_v1 as lc1
from backend.research.rebuild import a1_top5_matched_exit_attribution_v1 as matched

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "backend/research/prep/g5_trendrider_broad30_product_manifest_v1.json"
PRODUCT = ROOT / "backend/research/prep/g5_trendrider_broad30_product_latest.json"
TOP5 = ROOT / "backend/research/rebuild/a1_top5_latest_only_ssot_v1.json"
MATCHED = ROOT / "backend/research/rebuild/a1_top5_matched_exit_attribution_latest.json"
PRODUCT_REL = "backend/research/prep/g5_trendrider_broad30_product_latest.json"
LANE_ID = "trend_rider_broad_wr7000"
STRATEGY_ID = "trend_rider"
SCHEMA = "zel.g5.trendrider.w2_forensic.v1"


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def receipt_valid(value: Mapping[str, Any]) -> bool:
    supplied = str(value.get("receipt_sha256") or "")
    core = dict(value)
    core.pop("receipt_sha256", None)
    return bool(supplied) and supplied == stable(core)


def top5_product_binding(product: Mapping[str, Any], top5: Mapping[str, Any]) -> dict[str, Any]:
    if product.get("schema_version") != "zel.g5.trendrider_broad30.product_oos.v1":
        raise RuntimeError("G5_PRODUCT_SCHEMA_MISMATCH")
    if product.get("stage") != "G5" or product.get("strategy_id") != STRATEGY_ID or product.get("lane_id") != LANE_ID:
        raise RuntimeError("G5_PRODUCT_IDENTITY_MISMATCH")
    if not receipt_valid(product):
        raise RuntimeError("G5_PRODUCT_RECEIPT_SHA_MISMATCH")
    if product.get("policy_retune") is not False or product.get("threshold_retune") is not False:
        raise RuntimeError("G5_PRODUCT_RETUNE_FORBIDDEN")
    if product.get("old_history_union") is not False:
        raise RuntimeError("G5_PRODUCT_OLD_HISTORY_UNION_FORBIDDEN")
    if product.get("selection_authority") is not False or product.get("promotion_authority") is not False:
        raise RuntimeError("G5_PRODUCT_AUTHORITY_DRIFT")
    if product.get("execution_authority") != "NONE" or product.get("order_authority") != "BLOCKED" or product.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("G5_PRODUCT_EXECUTION_AUTHORITY_DRIFT")
    if int(product.get("protected_mutations") or 0) != 0:
        raise RuntimeError("G5_PRODUCT_PROTECTED_MUTATION")

    if top5.get("schema_version") != "zel.a1.top5.latest_only_ssot.v1" or top5.get("state") != "CURRENT_TOP5_ONLY":
        raise RuntimeError("TOP5_AUTHORITY_DRIFT")
    lane = next((x for x in (top5.get("top5") or []) if isinstance(x, Mapping) and x.get("lane_id") == LANE_ID), None)
    if not isinstance(lane, Mapping):
        raise RuntimeError("TOP5_TRENDRIDER_BROAD_MISSING")
    g5_binding = lane.get("g5")
    if not isinstance(g5_binding, Mapping):
        raise RuntimeError("TOP5_G5_BINDING_MISSING")
    if g5_binding.get("source_path") != PRODUCT_REL:
        raise RuntimeError("TOP5_G5_SOURCE_PATH_MISMATCH")

    product_receipt = str(product.get("receipt_sha256") or "")
    product_input_receipt = str(product.get("source_receipt_sha256") or "")
    if str(g5_binding.get("source_receipt_sha256") or "") != product_receipt:
        raise RuntimeError("G5_PRODUCT_TOP5_RECEIPT_MISMATCH")
    if str(g5_binding.get("source_input_receipt_sha256") or "") != product_input_receipt:
        raise RuntimeError("G5_PRODUCT_TOP5_INPUT_RECEIPT_MISMATCH")
    if int(g5_binding.get("postlock_closed_T") or 0) != int(product.get("postlock_closed_T") or 0):
        raise RuntimeError("G5_PRODUCT_TOP5_T_MISMATCH")

    windows = product.get("windows") or {}
    w2 = (windows.get("W2") or {}).get("metrics") or {}
    w3 = (windows.get("W3") or {}).get("metrics") or {}
    if int(product.get("postlock_closed_T") or 0) != int(w2.get("trades") or 0) + int(w3.get("trades") or 0):
        raise RuntimeError("G5_PRODUCT_WINDOW_T_MISMATCH")

    return {
        "source_path": PRODUCT_REL,
        "source_receipt_sha256": product_receipt,
        "source_input_receipt_sha256": product_input_receipt,
        "postlock_closed_T": int(product.get("postlock_closed_T") or 0),
        "top5_state": top5.get("state"),
    }


def med(values: list[float]) -> float | None:
    return None if not values else float(statistics.median(values))


def mean(rows: list[Mapping[str, Any]], key: str) -> float | None:
    values = [float(x[key]) for x in rows if x.get(key) is not None and math.isfinite(float(x[key]))]
    return None if not values else sum(values) / len(values)


def counts(rows: list[Mapping[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "UNKNOWN")
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


def share(rows: list[Mapping[str, Any]], key: str, value: str) -> float:
    if not rows:
        return 0.0
    return sum(1 for x in rows if str(x.get(key)) == value) / len(rows)


def enrich_preentry(receipt: Mapping[str, Any], rows: list[dict[str, Any]]) -> None:
    for row in rows:
        row["session"] = lc2._frozen_h5_session(int(row.get("signal_ts") or row.get("entry_ts") or 0))
    if rows:
        lc1._trend_enrichment(receipt, rows)


def preentry_candidates(w2: list[dict[str, Any]], reference: list[dict[str, Any]]) -> list[dict[str, Any]]:
    winners = [x for x in reference if float(x.get("net_bps") or 0.0) > 0.0]
    baseline = winners or reference
    candidates: list[dict[str, Any]] = []

    for dim in ("symbol", "side", "session"):
        if not w2:
            continue
        value, n = Counter(str(x.get(dim)) for x in w2).most_common(1)[0]
        wshare = n / len(w2)
        bshare = share(baseline, dim, value)
        candidates.append({
            "axis": dim.upper(),
            "value": value,
            "loss_streak_share": wshare,
            "prior_share": bshare,
            "delta_share": wshare - bshare,
            "diagnostic_score": max(0.0, wshare - bshare) * math.log2(2 + len(w2)),
        })

    for key in ("chase_atr", "st_gap_atr", "atr_pct"):
        a = mean(w2, key)
        b = mean(baseline, key)
        if a is None or b is None:
            continue
        rel = (a - b) / max(abs(b), 1e-9)
        candidates.append({
            "axis": key.upper(),
            "loss_streak_mean": a,
            "reference_mean": b,
            "relative_delta": rel,
            "diagnostic_score": min(3.0, abs(rel)) * math.log2(2 + len(w2)) / 2.0,
        })

    candidates.sort(key=lambda x: (-float(x.get("diagnostic_score") or 0.0), str(x.get("axis") or "")))
    return candidates


def forensic_axis(w2: list[dict[str, Any]], reference: list[dict[str, Any]]) -> tuple[str, str, str, list[dict[str, Any]]]:
    """Use the already-frozen loss-cluster pre-entry materiality policy; no new threshold is learned here."""
    if len(w2) < 4:
        return "INSUFFICIENT_CAUSAL_EVIDENCE", "NONE", "COLLECT_MORE_W2", []

    candidates = preentry_candidates(w2, reference)
    actionable = [x for x in candidates if str(x.get("axis") or "") in lc2.PREENTRY_AXES and lc2._material(x)]
    if actionable:
        root = actionable[0]
        axis = str(root["axis"])
        suffix = f"={root.get('value')}" if axis in {"SYMBOL", "SIDE", "SESSION"} else ""
        return "DETERMINISTIC_FORENSIC_CANDIDATE", axis + suffix, "HANDOFF_G4_CAUSAL", candidates

    return "INSUFFICIENT_CAUSAL_EVIDENCE", "NONE", "COLLECT_MORE_W2_AND_TEST_PREENTRY_LOSS_FILTER", candidates


def run(out: Path) -> dict[str, Any]:
    manifest, product, top5, matched_receipt = read(MANIFEST), read(PRODUCT), read(TOP5), read(MATCHED)
    if manifest.get("state") != "FROZEN_G5_PRODUCT_MANIFEST":
        raise RuntimeError("G5_MANIFEST_NOT_FROZEN")
    parent_binding = top5_product_binding(product, top5)

    with tempfile.TemporaryDirectory(prefix="g5-w2-forensic-") as td:
        replay_path = Path(td) / "current_policy.json"
        receipt = g5.current_policy_replay(out_path=replay_path, boundary_utc=str(manifest["prospective_boundary_utc"]))

    boundary_ms = int(manifest["prospective_boundary_ms"])
    raw0 = sorted(
        [dict(x) for x in (receipt.get("trades") or []) if int(x.get("signal_ts") or 0) > boundary_ms and int(x.get("exit_ts") or 0) > boundary_ms],
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

    broad = next((x for x in (matched_receipt.get("lanes") or []) if x.get("lane") == "trend_rider_broad"), None)
    if not isinstance(broad, dict):
        raise RuntimeError("MATCHED_BROAD_REFERENCE_MISSING")
    reference_rows = [dict(x) for x in (broad.get("rows") or [])]

    enrich_preentry(receipt, w2_rows)
    enrich_preentry(receipt, reference_rows)

    status, axis, route, candidates = forensic_axis(w2_rows, reference_rows)
    w2_summary = matched.summary(w2_rows)
    ref_summary = matched.summary(reference_rows)
    ref_losers = [x for x in reference_rows if float(x.get("net_bps") or 0.0) <= 0.0]
    ref_winners = [x for x in reference_rows if float(x.get("net_bps") or 0.0) > 0.0]

    product_w2_t = int(((product.get("windows") or {}).get("W2") or {}).get("metrics", {}).get("trades") or 0)
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_W2_FORENSIC_COMPLETE" if w2_rows else "WAIT_W2_FORENSIC_T",
        "strategy_id": STRATEGY_ID,
        "lane_id": LANE_ID,
        "parent_stage": "G5",
        "parent_state": product.get("state"),
        "parent_receipt_sha256": product.get("receipt_sha256"),
        "parent_source_receipt_sha256": product.get("source_receipt_sha256"),
        "parent_top5_binding": parent_binding,
        "manifest_sha256": manifest.get("manifest_sha256"),
        "boundary_ms": boundary_ms,
        "boundary_utc": manifest.get("prospective_boundary_utc"),
        "w2_target_T": target,
        "w2_observed_T": len(w2_rows),
        "w2_product_T": product_w2_t,
        "parity": {
            "w2_count_matches_product": len(w2_rows) == product_w2_t,
            "parent_product_matches_top5": True,
            "parent_receipt_matches_top5": str(product.get("receipt_sha256") or "") == str(parent_binding["source_receipt_sha256"]),
            "parent_input_receipt_matches_top5": str(product.get("source_receipt_sha256") or "") == str(parent_binding["source_input_receipt_sha256"]),
            "duplicate": len(raw0) - len(dedup),
            "integrity_defects": list(receipt.get("integrity_defects") or []),
            "leakage_lookahead": int(receipt.get("leakage_lookahead") or 0),
        },
        "w2": {
            "summary": w2_summary,
            "reason_counts": counts(w2_rows, "reason"),
            "side_counts": counts(w2_rows, "side"),
            "symbol_counts": counts(w2_rows, "symbol"),
            "net_bps": sum(float(x["net_bps"]) for x in w2_rows),
            "rows": w2_rows,
        },
        "g4_reference": {
            "T": len(reference_rows),
            "summary": ref_summary,
            "reason_counts": counts(reference_rows, "reason"),
            "side_counts": counts(reference_rows, "side"),
            "symbol_counts": counts(reference_rows, "symbol"),
            "winner_T": len(ref_winners),
            "winner_summary": matched.summary(ref_winners),
            "loser_T": len(ref_losers),
            "loser_summary": matched.summary(ref_losers),
        },
        "preentry_ranked_hypotheses": candidates,
        "preentry_materiality_authority": "backend/research/rebuild/a1_recent_loss_cluster_actionable_v2.py",
        "causal_status": status,
        "selected_causal_axis": axis,
        "recommended_route": route,
        "causal_policy": {
            "four_T_is_forensic_not_terminal": True,
            "post_outcome_axis_not_runtime_entry_filter": True,
            "parent_retune_forbidden": True,
            "parent_W2_continues_to_12T": True,
            "child_requires_fresh_boundary": True,
            "reuse_frozen_preentry_materiality": True,
            "side_or_symbol_concentration_alone_is_not_causal": True,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "action": "hold",
    }
    if not result["parity"]["w2_count_matches_product"]:
        raise RuntimeError("W2_PRODUCT_REPLAY_PARITY_MISMATCH")
    if not result["parity"]["parent_receipt_matches_top5"] or not result["parity"]["parent_input_receipt_matches_top5"]:
        raise RuntimeError("W2_FORENSIC_PARENT_TOP5_LINEAGE_FAIL")
    if result["parity"]["duplicate"] != 0 or result["parity"]["integrity_defects"] or result["parity"]["leakage_lookahead"] != 0:
        raise RuntimeError("W2_FORENSIC_INTEGRITY_FAIL")
    result["receipt_sha256"] = stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    winners = [
        {"net_bps": 100.0, "side": "long", "symbol": "BTC-USDT", "session": "EU", "chase_atr": 1.0, "st_gap_atr": 2.0, "atr_pct": 0.5}
        for _ in range(4)
    ]
    w2 = [
        {"net_bps": -100.0, "side": "long", "symbol": "BTC-USDT", "session": "EU", "chase_atr": 0.2, "st_gap_atr": 2.0, "atr_pct": 0.5}
        for _ in range(4)
    ]
    status, axis, route, ranked = forensic_axis(w2, winners)
    assert status == "DETERMINISTIC_FORENSIC_CANDIDATE"
    assert axis == "CHASE_ATR"
    assert route == "HANDOFF_G4_CAUSAL"
    assert ranked[0]["axis"] == "CHASE_ATR"

    fake_product = {
        "schema_version": "zel.g5.trendrider_broad30.product_oos.v1",
        "stage": "G5",
        "strategy_id": STRATEGY_ID,
        "lane_id": LANE_ID,
        "state": "WAIT_G5_W2_12",
        "source_receipt_sha256": "input-a",
        "postlock_closed_T": 4,
        "windows": {"W2": {"metrics": {"trades": 4}}, "W3": {"metrics": {"trades": 0}}},
        "policy_retune": False,
        "threshold_retune": False,
        "old_history_union": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
    }
    fake_product["receipt_sha256"] = stable(fake_product)
    fake_top5 = {
        "schema_version": "zel.a1.top5.latest_only_ssot.v1",
        "state": "CURRENT_TOP5_ONLY",
        "top5": [{"lane_id": LANE_ID, "g5": {
            "source_path": PRODUCT_REL,
            "source_receipt_sha256": fake_product["receipt_sha256"],
            "source_input_receipt_sha256": "input-a",
            "postlock_closed_T": 4,
        }}],
    }
    binding = top5_product_binding(fake_product, fake_top5)
    assert binding["source_receipt_sha256"] == fake_product["receipt_sha256"]
    bad_top5 = json.loads(json.dumps(fake_top5))
    bad_top5["top5"][0]["g5"]["source_receipt_sha256"] = "stale"
    try:
        top5_product_binding(fake_product, bad_top5)
    except RuntimeError as exc:
        assert str(exc) == "G5_PRODUCT_TOP5_RECEIPT_MISMATCH"
    else:
        raise AssertionError("Top5 lineage mismatch must fail closed")

    print("PASS_G5_TRENDRIDER_W2_FORENSIC_V1_SELF_TEST")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("out/g5_trendrider_w2_forensic_v1.json"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.out)
    print(json.dumps({
        "state": result["state"],
        "w2_T": result["w2_observed_T"],
        "causal_status": result["causal_status"],
        "axis": result["selected_causal_axis"],
        "route": result["recommended_route"],
        "parent_receipt": result["parent_receipt_sha256"],
        "top5_lineage": result["parity"]["parent_product_matches_top5"],
        "top_preentry": (result["preentry_ranked_hypotheses"] or [None])[0],
        "receipt": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
