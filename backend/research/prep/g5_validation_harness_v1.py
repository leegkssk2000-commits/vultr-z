from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from collections import Counter, defaultdict

REQUIRED_TRADE_FIELDS=("trade_id","entry_ts","exit_ts","symbol","side","net_pnl_r","fee_r","funding_r","slippage_r","window_id")

class ValidationError(ValueError):
    pass


def purged_walk_forward(n:int, *, train:int, test:int, purge:int, embargo:int):
    if min(n,train,test)<=0 or purge<0 or embargo<0:
        raise ValidationError("bad_split_args")
    out=[]; start=0
    while True:
        train_start=start; train_end=train_start+train
        test_start=train_end+purge; test_end=test_start+test
        if test_end>n: break
        out.append({"train":[train_start,train_end],"purge":[train_end,test_start],"test":[test_start,test_end],"embargo_end":min(n,test_end+embargo)})
        start=test_end+embargo
    return out


def frozen_manifest(windows:dict)->dict:
    if set(windows)!={"W1","W2","W3"}: raise ValidationError("need_exact_w1_w2_w3")
    payload=json.dumps(windows,sort_keys=True,separators=(",",":"))
    return {"windows":windows,"sha256":sha256(payload.encode()).hexdigest(),"selection_window":"W1","w2_w3_frozen":True}


def stress_matrix(*, base_cost:float, p95_funding:float)->list[dict]:
    return [
        {"name":"BASE","cost_multiplier":1.0,"funding_override":None,"execution_bar_shift":0},
        {"name":"COST_2X","cost_multiplier":2.0,"funding_override":None,"execution_bar_shift":0},
        {"name":"P95_FUNDING","cost_multiplier":1.0,"funding_override":float(p95_funding),"execution_bar_shift":0},
        {"name":"PLUS_ONE_BAR","cost_multiplier":1.0,"funding_override":None,"execution_bar_shift":1},
    ]


def validate_trade_rows(rows:list[dict])->None:
    seen=set()
    for r in rows:
        miss=[k for k in REQUIRED_TRADE_FIELDS if r.get(k) is None]
        if miss: raise ValidationError("missing:"+",".join(miss))
        tid=str(r["trade_id"])
        if tid in seen: raise ValidationError("duplicate_trade_id")
        seen.add(tid)
        if r["exit_ts"] < r["entry_ts"]: raise ValidationError("negative_holding_time")


def recompute_metrics(rows:list[dict])->dict:
    validate_trade_rows(rows)
    pnl=[float(r["net_pnl_r"]) for r in rows]
    wins=[x for x in pnl if x>0]; losses=[x for x in pnl if x<0]
    gross_profit=sum(wins); gross_loss=-sum(losses)
    eq=0.0; peak=0.0; max_dd=0.0
    for x in pnl:
        eq+=x; peak=max(peak,eq); max_dd=max(max_dd,peak-eq)
    avg_win=sum(wins)/len(wins) if wins else 0.0
    avg_loss=-sum(losses)/len(losses) if losses else 0.0
    return {
        "trades":len(rows),
        "net_r":sum(pnl),
        "win_rate":len(wins)/len(rows) if rows else 0.0,
        "profit_factor":gross_profit/gross_loss if gross_loss>0 else (math.inf if gross_profit>0 else 0.0),
        "payoff":avg_win/avg_loss if avg_loss>0 else (math.inf if avg_win>0 else 0.0),
        "max_dd_r":max_dd,
        "fee_r":sum(float(r["fee_r"]) for r in rows),
        "funding_r":sum(float(r["funding_r"]) for r in rows),
        "slippage_r":sum(float(r["slippage_r"]) for r in rows),
    }


def deterministic_digest(rows:list[dict])->str:
    validate_trade_rows(rows)
    payload=json.dumps(sorted(rows,key=lambda x:str(x["trade_id"])),sort_keys=True,separators=(",",":"))
    return sha256(payload.encode()).hexdigest()


def parity(a:list[dict], b:list[dict])->bool:
    return deterministic_digest(a)==deterministic_digest(b) and recompute_metrics(a)==recompute_metrics(b)


def concentration(rows:list[dict], key:str)->dict:
    if key not in {"symbol","side","window_id","regime"}: raise ValidationError("unsupported_concentration_key")
    if not rows: return {"n":0,"top_share":0.0,"counts":{}}
    c=Counter(str(r.get(key,"UNKNOWN")) for r in rows)
    top=max(c.values())/len(rows)
    return {"n":len(rows),"top_share":top,"counts":dict(sorted(c.items()))}


def adjacent_parameter_grid(center:float, step:float)->list[float]:
    if step<=0: raise ValidationError("step_must_be_positive")
    return [center-step, center, center+step]


def false_discovery_contract(candidate_count:int)->dict:
    if candidate_count<1: raise ValidationError("candidate_count")
    return {"candidate_count":candidate_count,"dsr_required":candidate_count>1,"pbo_or_equivalent_required":candidate_count>1,"selection_window":"W1","w2_w3_frozen":True}
