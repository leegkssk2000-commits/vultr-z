from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
SSOT = ROOT / "backend/research/prep/strategy_synthesis_material_ssot_v1.json"
AUTH = {
    "selection_authority": False, "promotion_authority": False,
    "execution_authority": "NONE", "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED", "exchange_order_submitted": False,
    "protected_mutations": 0, "action": "hold",
}
GRADE_RANK = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1, "HOLD": 0}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def _trades(receipt: Mapping[str, Any], start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    return [
        dict(x) for x in (receipt.get("trades") or [])
        if isinstance(x, Mapping) and start_ms <= int(x.get("entry_ts") or 0) <= end_ms
    ]


def _vector(trades: list[Mapping[str, Any]]) -> dict[tuple[str, int], float]:
    out: dict[tuple[str, int], float] = {}
    for t in trades:
        key = (str(t.get("symbol") or ""), int(t.get("entry_ts") or 0))
        out[key] = out.get(key, 0.0) + float(t.get("net_bps") or 0.0)
    return out


def cosine(a: Mapping[tuple[str, int], float], b: Mapping[tuple[str, int], float]) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 0.0
    dot = sum(float(a.get(k, 0.0)) * float(b.get(k, 0.0)) for k in keys)
    na = math.sqrt(sum(float(a.get(k, 0.0)) ** 2 for k in keys))
    nb = math.sqrt(sum(float(b.get(k, 0.0)) ** 2 for k in keys))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def max_drawdown(events: Mapping[tuple[str, int], float]) -> float:
    # Sort by entry timestamp then symbol. This is a research equity path using
    # realized trade net-bps assigned to its frozen entry key; no reordering by PnL.
    equity = peak = 0.0
    max_dd = 0.0
    for key in sorted(events, key=lambda k: (k[1], k[0])):
        equity += float(events[key])
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def pair_evidence(candidate_id: str, candidate: Mapping[str, Any], reference_id: str, reference: Mapping[str, Any]) -> dict[str, Any] | None:
    c_trades_all = [x for x in (candidate.get("trades") or []) if isinstance(x, Mapping)]
    r_trades_all = [x for x in (reference.get("trades") or []) if isinstance(x, Mapping)]
    if not c_trades_all or not r_trades_all:
        return None
    c_start = min(int(x["entry_ts"]) for x in c_trades_all); c_end = max(int(x["entry_ts"]) for x in c_trades_all)
    r_start = min(int(x["entry_ts"]) for x in r_trades_all); r_end = max(int(x["entry_ts"]) for x in r_trades_all)
    start = max(c_start, r_start); end = min(c_end, r_end)
    if end < start:
        return None
    ct = _trades(candidate, start, end); rt = _trades(reference, start, end)
    if not ct or not rt:
        return None
    cv, rv = _vector(ct), _vector(rt)
    behavior_cosine = cosine(cv, rv)
    keys = set(cv) | set(rv)
    combined = {k: 0.5 * float(rv.get(k, 0.0)) + 0.5 * float(cv.get(k, 0.0)) for k in keys}
    ref_net = sum(rv.values()); cand_net = sum(cv.values()); combined_net = sum(combined.values())
    ref_dd = max_drawdown(rv); combined_dd = max_drawdown(combined)
    return {
        "candidate_id": candidate_id, "reference_id": reference_id,
        "common_window_start_entry_ts": start, "common_window_end_entry_ts": end,
        "candidate_trade_count": len(ct), "reference_trade_count": len(rt),
        "candidate_net_bps": cand_net, "reference_net_bps": ref_net,
        "combined_equal_weight_net_bps": combined_net,
        "marginal_net_bps": combined_net - ref_net,
        "reference_drawdown_bps": ref_dd, "combined_equal_weight_drawdown_bps": combined_dd,
        "dd_improvement_bps": ref_dd - combined_dd,
        "behavior_cosine": behavior_cosine,
        "behavior_vector": "union of exact frozen (symbol,entry_ts) net_bps keys over common prospective window",
        "combination_rule": "50% fixed reference sleeve + 50% fixed candidate sleeve; no parameter/weight search",
    }


def evaluate(material: Mapping[str, Any], receipts: Mapping[str, Mapping[str, Any]], ssot: Mapping[str, Any]) -> dict[str, Any]:
    if ssot.get("state") != "PASS_SYNTHESIS_MATERIAL_SSOT_SEALED":
        raise RuntimeError("MATERIAL_SSOT_NOT_SEALED")
    rows = [x for x in (material.get("rows") or []) if isinstance(x, Mapping)]
    grade = {str(x.get("strategy_id")): str(x.get("material_grade")) for x in rows}
    result_rows: list[dict[str, Any]] = []
    evidence_map: dict[str, Any] = {}
    gate = ssot["final_discard_gate"]
    cosine_gate = float(gate["minimum_behavior_cosine_for_redundancy"])

    for cid, c_receipt in sorted(receipts.items()):
        if cid not in grade or grade[cid] in {"S", "HOLD"}:
            continue
        c_metrics = c_receipt.get("metrics") if isinstance(c_receipt.get("metrics"), Mapping) else {}
        c_gross = c_metrics.get("gross_expectancy_bps")
        standalone_negative = c_gross is not None and float(c_gross) <= 0.0 and int(c_receipt.get("completed_trades") or 0) >= 3
        candidates: list[dict[str, Any]] = []
        for rid, r_receipt in receipts.items():
            if rid == cid or rid not in grade:
                continue
            # Reference selection is behavior-only among equal/higher-grade material;
            # never choose the reference by PnL or holdout outcome.
            if GRADE_RANK.get(grade[rid], -1) < GRADE_RANK.get(grade[cid], -1):
                continue
            ev = pair_evidence(cid, c_receipt, rid, r_receipt)
            if ev is not None:
                candidates.append(ev)
        candidates.sort(key=lambda x: (-abs(float(x["behavior_cosine"])), str(x["reference_id"])))
        best = candidates[0] if candidates else None
        if best is None:
            row = {"strategy_id": cid, "state": "HOLD_SYNTHESIS_ABLATION_NO_COMPARABLE_REFERENCE", "material_grade": grade[cid], "standalone_negative": standalone_negative}
            result_rows.append(row); continue
        marginal = float(best["marginal_net_bps"]); dd_imp = float(best["dd_improvement_bps"]); cos = float(best["behavior_cosine"])
        discard = (
            standalone_negative
            and marginal <= float(gate["maximum_marginal_net_bps"])
            and dd_imp <= float(gate["minimum_dd_improvement_bps"])
            and cos >= cosine_gate
        )
        positive_marginal = marginal > 0.0 and dd_imp >= 0.0
        state = "PASS_SYNTHESIS_POSITIVE_MARGINAL" if positive_marginal else "PASS_DISCARD_ABLATION_EVIDENCE" if discard else "PASS_SYNTHESIS_RETAIN"
        row = {
            "strategy_id": cid, "state": state, "material_grade": grade[cid],
            "standalone_negative": standalone_negative, **best,
            "discard_gate_met": discard,
            "reference_selected_by": "MAX_ABSOLUTE_BEHAVIOR_COSINE_ONLY_NOT_PNL",
        }
        row["row_sha256"] = stable_sha(row)
        result_rows.append(row)
        evidence_map[cid] = {
            "marginal_net_bps": marginal,
            "dd_improvement_bps": dd_imp,
            "behavior_cosine": cos,
            "reference_id": best["reference_id"],
            "source_row_sha256": row["row_sha256"],
        }

    result = {
        "schema_version": "zel.strategy_synthesis_ablation.v1",
        "state": "PASS_SYNTHESIS_ABLATION_EVALUATED",
        "strategy_count": len(result_rows), "rows": result_rows,
        "strategies": evidence_map,
        "positive_marginal_count": sum(1 for x in result_rows if x.get("state") == "PASS_SYNTHESIS_POSITIVE_MARGINAL"),
        "discard_ablation_evidence_count": sum(1 for x in result_rows if x.get("discard_gate_met") is True),
        "retain_count": sum(1 for x in result_rows if x.get("state") == "PASS_SYNTHESIS_RETAIN"),
        "hold_count": sum(1 for x in result_rows if str(x.get("state") or "").startswith("HOLD_")),
        "no_weight_search": True, "no_holdout_retune": True,
        "material_ssot_sha256": stable_sha(ssot), **AUTH,
    }
    result["receipt_sha256"] = stable_sha({k:v for k,v in result.items() if k != "receipt_sha256"})
    return result


def load_receipts(directory: Path) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        try: row = read(path)
        except Exception: continue
        cid = str(row.get("strategy_id") or "")
        if cid and isinstance(row.get("trades"), list):
            out[cid] = row
    return out


def self_test() -> int:
    a={"trades":[{"symbol":"BTC-USDT","entry_ts":1,"net_bps":10},{"symbol":"BTC-USDT","entry_ts":2,"net_bps":-5}]}
    b={"trades":[{"symbol":"BTC-USDT","entry_ts":1,"net_bps":9},{"symbol":"BTC-USDT","entry_ts":2,"net_bps":-4}]}
    ev=pair_evidence("a",a,"b",b); assert ev is not None and ev["behavior_cosine"] > 0.99
    assert read(SSOT)["upgrade_policy"]["dedup_cosine_threshold"] == 0.85
    print("PASS_STRATEGY_SYNTHESIS_ABLATION_V1_SELF_TEST")
    return 0


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--material",type=Path); ap.add_argument("--receipts-dir",type=Path); ap.add_argument("--output",type=Path,default=Path("out/strategy_synthesis_ablation_v1.json")); ap.add_argument("--self-test",action="store_true"); args=ap.parse_args()
    if args.self_test:return self_test()
    if not args.material or not args.receipts_dir: raise SystemExit("--material and --receipts-dir required")
    result=evaluate(read(args.material),load_receipts(args.receipts_dir),read(SSOT)); args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"state":result["state"],"strategy_count":result["strategy_count"],"positive_marginal":result["positive_marginal_count"],"discard_evidence":result["discard_ablation_evidence_count"],"retain":result["retain_count"],"hold":result["hold_count"],"receipt_sha256":result["receipt_sha256"]},sort_keys=True)); return 0


if __name__=="__main__": raise SystemExit(main())
