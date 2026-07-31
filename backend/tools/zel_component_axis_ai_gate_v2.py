from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.tools import zel_component_autonomy_v2 as core

SAFE = {"research_only": True, "promotion_authority": False, "protected_mutations": 0, "execution_allowed": False, "execution_authority": "NONE", "order_authority": "BLOCKED", "runtime_bound": False}


def read(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"OBJECT_REQUIRED:{path}")
    return value


def write(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def candidate(result: Mapping[str, Any], axis: str) -> tuple[Any, Mapping[str, Any], Mapping[str, Any]]:
    modules = result["module_results"]
    if axis == "BOT_POLICY":
        profiles = modules["bots"]["best_by_role"]
        rows = [row for row in profiles.values() if (row.get("evidence") or {}).get("material")]
        if not rows: raise ValueError("BOT_AXIS_NOT_MATERIAL")
        best = max(rows, key=lambda row: core.number(row["evidence"]["deltas"]["net"]))
        return profiles, best["stats"], best["evidence"]
    if axis == "TEAM_POLICY":
        best = modules["teams"]["best"]
        return {k:v for k,v in best.items() if k not in {"stats","evidence"}}, best["stats"], best["evidence"]
    if axis == "SKILL_PROFILE":
        best = modules["skills"]["best"]
        if best.get("selection_eligible") is not True: raise ValueError("SKILL_NOT_SELECTION_ELIGIBLE")
        return {k:v for k,v in best.items() if k not in {"stats","evidence"}}, best["stats"], best["evidence"]
    if axis == "ADVISOR_PROFILE":
        selected = []
        configuration = {}
        for role in ("ZBOT","ZICO","LICO"):
            best = modules["advisors"][role]["best"]
            if (best.get("evidence") or {}).get("material"):
                configuration[role] = {k:v for k,v in best.items() if k not in {"stats","evidence"}}
                selected.append(best)
        if not selected: raise ValueError("ADVISOR_AXIS_NOT_MATERIAL")
        best = max(selected, key=lambda row: core.number(row["evidence"]["deltas"]["net"]))
        return configuration, best["stats"], best["evidence"]
    raise ValueError(f"AXIS_INVALID:{axis}")


def prepare(result: Mapping[str, Any], out: Path) -> dict[str, Any]:
    active=[]; skipped={}
    for axis, eligible in (result.get("axis_review_eligibility") or {}).items():
        if not eligible:
            skipped[axis]="SKIP_NOT_MATERIAL_OR_LOW_SAMPLE"; continue
        configuration, stats, proof = candidate(result, axis)
        delta = proof.get("deltas") or {}
        evidence = {
            "material": bool(proof.get("material")), "no_change": bool(proof.get("no_change")),
            "delta_net_pct_points": core.number(delta.get("net")),
            "delta_profit_factor": core.number(delta.get("pf")),
            "delta_drawdown_pct_points": core.number(delta.get("dd_reduction")),
            "trade_retention": core.number(delta.get("retention")),
        }
        payload = {
            "strategy_id": result["strategy_id"], "stage":"PRE_REPLAY_COMPONENT_AXIS",
            "changed_axes":[axis], "lineage_complete":True,
            "hypothesis":{"axis":axis,"generation":result["epoch"],"configuration":configuration,"description":"Evaluate one material component axis against the exact ledger."},
            "control":result["control"]["stats"], "candidate":stats, "evidence":evidence,
            "lineage":{"ledger_sha":result["source_authority"]["ledger_sha256"],"summary_sha":result["source_authority"]["summary_sha256"],"fingerprint":result["data_fingerprint"],"candidate_result_sha":result["result_sha256"]},
            **SAFE,
        }
        write(out/"inputs"/f"{axis}.json", payload); active.append(axis)
    index={"state":"PASS_AXIS_INPUT_PREPARATION" if active else "SKIP_NO_MATERIAL_AXIS","active_axes":active,"skipped_axes":skipped,**SAFE}
    index["index_sha256"]=core.stable_sha(index); write(out/"inputs"/"index.json",index); return index


def summarize(inputs: Path, reviews: Path, out: Path) -> dict[str, Any]:
    index=read(inputs/"index.json"); axes={}; accepted=[]
    for axis in index.get("active_axes",[]):
        receipt=read(reviews/f"{axis}.json"); providers=receipt.get("provider_results") or {}
        ga=((providers.get("groq") or {}).get("artifact") or {}); wa=((providers.get("workers_ai") or {}).get("artifact") or {})
        gd=(ga.get("review") or {}).get("decision"); wd=(wa.get("review") or {}).get("decision")
        if gd not in {"PASS_TO_REPLAY","REJECT","HOLD"} or wd not in {"PASS_TO_REPLAY","REJECT","HOLD"}: raise ValueError(f"PROVIDER_DECISION_INVALID:{axis}")
        passed=receipt.get("status")=="PASS_AI_REVIEW_ROUTER" and gd==wd=="PASS_TO_REPLAY"
        axes[axis]={"router_status":receipt.get("status"),"groq_decision":gd,"workers_decision":wd,"pass_to_next":passed,"groq_response_sha":ga.get("response_sha"),"workers_response_sha":wa.get("response_sha")}
        if passed: accepted.append(axis)
    summary={"state":"PASS_COMPONENT_AXIS_AI_GATE_V2" if accepted else "HOLD_NO_AI_APPROVED_COMPONENT_AXIS","reviewed_axis_count":len(axes),"accepted_axis_count":len(accepted),"accepted_axes":accepted,"axes":axes,"skipped_axes":index.get("skipped_axes",{}),"next":"WAIT_COMPONENT_AXIS_REPLAY_BINDING" if accepted else "WAIT_NEW_EXACT_LEDGER_OR_W1",**SAFE}
    summary["summary_sha256"]=core.stable_sha(summary); write(out,summary); return summary


def fixture(out: Path) -> int:
    result={"strategy_id":"trend_ma_macd","epoch":1,"data_fingerprint":"f"*64,"result_sha256":"r"*64,"source_authority":{"ledger_sha256":"l"*64,"summary_sha256":"s"*64},"control":{"stats":{"trade_count":24}},"axis_review_eligibility":{"BOT_POLICY":False,"TEAM_POLICY":True,"SKILL_PROFILE":False,"ADVISOR_PROFILE":False},"module_results":{"bots":{"best_by_role":{}},"teams":{"best":{"team":"AlphaTeam","stats":{"trade_count":20,"net_return_pct_sum":1.5,"profit_factor":1.7,"max_drawdown_pct":1.6},"evidence":{"material":True,"no_change":False,"deltas":{"net":0.5,"pf":0.3,"dd_reduction":0.4,"retention":0.83}}}},"skills":{"best":{}},"advisors":{}}}
    index=prepare(result,out); payload=read(out/"inputs"/"TEAM_POLICY.json")
    assert index["active_axes"]==["TEAM_POLICY"]
    assert set(payload["evidence"])=={"material","no_change","delta_net_pct_points","delta_profit_factor","delta_drawdown_pct_points","trade_retention"}
    print("PASS_COMPONENT_AXIS_AI_GATE_V2_FIXTURE"); return 0


def main() -> int:
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="mode",required=True)
    p=sub.add_parser("prepare"); p.add_argument("--result",required=True); p.add_argument("--out",required=True)
    s=sub.add_parser("summarize"); s.add_argument("--inputs",required=True); s.add_argument("--reviews",required=True); s.add_argument("--out",required=True)
    f=sub.add_parser("fixture"); f.add_argument("--out",required=True)
    args=parser.parse_args()
    if args.mode=="prepare": prepare(read(args.result),Path(args.out)); return 0
    if args.mode=="summarize": summarize(Path(args.inputs),Path(args.reviews),Path(args.out)); return 0
    return fixture(Path(args.out))


if __name__=="__main__": raise SystemExit(main())
