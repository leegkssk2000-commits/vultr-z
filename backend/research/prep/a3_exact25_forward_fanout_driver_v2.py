from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_v3_causal_registry_updater_v1 as registry_updater
from backend.research.prep import strategy_material_causal_router_v1 as causal_router

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "backend/research/rebuild/a1_exact25_v3_causal_registry_v1.json"


def read(path: Path) -> dict[str, Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False,default=str).encode()).hexdigest()


def run_module(module: str, args: list[str], log: Path) -> int:
    log.parent.mkdir(parents=True,exist_ok=True)
    with log.open("w",encoding="utf-8") as fh:
        proc=subprocess.run([sys.executable,"-m",module,*args],cwd=ROOT,stdout=fh,stderr=subprocess.STDOUT,text=True,check=False)
    return int(proc.returncode)


def state_from(path: Path, default: str="NOT_RUN") -> str:
    if not path.exists():return default
    try:return str(read(path).get("state") or default)
    except Exception:return "HOLD_PARSE_ERROR"


def build_material(output_dir: Path, registry_path: Path) -> tuple[dict[str,Any],dict[str,Any]]:
    raw=output_dir/"strategy_material_grade_v1.json"
    rc=run_module("backend.research.prep.strategy_material_grade_v1",["--output",str(raw)],output_dir/"material.log")
    if rc!=0 or not raw.exists():raise RuntimeError(f"MATERIAL_GRADE_FAILED:{rc}")
    routed=causal_router.evaluate(read(raw),read(registry_path))
    routed_path=output_dir/"strategy_material_causal_routed_v1.json"
    routed_path.write_text(json.dumps(routed,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return read(raw),routed


def evaluate_candidate(sid: str, context_path: Path, output_dir: Path) -> dict[str,Any]:
    d=output_dir/"a3_candidates"/sid;d.mkdir(parents=True,exist_ok=True)
    receipt=d/"receipt.json";controls=d/"controls.json";a1=d/"a1.json";a2=d/"a2.json";a3=d/"a3.json"
    row={"candidate_id":sid,"receipt_state":"NOT_RUN","trades":None,"control_state":"NOT_RUN","control_blockers":[],"a1_state":"NOT_RUN","a2_state":"NOT_RUN","a3_state":"NOT_RUN","errors":[]}
    rc=run_module("backend.research.rebuild.a1_exact25_generic_evaluator_v2",["--terminal-replay","--strategy-id",sid,"--out",str(receipt)],d/"receipt.log")
    if not receipt.exists():
        row["errors"].append(f"RECEIPT_MISSING_RC_{rc}");return row
    r=read(receipt);row["receipt_state"]=r.get("state");row["trades"]=r.get("completed_trades")
    rc=run_module("backend.research.rebuild.a1_exact25_v3_universal_controls_v1",["--receipt",str(receipt),"--output",str(controls)],d/"controls.log")
    if not controls.exists():
        row["errors"].append(f"CONTROLS_MISSING_RC_{rc}");return row
    c=read(controls);row["control_state"]=c.get("state");row["control_blockers"]=c.get("blockers") or [];row["hard_control_states"]=c.get("hard_control_states") or {};row["frozen_control_trade_count"]=c.get("frozen_control_trade_count")
    if c.get("state")!="PASS_V3_UNIVERSAL_HARD_CONTROLS":return row

    rc=run_module("backend.research.rebuild.a1_exact25_v3_forward_transition_v1",["--receipt",str(receipt),"--controls",str(controls),"--output",str(a1)],d/"a1.log")
    row["a1_state"]=state_from(a1,"HOLD_OR_ERROR")
    if row["a1_state"]!="PASS_A1_CAUSAL_READY_FOR_A2":
        if rc not in (0,2):row["errors"].append(f"A1_RC_{rc}")
        return row

    rc=run_module("backend.research.prep.a2_forward_cost_turnover_v1",["--transition",str(a1),"--receipt",str(receipt),"--output",str(a2)],d/"a2.log")
    row["a2_state"]=state_from(a2,"HOLD_OR_ERROR")
    if row["a2_state"]!="PASS_A2_COST_TURNOVER":
        if rc not in (0,2):row["errors"].append(f"A2_RC_{rc}")
        return row

    rc=run_module("backend.research.prep.a3_exact25_forward_durability_v1",["--receipt",str(receipt),"--a2",str(a2),"--context",str(context_path),"--output",str(a3)],d/"a3.log")
    row["a3_state"]=state_from(a3,"HOLD_OR_ERROR")
    if a3.exists():
        av=read(a3);row["a3_coverage"]=av.get("coverage");row["a3_blockers"]=av.get("blockers") or [];row["a3_failures"]=av.get("failures") or []
    if rc!=0:row["errors"].append(f"A3_RC_{rc}")
    return row


def evaluate(context_path: Path, output_dir: Path, run_id: str, head_sha: str, registry_path: Path=REGISTRY) -> dict[str,Any]:
    output_dir.mkdir(parents=True,exist_ok=True)
    _,current=build_material(output_dir,registry_path)
    current_queue=list((current.get("buckets") or {}).get("A3_PROMOTION_QUEUE") or [])
    (output_dir/"a3_queue_current.txt").write_text("\n".join(current_queue)+("\n" if current_queue else ""),encoding="utf-8")
    rows=[evaluate_candidate(str(sid),context_path,output_dir) for sid in current_queue]
    (output_dir/"a3_stage_lines.jsonl").write_text("".join(json.dumps(x,sort_keys=True)+"\n" for x in rows),encoding="utf-8")

    updated_registry=registry_updater.evaluate(read(registry_path),output_dir/"a3_candidates",str(run_id),str(head_sha))
    registry_out=output_dir/"a1_exact25_v3_causal_registry_v1.json"
    registry_out.write_text(json.dumps(updated_registry,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    next_material=causal_router.evaluate(read(output_dir/"strategy_material_grade_v1.json"),updated_registry)
    next_path=output_dir/"strategy_material_causal_routed_next_v1.json"
    next_path.write_text(json.dumps(next_material,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    next_queue=list((next_material.get("buckets") or {}).get("A3_PROMOTION_QUEUE") or [])
    (output_dir/"a3_queue_next.txt").write_text("\n".join(next_queue)+("\n" if next_queue else ""),encoding="utf-8")

    context=read(context_path)
    result={
        "schema_version":"zel.a3_exact25.forward_fanout.v2",
        "state":"PASS_A3_FANOUT_EVIDENCE_CEILING_EVALUATED",
        "current_candidate_count":len(rows),"current_queue":current_queue,"next_queue":next_queue,"rows":rows,
        "context_state":context.get("state"),"context_valid_row_count":context.get("valid_row_count"),"context_legacy_causal_ineligible_count":context.get("legacy_causal_ineligible_count"),
        "causal_registry_terminal_count":updated_registry.get("terminal_count"),"causal_registry_pass_count":updated_registry.get("pass_count"),"causal_registry_fail_count":updated_registry.get("fail_count"),
        "causal_registry_last_merge":updated_registry.get("last_merge"),
        "a3_pass_count":sum(1 for x in rows if x.get("a3_state") in ("PASS_A3_GLOBAL_DURABILITY","PASS_A3_EXPLICIT_REGIME_OWNER")),
        "a3_wait_count":sum(1 for x in rows if str(x.get("a3_state") or "").startswith("WAIT_")),
        "selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED","protected_mutations":0,"action":"hold",
    }
    result["receipt_sha256"]=sha(result)
    (output_dir/"a3_fanout_receipt_v2.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return result


def self_test() -> int:
    assert state_from(Path("/definitely/missing"))=="NOT_RUN"
    print("PASS_A3_EXACT25_FORWARD_FANOUT_DRIVER_V2_SELF_TEST");return 0


def main() -> int:
    ap=argparse.ArgumentParser();ap.add_argument("--context",type=Path);ap.add_argument("--output-dir",type=Path,default=Path("out"));ap.add_argument("--run-id");ap.add_argument("--head-sha");ap.add_argument("--registry",type=Path,default=REGISTRY);ap.add_argument("--self-test",action="store_true");args=ap.parse_args()
    if args.self_test:return self_test()
    if not args.context or not args.run_id or not args.head_sha:raise SystemExit("--context --run-id --head-sha required")
    result=evaluate(args.context,args.output_dir,str(args.run_id),str(args.head_sha),args.registry)
    print(json.dumps({"state":result["state"],"current_queue":result["current_queue"],"next_queue":result["next_queue"],"registry_fail":result["causal_registry_fail_count"],"a3_pass":result["a3_pass_count"],"receipt_sha256":result["receipt_sha256"]},sort_keys=True));return 0


if __name__=="__main__":raise SystemExit(main())
