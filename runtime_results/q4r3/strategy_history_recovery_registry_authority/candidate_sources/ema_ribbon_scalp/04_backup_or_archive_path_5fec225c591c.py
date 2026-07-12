#!/usr/bin/env python3
import json, time, datetime, re, shutil, hashlib
from pathlib import Path
from collections import Counter

API=Path("/var/www/z-os-alimi/api")
RUN=Path("/home/z/z/runtime")
OWNER="H87R4D22_OFFICIAL_CANDIDATE_UNPOISON_RR_GATE"

OFFICIAL={"vwap_revert","support_resistance","liquidity_sweep","trend_rider"}
DEFAULT_TARGET={"vwap_revert":2.5,"support_resistance":2.5,"liquidity_sweep":3.0,"trend_rider":3.0}
NONOFFICIAL={
 "turtle_trend","trend_ma_macd","bb_revert","sr_levels","obv_trend","rsi_swing_fail",
 "alpha_combo","mfi_rsi_div","keltner_trend","fvg_revert","grid_rebalance",
 "squeeze_break","supertrend_pullback","ema_ribbon_scalp","scalp_snap","session_bias"
}

SCAN_RE=re.compile(r"(candidate|admission|arbiter|allowlist|router|selector|projector|latch|rotation|entry|forward|current_batch|scope|context|batch|score|rr|tp)", re.I)
EXCL_RE=re.compile(r"(ledger|closed|history|summary|telegram|view|canonical|doctor|audit|performance|pnl|baseline|display_authority)", re.I)

def load(p):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return {}

