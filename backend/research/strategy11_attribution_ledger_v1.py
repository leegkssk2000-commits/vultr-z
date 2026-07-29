from __future__ import annotations

import argparse, hashlib, json
from collections import defaultdict
from pathlib import Path
from typing import Any

SAFETY={"research_only":True,"promotion_authority":False,"protected_mutations":0,"execution_allowed":False,"order_authority":"BLOCKED"}

def canonical(v:Any)->str:return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def sha(v:Any)->str:return hashlib.sha256(canonical(v).encode()).hexdigest()
def read(p:Path)->dict[str,Any]:
 v=json.loads(p.read_text());
 if not isinstance(v,dict): raise ValueError("JSON_OBJECT_REQUIRED")
 return v

def build(x:dict[str,Any])->dict[str,Any]:
 for k,e in SAFETY.items():
  if x.get(k)!=e: raise ValueError(f"SAFETY_MISMATCH:{k}")
 if not isinstance(x.get("trades"),list) or not x["trades"]: raise ValueError("TRADES_REQUIRED")
 rows=[]; agg=defaultdict(lambda:{"gross":0.0,"cost":0.0,"net":0.0,"trades":0})
 seen=set()
 for t in x["trades"]:
  req={"trade_id","strategy_id","material_id","team","symbol","regime","window_id","gross_pnl_r","fee_r","slippage_r","funding_r","source_sha","candidate_sha","data_sha","window_sha","manifest_sha"}
  if not req.issubset(t): raise ValueError("TRADE_FIELDS_MISSING")
  if t["trade_id"] in seen: raise ValueError("DUPLICATE_TRADE_ID")
  seen.add(t["trade_id"])
  cost=float(t["fee_r"])+float(t["slippage_r"])+float(t["funding_r"]); net=float(t["gross_pnl_r"])-cost
  row={**t,"cost_r":round(cost,10),"net_pnl_r":round(net,10),"lineage_sha":sha({k:t[k] for k in ["source_sha","candidate_sha","data_sha","window_sha","manifest_sha"]})}
  rows.append(row)
  for dim,key in [("strategy",t["strategy_id"]),("material",t["material_id"]),("team",t["team"]),("symbol",t["symbol"]),("regime",t["regime"]),("window",t["window_id"])]:
   a=agg[(dim,str(key))]; a["gross"]+=float(t["gross_pnl_r"]);a["cost"]+=cost;a["net"]+=net;a["trades"]+=1
 summary={f"{d}:{k}":{"gross_pnl_r":round(v["gross"],10),"cost_r":round(v["cost"],10),"net_pnl_r":round(v["net"],10),"trades":v["trades"]} for (d,k),v in sorted(agg.items())}
 total=round(sum(r["net_pnl_r"] for r in rows),10)
 strategy={k.split(":",1)[1]:v["net_pnl_r"] for k,v in summary.items() if k.startswith("strategy:")}
 marginal={k:round(total-v,10) for k,v in strategy.items()}
 return {"schema_version":"strategy11.attribution_ledger.v1","status":"PASS_STRATEGY_ATTRIBUTION_LEDGER","input_sha":sha(x),"trade_count":len(rows),"total_net_pnl_r":total,"rows":rows,"attribution":summary,"leave_one_strategy_out_net_r":marginal,"append_only":True,"runtime_bound":False,**SAFETY}

def main()->int:
 ap=argparse.ArgumentParser();ap.add_argument("--input",type=Path,required=True);ap.add_argument("--output",type=Path,required=True);a=ap.parse_args()
 try:r=build(read(a.input));a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,indent=2,sort_keys=True)+"\n");print(r["status"]);return 0
 except Exception as e:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({"status":"HOLD_STRATEGY_ATTRIBUTION_LEDGER","blockers":[str(e)],**SAFETY},indent=2)+"\n");return 1
if __name__=="__main__":raise SystemExit(main())
