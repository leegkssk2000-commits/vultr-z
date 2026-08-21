from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.prep import strategy_synthesis_ablation_v1 as v1

ROOT = Path(__file__).resolve().parents[3]
SSOT = ROOT / "backend/research/prep/strategy_synthesis_material_ssot_v1.json"


def _reference_order(cid: str, rows: Mapping[str, Mapping[str, Any]], grade: Mapping[str, str]) -> list[str]:
    c = rows[cid]
    c_owner = str(c.get("policy_owner") or "")
    c_family = str(c.get("family") or "")
    eligible = [
        rid for rid in rows
        if rid != cid and v1.GRADE_RANK.get(grade.get(rid, "HOLD"), -1) >= v1.GRADE_RANK.get(grade.get(cid, "HOLD"), -1)
    ]
    return sorted(
        eligible,
        key=lambda rid: (
            0 if c_owner and str(rows[rid].get("policy_owner") or "") == c_owner else 1,
            0 if c_family and str(rows[rid].get("family") or "") == c_family else 1,
            rid,
        ),
    )


def evaluate(material: Mapping[str, Any], receipts: Mapping[str, Mapping[str, Any]], ssot: Mapping[str, Any]) -> dict[str, Any]:
    if ssot.get("state") != "PASS_SYNTHESIS_MATERIAL_SSOT_SEALED":
        raise RuntimeError("MATERIAL_SSOT_NOT_SEALED")
    material_rows = {
        str(x.get("strategy_id")): x for x in (material.get("rows") or [])
        if isinstance(x, Mapping) and str(x.get("strategy_id") or "")
    }
    grade = {cid: str(row.get("material_grade") or "HOLD") for cid, row in material_rows.items()}
    gate = ssot["final_discard_gate"]
    upgrade = ssot["upgrade_policy"]
    min_combined_net = float(upgrade["minimum_fixed_combination_net_bps_for_grade_upgrade"])
    if upgrade.get("absolute_combination_economics_required_for_grade_upgrade") is not True:
        raise RuntimeError("ABSOLUTE_COMBINATION_ECONOMICS_GATE_REQUIRED")
    result_rows: list[dict[str, Any]] = []
    evidence_map: dict[str, Any] = {}

    for cid in sorted(receipts):
        if cid not in material_rows or grade[cid] in {"S", "HOLD"}:
            continue
        c_receipt = receipts[cid]
        c_metrics = c_receipt.get("metrics") if isinstance(c_receipt.get("metrics"), Mapping) else {}
        c_gross = c_metrics.get("gross_expectancy_bps")
        standalone_negative = c_gross is not None and float(c_gross) <= 0.0 and int(c_receipt.get("completed_trades") or 0) >= 3

        chosen = None
        chosen_tier = None
        for rid in _reference_order(cid, material_rows, grade):
            if rid not in receipts:
                continue
            ev = v1.pair_evidence(cid, c_receipt, rid, receipts[rid])
            if ev is None:
                continue
            chosen = ev
            same_owner = str(material_rows[cid].get("policy_owner") or "") == str(material_rows[rid].get("policy_owner") or "")
            same_family = str(material_rows[cid].get("family") or "") == str(material_rows[rid].get("family") or "")
            chosen_tier = "SAME_POLICY_OWNER" if same_owner else "SAME_FAMILY" if same_family else "LEXICOGRAPHIC_EQUAL_OR_HIGHER_GRADE"
            break

        if chosen is None:
            result_rows.append({
                "strategy_id": cid, "state": "HOLD_SYNTHESIS_ABLATION_NO_COMPARABLE_REFERENCE",
                "material_grade": grade[cid], "standalone_negative": standalone_negative,
            })
            continue

        marginal = float(chosen["marginal_net_bps"])
        dd_imp = float(chosen["dd_improvement_bps"])
        behavior_cosine = float(chosen["behavior_cosine"])
        combined_net = float(chosen["combined_equal_weight_net_bps"])
        discard = (
            standalone_negative
            and marginal <= float(gate["maximum_marginal_net_bps"])
            and dd_imp <= float(gate["minimum_dd_improvement_bps"])
            and behavior_cosine >= float(gate["minimum_behavior_cosine_for_redundancy"])
        )
        relative_positive = marginal > 0.0 and dd_imp >= 0.0
        grade_upgrade_eligible = relative_positive and combined_net > min_combined_net
        if grade_upgrade_eligible:
            state = "PASS_SYNTHESIS_POSITIVE_MARGINAL"
        elif relative_positive:
            state = "PASS_SYNTHESIS_RELATIVE_ONLY_RETAIN"
        elif discard:
            state = "PASS_DISCARD_ABLATION_EVIDENCE"
        else:
            state = "PASS_SYNTHESIS_RETAIN"
        row = {
            "strategy_id": cid, "state": state, "material_grade": grade[cid],
            "standalone_negative": standalone_negative, **chosen,
            "relative_positive_marginal": relative_positive,
            "grade_upgrade_eligible": grade_upgrade_eligible,
            "absolute_combination_net_gate_bps": min_combined_net,
            "discard_gate_met": discard,
            "reference_selected_by": chosen_tier,
            "reference_selection_uses_realized_pnl": False,
            "reference_selection_uses_behavior_cosine": False,
        }
        row["row_sha256"] = v1.stable_sha(row)
        result_rows.append(row)
        if grade_upgrade_eligible or discard:
            evidence_map[cid] = {
                "marginal_net_bps": marginal,
                "dd_improvement_bps": dd_imp,
                "behavior_cosine": behavior_cosine,
                "combined_equal_weight_net_bps": combined_net,
                "candidate_net_bps": float(chosen["candidate_net_bps"]),
                "reference_net_bps": float(chosen["reference_net_bps"]),
                "grade_upgrade_eligible": grade_upgrade_eligible,
                "reference_id": chosen["reference_id"],
                "reference_selection": chosen_tier,
                "source_row_sha256": row["row_sha256"],
            }

    result = {
        "schema_version": "zel.strategy_synthesis_ablation.v2",
        "state": "PASS_SYNTHESIS_ABLATION_EVALUATED",
        "strategy_count": len(result_rows), "rows": result_rows, "strategies": evidence_map,
        "positive_marginal_count": sum(1 for x in result_rows if x.get("state") == "PASS_SYNTHESIS_POSITIVE_MARGINAL"),
        "relative_only_retain_count": sum(1 for x in result_rows if x.get("state") == "PASS_SYNTHESIS_RELATIVE_ONLY_RETAIN"),
        "discard_ablation_evidence_count": sum(1 for x in result_rows if x.get("discard_gate_met") is True),
        "retain_count": sum(1 for x in result_rows if x.get("state") in {"PASS_SYNTHESIS_RETAIN", "PASS_SYNTHESIS_RELATIVE_ONLY_RETAIN"}),
        "hold_count": sum(1 for x in result_rows if str(x.get("state") or "").startswith("HOLD_")),
        "reference_selection_outcome_independent": True,
        "absolute_combination_economics_required_for_grade_upgrade": True,
        "minimum_fixed_combination_net_bps_for_grade_upgrade": min_combined_net,
        "no_weight_search": True, "no_holdout_retune": True,
        "material_ssot_sha256": v1.stable_sha(ssot), **v1.AUTH,
    }
    result["receipt_sha256"] = v1.stable_sha({k:v for k,v in result.items() if k != "receipt_sha256"})
    return result


