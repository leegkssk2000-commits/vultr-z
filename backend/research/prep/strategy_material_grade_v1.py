from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
INVENTORY = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
SSOT = ROOT / "backend/research/prep/strategy_synthesis_material_ssot_v1.json"

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}

A3_PASS = {"PASS_A3_GLOBAL_DURABILITY", "PASS_A3_EXPLICIT_REGIME_OWNER"}
FINALIST = {"A1_FINALIST_PARKED", "A1_SURVIVOR"}
DATA_HOLD = {"A1_DATA_BLOCKED", "HOLD_USER_AUTHORITY"}
SPARSE = {"A1_SPARSE_EVENT_FUTILITY"}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def family_from_owner(owner: str) -> str:
    name = Path(owner).stem.lower()
    for token in ("microstructure", "reversal_range", "indicator_core", "breakout", "trend", "final_four", "vwap_bb"):
        if token in name:
            return token
    return name or "unknown"


def _a3_index(raw: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    if not raw:
        return {}
    if raw.get("candidate_id"):
        return {str(raw["candidate_id"]): raw}
    out: dict[str, Mapping[str, Any]] = {}
    for key in ("strategies", "rows", "candidates"):
        block = raw.get(key)
        if isinstance(block, Mapping):
            for cid, row in block.items():
                if isinstance(row, Mapping):
                    out[str(cid)] = row
        elif isinstance(block, list):
            for row in block:
                if isinstance(row, Mapping) and row.get("candidate_id"):
                    out[str(row["candidate_id"])] = row
    return out


def _synth_index(raw: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    if not raw:
        return {}
    block = raw.get("strategies") if isinstance(raw.get("strategies"), Mapping) else raw
    return {str(k): v for k, v in block.items() if isinstance(v, Mapping)}


def _base_classification(row: Mapping[str, Any], a3: Mapping[str, Any] | None) -> tuple[str, str, str, str]:
    status = str(row.get("status") or "")
    trades = int(row.get("completed_trades") or 0)
    gross = finite(row.get("gross_expectancy_bps"))
    net = finite(row.get("net_expectancy_bps"))
    pf = finite(row.get("profit_factor"))
    payoff = finite(row.get("payoff"))
    a3_state = str((a3 or {}).get("state") or "")

    if a3_state in A3_PASS:
        return "S", "SYNTHESIS_CORE", "NONE_A3_VERIFIED", "S"
    if status in DATA_HOLD:
        return "HOLD", "HOLD_DATA", "SOURCE_COMPLETION_ONLY", "C"
    if status in FINALIST and net is not None and net > 0 and (pf is None or pf >= 1.0) and (payoff is None or payoff >= 1.0):
        return "A", "A3_PROMOTION_QUEUE", "CAUSAL_CONTROL_HARDENING", "S"
    if net is not None and net > 0:
        return "B", "SYNTHESIS_UPGRADE", "CAUSAL_CONTROL_HARDENING", "A"
    if gross is not None and gross > 0:
        return "B", "SYNTHESIS_UPGRADE", "COST_TURNOVER_COMPRESSION", "A"
    if status in SPARSE or trades < 3:
        return "C", "SYNTHESIS_EXPERIMENTAL", "STRUCTURAL_EVENT_DENSITY_REDESIGN", "B"
    if gross is not None and gross <= 0 and trades >= 10:
        return "D", "DISCARD_PENDING_ABLATION", "MECHANISM_RECOMBINATION_ONLY", "B"
    return "C", "SYNTHESIS_EXPERIMENTAL", "DISTINCT_MECHANISM_RECOMBINATION", "B"


def _synthesis_override(
    grade: str,
    disposition: str,
    standalone_negative: bool,
    evidence: Mapping[str, Any] | None,
    ssot: Mapping[str, Any],
) -> tuple[str, str, str]:
    if not evidence:
        return grade, disposition, "UNTESTED_MARGINAL_CONTRIBUTION"
    marginal = finite(evidence.get("marginal_net_bps"))
    dd_improvement = finite(evidence.get("dd_improvement_bps"))
    cosine = finite(evidence.get("behavior_cosine"))
    if marginal is not None and marginal > 0 and (dd_improvement is None or dd_improvement >= 0):
        order = ["D", "C", "B", "A"]
        if grade in order:
            grade = order[min(order.index(grade) + 1, len(order) - 1)]
        if grade == "HOLD":
            grade = "C"
        return grade, "SYNTHESIS_CORE", "PROVEN_POSITIVE_MARGINAL_CONTRIBUTION"
    gate = ssot["final_discard_gate"]
    if (
        standalone_negative
        and marginal is not None and marginal <= float(gate["maximum_marginal_net_bps"])
        and dd_improvement is not None and dd_improvement <= float(gate["minimum_dd_improvement_bps"])
        and cosine is not None and cosine >= float(gate["minimum_behavior_cosine_for_redundancy"])
    ):
        return "D", "DISCARD_CONFIRMED", "PROVEN_REDUNDANT_NONPOSITIVE_MARGINAL"
    return grade, disposition, "INCONCLUSIVE_MARGINAL_CONTRIBUTION"


def _quality_components(row: Mapping[str, Any]) -> dict[str, Any]:
    trades = int(row.get("completed_trades") or 0)
    gross = finite(row.get("gross_expectancy_bps"))
    net = finite(row.get("net_expectancy_bps"))
    pnl = finite(row.get("net_pnl_bps"))
    dd = finite(row.get("drawdown_bps"))
    pf = finite(row.get("profit_factor"))
    payoff = finite(row.get("payoff"))
    defects = list(row.get("integrity_defects") or [])
    return {
        "completed_trades": trades,
        "gross_expectancy_bps": gross,
        "net_expectancy_bps": net,
        "net_pnl_bps": pnl,
        "drawdown_bps": dd,
        "profit_factor": pf,
        "payoff": payoff,
        "win_rate": finite(row.get("win_rate")),
        "verified_pretrade_cost_bps": finite(row.get("verified_pretrade_cost_bps")),
        "integrity_defect_count": len(defects),
        "positive_gross": gross is not None and gross > 0,
        "positive_net": net is not None and net > 0,
        "risk_efficiency_net_pnl_over_dd": (pnl / dd) if pnl is not None and dd is not None and dd > 0 else None,
    }


def evaluate(
    ledger: Mapping[str, Any],
    inventory: Mapping[str, Any],
    ssot: Mapping[str, Any],
    *,
    a3_raw: Mapping[str, Any] | None = None,
    synthesis_raw: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if int(ledger.get("done_count") or 0) != 25 or len(ledger.get("strategy_order") or []) != 25:
        raise RuntimeError("EXACT25_COMPLETE_LEDGER_REQUIRED")
    if int(inventory.get("identity_count") or 0) != 25 or inventory.get("r3_gate") != "PASS":
        raise RuntimeError("STRUCTURAL_INVENTORY_REQUIRED")
    if ssot.get("state") != "PASS_SYNTHESIS_MATERIAL_SSOT_SEALED":
        raise RuntimeError("MATERIAL_SSOT_NOT_SEALED")

    a3 = _a3_index(a3_raw)
    synth = _synth_index(synthesis_raw)
    strategies = ledger.get("strategies") or {}
    structural = inventory.get("strategies") or {}
    family_counts = Counter(family_from_owner(str((structural.get(cid) or {}).get("policy_owner") or "")) for cid in ledger["strategy_order"])
    rows: list[dict[str, Any]] = []

    for cid in ledger["strategy_order"]:
        base = strategies.get(cid) or {}
        inv = structural.get(cid) or {}
        family = family_from_owner(str(inv.get("policy_owner") or ""))
        grade, disposition, upgrade_axis, target_grade = _base_classification(base, a3.get(cid))
        comp = _quality_components(base)
        standalone_negative = bool(
            comp["gross_expectancy_bps"] is not None
            and comp["gross_expectancy_bps"] <= 0
            and comp["completed_trades"] >= 3
        )
        grade, disposition, synth_state = _synthesis_override(grade, disposition, standalone_negative, synth.get(cid), ssot)
        if grade == "S":
            target_grade = "S"
        row = {
            "strategy_id": cid,
            "family": family,
            "family_population": int(family_counts[family]),
            "policy_owner": inv.get("policy_owner"),
            "evidence_packet": inv.get("evidence_packet"),
            "a1_status": base.get("status"),
            "a3_state": (a3.get(cid) or {}).get("state"),
            "material_grade": grade,
            "material_disposition": disposition,
            "synthesis_value_state": synth_state,
            "upgrade_axis": upgrade_axis,
            "target_grade": target_grade,
            "upgrade_round_limit": int(ssot["upgrade_policy"]["max_rounds_per_material"]),
            "one_axis_per_round": True,
            "structural_diversity_prior": 1.0 / max(1, int(family_counts[family])),
            "quality": comp,
            "final_discard_evidence_present": cid in synth and disposition == "DISCARD_CONFIRMED",
            "promotion_authority_from_material_grade": False,
        }
        row["row_sha256"] = stable_sha(row)
        rows.append(row)

    buckets = {name: [x["strategy_id"] for x in rows if x["material_disposition"] == name] for name in ssot["dispositions"]}
    grades = {g: [x["strategy_id"] for x in rows if x["material_grade"] == g] for g in ssot["grades"]}
    upgrade_queue = [
        {
            "strategy_id": x["strategy_id"],
            "from_grade": x["material_grade"],
            "target_grade": x["target_grade"],
            "axis": x["upgrade_axis"],
            "max_rounds": x["upgrade_round_limit"],
            "constraints": {
                "one_changed_axis": True,
                "no_threshold_loosen_to_create_trades": True,
                "no_holdout_retune": True,
                "no_best_horizon_selection": True,
                "dedup_cosine_threshold": float(ssot["upgrade_policy"]["dedup_cosine_threshold"]),
            },
        }
        for x in rows
        if x["material_grade"] not in {"S", "HOLD"} and x["material_disposition"] != "DISCARD_CONFIRMED"
    ]
    result = {
        "schema_version": "zel.strategy_material_grade.v1",
        "state": "PASS_STRATEGY_MATERIALS_CLASSIFIED",
        "strategy_count": len(rows),
        "all_exact25_accounted": len(rows) == 25 and len({x["strategy_id"] for x in rows}) == 25,
        "rows": rows,
        "buckets": buckets,
        "grades": grades,
        "upgrade_queue": upgrade_queue,
        "family_counts": dict(sorted(family_counts.items())),
        "final_discard_count": len(buckets.get("DISCARD_CONFIRMED") or []),
        "provisional_discard_count": len(buckets.get("DISCARD_PENDING_ABLATION") or []),
        "note": "Material grade is a synthesis/research priority only. It never grants A1/A2/A3 or Survivor authority. Final discard is impossible without explicit marginal synthesis ablation evidence.",
        **AUTH,
    }
    result["receipt_sha256"] = stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    return result


def self_test() -> int:
    ssot = read(SSOT)
    inv = {"identity_count": 25, "r3_gate": "PASS", "strategies": {f"s{i}": {"policy_owner": "trend_policy_batch_v1.py", "evidence_packet": "x"} for i in range(25)}}
    rows = {}
    order = []
    for i in range(25):
        cid = f"s{i}"; order.append(cid)
        rows[cid] = {"status": "A1_ECONOMIC_FAIL", "completed_trades": 20, "gross_expectancy_bps": -1.0, "net_expectancy_bps": -15.0, "net_pnl_bps": -300.0, "drawdown_bps": 300.0, "profit_factor": 0.5, "payoff": 0.8, "integrity_defects": [], "verified_pretrade_cost_bps": 14.0}
    ledger = {"done_count": 25, "strategy_order": order, "strategies": rows}
    r = evaluate(ledger, inv, ssot)
    assert r["strategy_count"] == 25 and r["all_exact25_accounted"] is True
    assert len(r["buckets"]["DISCARD_PENDING_ABLATION"]) == 25
    ev = {"s0": {"marginal_net_bps": -1.0, "dd_improvement_bps": 0.0, "behavior_cosine": 0.9}}
    r2 = evaluate(ledger, inv, ssot, synthesis_raw=ev)
    assert "s0" in r2["buckets"]["DISCARD_CONFIRMED"]
    a3 = {"candidate_id": "s1", "state": "PASS_A3_GLOBAL_DURABILITY"}
    r3 = evaluate(ledger, inv, ssot, a3_raw=a3)
    assert next(x for x in r3["rows"] if x["strategy_id"] == "s1")["material_grade"] == "S"
    print("PASS_STRATEGY_MATERIAL_GRADE_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", type=Path, default=LEDGER)
    ap.add_argument("--inventory", type=Path, default=INVENTORY)
    ap.add_argument("--ssot", type=Path, default=SSOT)
    ap.add_argument("--a3", type=Path)
    ap.add_argument("--synthesis-evidence", type=Path)
    ap.add_argument("--output", type=Path, default=Path("out/strategy_material_grade_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = evaluate(
        read(args.ledger), read(args.inventory), read(args.ssot),
        a3_raw=read(args.a3) if args.a3 else None,
        synthesis_raw=read(args.synthesis_evidence) if args.synthesis_evidence else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "strategy_count": result["strategy_count"],
        "grades": {k: len(v) for k, v in result["grades"].items()},
        "buckets": {k: len(v) for k, v in result["buckets"].items()},
        "upgrade_queue": len(result["upgrade_queue"]),
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