def save(p,obj):
    p=Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp=Path(str(p)+".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)

def age(p):
    try: return round(time.time()-Path(p).stat().st_mtime,3)
    except Exception: return None

def fv(x, default=None):
    try:
        if x is None or isinstance(x,bool): return default
        return float(str(x).replace("R","").replace("%","").replace(",","").strip())
    except Exception:
        return default

def first(*xs):
    for x in xs:
        if x is not None and x != "":
            return x
    return None

def strategy_of(d):
    if not isinstance(d,dict): return ""
    for k in ["strategy","strategy_id","selected_strategy","candidate_strategy","strat","method"]:
        if d.get(k):
            return str(d.get(k))
    cur=str(d.get("current") or "")
    blob=json.dumps(d, ensure_ascii=False)
    for s in sorted(OFFICIAL|NONOFFICIAL, key=len, reverse=True):
        if s in cur or s in blob:
            return s
    return ""

def val(d, *keys):
    for k in keys:
        if k in d and d.get(k) not in [None,""]:
            return d.get(k)
    return None

def rr_of(d):
    return fv(first(
        val(d,"selected_rr"),
        val(d,"selected_rr_derived"),
        val(d,"rr"),
        val(d,"risk_reward"),
        val(d,"tp_rr"),
        val(d,"candidate_rr")
    ), None)

def target_of(st,d):
    return fv(first(val(d,"target_tp_r"), val(d,"target_rr"), val(d,"required_rr")), DEFAULT_TARGET.get(st,3.0))

def has_entry_sl_tp(d):
    e=first(val(d,"entry"), val(d,"selected_entry"), val(d,"entry_price"))
    sl=first(val(d,"sl"), val(d,"selected_sl"), val(d,"stop"), val(d,"stop_loss"))
    tp=first(val(d,"tp"), val(d,"selected_tp"), val(d,"selected_final_tp"), val(d,"take_profit"), val(d,"final_tp"))
    return e not in [None,""] and sl not in [None,""] and tp not in [None,""]

def auth_block(d):
    d["order"]="blocked"
    d["exec"]="none"
    d["order_authority"]="blocked"
    d["execution_authority"]="none"
    d["paper_request_allowed"]=False
    d["paper_execution_allowed"]=False
    d["live_execution_allowed"]=False
    d["real_order_enabled"]=False
    d["actual_close_written"]=False
    d["write_to_actual_request"]=False
    d["route_allowed"]=False
    return d

patched=[]
ready=[]
rr_blocked=[]
missing_blocked=[]
nonofficial_seen=[]
unknown_seen=[]

for root in [API,RUN]:
    if not root.exists():
        continue
    for p in root.glob("*.json"):
        name=p.name
        if not SCAN_RE.search(name):
            continue
        if EXCL_RE.search(name):
            continue

        d=load(p)
        if not isinstance(d,dict) or not d:
            continue

        st=strategy_of(d)
        a=age(p)

        if st in NONOFFICIAL:
            nonofficial_seen.append(str(p))
            continue
        if st not in OFFICIAL:
            unknown_seen.append(str(p))
            continue

        # official 후보는 R4D11의 stale block 메타를 해제한다.
        old_blocked_by=d.get("blocked_by")
        old_reason=d.get("blocked_reason")

        d["r4s_contract_ok"]=True
        d["r4s_contract_blocked"]=False
        d["official_strategy_ok"]=True
        d["official_strategy"]=st
        d["r4s_gate_owner"]=OWNER
        d["r4s_gate_updated_utc"]=datetime.datetime.now(datetime.timezone.utc).isoformat()
        d["allowed_strategies"]=sorted(OFFICIAL)
        d["previous_blocked_by"]=old_blocked_by
        d["previous_blocked_reason"]=old_reason

        rr=rr_of(d)
        target=target_of(st,d)
        complete=has_entry_sl_tp(d)

        if rr is None or not complete:
            d["candidate_ready"]=False
            d["fresh_entry_candidate_ready"]=False
            d["admission_allowed"]=False
            d["r4s_admission_allowed"]=False
            d["blocked_by"]=OWNER
            d["blocked_reason"]="OFFICIAL_CANDIDATE_MISSING_RR_OR_ENTRY_SL_TP"
            d["rr_current"]=rr
            d["rr_required"]=target
            missing_blocked.append({"path":str(p),"age_s":a,"strategy":st,"rr":rr,"target":target,"complete":complete})
        elif rr >= target:
            d["candidate_ready"]=True
            d["fresh_entry_candidate_ready"]=True
            d["admission_allowed"]=True
            d["r4s_admission_allowed"]=True
            d["blocked_by"]=""
            d["blocked_reason"]=""
            d["rr_current"]=rr
            d["rr_required"]=target
            d["admission_reason"]="OFFICIAL_R4S_RR_PASS"
            ready.append({"path":str(p),"age_s":a,"strategy":st,"rr":rr,"target":target})
        else:
            d["candidate_ready"]=False
            d["fresh_entry_candidate_ready"]=False
            d["admission_allowed"]=False
            d["r4s_admission_allowed"]=False
            d["blocked_by"]=OWNER
            d["blocked_reason"]="RR_BELOW_TARGET"
            d["rr_current"]=rr
            d["rr_required"]=target
            d["rr_gap"]=round(target-rr,6)
            rr_blocked.append({"path":str(p),"age_s":a,"strategy":st,"rr":rr,"target":target,"gap":round(target-rr,6)})

        auth_block(d)
        save(p,d)
        patched.append(str(p))

status={
    "owner":OWNER,
    "status":"ACTIVE_OFFICIAL_CANDIDATE_UNPOISON_RR_GATE",
    "updated_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "patched_official_files":len(patched),
    "ready_count":len(ready),
    "rr_blocked_count":len(rr_blocked),
    "missing_blocked_count":len(missing_blocked),
    "nonofficial_seen_count":len(nonofficial_seen),
    "unknown_seen_count":len(unknown_seen),
    "ready":ready[:50],
    "rr_blocked":rr_blocked[:80],
    "missing_blocked":missing_blocked[:80],
    "allowed_strategies":sorted(OFFICIAL),
    "order_authority":"blocked",
    "execution_authority":"none",
    "paper_request_allowed":False,
    "live_execution_allowed":False,
    "actual_close_written":False
}
save(API/"h87r4d22_official_candidate_unpoison_rr_gate_latest.json",status)
save(RUN/"h87r4d22_official_candidate_unpoison_rr_gate_latest.json",status)

summary="\n".join([
    "RESULT=PASS_R4D22_OFFICIAL_CANDIDATE_UNPOISON_RR_GATE_TICK",
    f"OWNER={OWNER}",
    f"PATCHED_OFFICIAL_FILES={len(patched)}",
    f"READY_COUNT={len(ready)}",
    f"RR_BLOCKED_COUNT={len(rr_blocked)}",
    f"MISSING_BLOCKED_COUNT={len(missing_blocked)}",
    "READY="+json.dumps(ready[:5],ensure_ascii=False),
    "RR_BLOCKED="+json.dumps(rr_blocked[:8],ensure_ascii=False),
    "ALLOWED=vwap_revert,support_resistance,liquidity_sweep,trend_rider",
    "ORDER=blocked EXEC=none LIVE=false PAPER_REQUEST=false ACTUAL_CLOSE=false",
])+"\n"
(RUN/"h87r4d22_official_candidate_unpoison_rr_gate_summary_latest.txt").write_text(summary,encoding="utf-8")
print(summary)