def self_test() -> int:
    rows = {
        "a":{"policy_owner":"x.py","family":"x","material_grade":"D"},
        "b":{"policy_owner":"x.py","family":"x","material_grade":"A"},
        "c":{"policy_owner":"y.py","family":"y","material_grade":"A"},
    }
    grade={k:v["material_grade"] for k,v in rows.items()}
    assert _reference_order("a",rows,grade)[0] == "b"
    ssot=v1.read(SSOT)
    assert ssot["upgrade_policy"]["absolute_combination_economics_required_for_grade_upgrade"] is True
    assert float(ssot["upgrade_policy"]["minimum_fixed_combination_net_bps_for_grade_upgrade"]) == 0.0
    print("PASS_STRATEGY_SYNTHESIS_ABLATION_V2_SELF_TEST")
    return 0


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--material",type=Path); ap.add_argument("--receipts-dir",type=Path); ap.add_argument("--output",type=Path,default=Path("out/strategy_synthesis_ablation_v2.json")); ap.add_argument("--self-test",action="store_true"); args=ap.parse_args()
    if args.self_test:return self_test()
    if not args.material or not args.receipts_dir: raise SystemExit("--material and --receipts-dir required")
    result=evaluate(v1.read(args.material),v1.load_receipts(args.receipts_dir),v1.read(SSOT)); args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"state":result["state"],"strategy_count":result["strategy_count"],"positive_marginal":result["positive_marginal_count"],"relative_only_retain":result["relative_only_retain_count"],"discard_evidence":result["discard_ablation_evidence_count"],"retain":result["retain_count"],"hold":result["hold_count"],"receipt_sha256":result["receipt_sha256"]},sort_keys=True)); return 0


if __name__=="__main__": raise SystemExit(main())
