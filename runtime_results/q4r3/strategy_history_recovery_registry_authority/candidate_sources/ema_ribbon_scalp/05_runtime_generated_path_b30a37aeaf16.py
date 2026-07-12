#!/usr/bin/env python3
import json, time, datetime, re, hashlib, math
from pathlib import Path
from collections import defaultdict

API=Path("/var/www/z-os-alimi/api")
RUN=Path("/home/z/z/runtime")
OWNER="H87R4D29_REGIME_DIRECTION_CONDITIONAL_ALLOW"

def _r4d58e_num(v):
    try:
        if v is None or isinstance(v, bool):
            return None
        return float(str(v).replace("R", "").replace("%", "").replace(",", "").strip())
    except Exception:
        return None

def _r4d58e_fourth_epoch_active():
    try:
        import json as _r4d58e_json
        from pathlib import Path as _r4d58e_Path
        _p = _r4d58e_Path("/home/z/z/runtime/r4d57_5j_epoch_slice_full_split_latest.json")
        if not _p.exists():
            return False
        _d = _r4d58e_json.loads(_p.read_text(encoding="utf-8"))
        _src = str(_d.get("src") or "")
        _source = str(_d.get("source") or "")
        _owner = str(_d.get("owner") or "")
        if ("R4D57.5J" not in _src and
            "R4D57.5J" not in _source and
            "H87R4D54C_EPOCH_SLICE_FULL_SPLIT" not in _owner and
            "H87R4D54C_EPOCH_SLICE_FULL_SPLIT" not in _src and
            "H87R4D54C_EPOCH_SLICE_FULL_SPLIT" not in _source):
            return False
        _closed = _r4d58e_num(_d.get("closed"))
        _closed_abs = _r4d58e_num(_d.get("closed_abs"))
        _anchor_abs = _r4d58e_num(_d.get("anchor_abs"))
        if _closed is None or _closed_abs is None or _anchor_abs is None:
            return False
        if abs(_closed - (_closed_abs - _anchor_abs)) > 1e-9:
            return False
        if _d.get("order_authority", _d.get("order", "blocked")) not in ("blocked", None):
            return False
        if _d.get("execution_authority", _d.get("exec", "none")) not in ("none", None):
            return False
        for _k in ("paper_execution_allowed", "paper_request_allowed", "live_execution_allowed", "real_order_enabled", "actual_close_written", "write_to_actual_request"):
            if _d.get(_k) is True:
                return False
        return True
    except Exception:
        return False

def _r4d58e_skip_legacy_r4d40_autorun():
    if _r4d58e_fourth_epoch_active():
        print("R4D58E_SKIP_LEGACY_R4D40B_D40D_D40J_DURING_4TH_EPOCH")
        return True
    return False

OFFICIAL={"vwap_revert","support_resistance","liquidity_sweep","trend_rider"}
TARGET_R={"vwap_revert":2.5,"support_resistance":2.5,"liquidity_sweep":3.0,"trend_rider":3.0}
CONDITIONAL_GROUPS={"support_resistance|long","vwap_revert|long"}

NONOFFICIAL={
 "turtle_trend","trend_ma_macd","bb_revert","sr_levels","obv_trend",
 "rsi_swing_fail","alpha_combo","mfi_rsi_div","keltner_trend",
 "fvg_revert","grid_rebalance","squeeze_break","supertrend_pullback",
 "ema_ribbon_scalp","scalp_snap","session_bias","momentum_driver",
 "vol_breakout","market_structure"
}

DISPLAY_SINKS=[
 "h87r4czx_display_authority_registry_latest.json",
 "zel_pos_auto_canonical_latest.json",
 "telegram_pnl_status_latest.json",
 "view_real_paper_ledger_summary_latest.json",
 "view_real_paper_ledger_latest.json",
 "h87_current_session_latest.json",
 "h87r4cg_unique_summary_latest.json",
 "h87r4ce_unique_summary_latest.json",
 "recent_ledger_trace_stats_latest.json",
]

STATE_PATH=API/"h87r4d26_official_shadow_lifecycle_latest.json"
BASELINE_PATH=API/"h87r4d26_official_baseline_latest.json"

CAND_RE=re.compile(r"(candidate|admission|arbiter|allowlist|router|selector|projector|latch|rotation|entry|forward|current_batch|scope|context|batch|score|rr|tp|sl|signal|session|authority)", re.I)
EXCL_RE=re.compile(r"(ledger|closed|history|summary|telegram|view|canonical|doctor|audit|performance|pnl|baseline|display_authority|single_pipeline|lifecycle|loss_decomposition|auto_loss|regime_direction)", re.I)

PRICE_FILE_RE=re.compile(r"(ohlcv|kline|candle|market|ticker|price|chart|series|symbol)", re.I)
ENTRY_KEYS={"entry","selected_entry","entry_price","candidate_entry","signal_entry","price_entry","trigger_entry"}
SL_KEYS={"sl","selected_sl","stop","stop_loss","candidate_sl","signal_sl","invalid_price","invalidation"}
TP_KEYS={"tp","selected_tp","selected_final_tp","final_tp","take_profit","candidate_tp","signal_tp","target_price","target_tp"}
RR_KEYS={"rr","selected_rr","selected_rr_derived","risk_reward","tp_rr","candidate_rr","rr_current","r_multiple"}
PRICE_KEYS={"price","last_price","mark_price","current_price","close","last"}

def load(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return {}

def save(p,obj):
    p=Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp=Path(str(p)+".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)

def age(p):
    try:
        return round(time.time()-Path(p).stat().st_mtime,3)
    except Exception:
        return None

def fv(x, default=None):
    try:
        if x is None or isinstance(x,bool):
            return default
        s=str(x).replace("R","").replace("%","").replace(",","").strip()
        if s in ["","-","None","null","nan"]:
            return default
        return float(s)
    except Exception:
        return default

def iv(x, default=0):
    try:
        return int(float(str(x).replace("R","").replace("%","").strip()))
    except Exception:
        return default

def first(*xs):
    for x in xs:
        if x is not None and x != "":
            return x
    return None

def walk(obj, limit_list=120):
    if isinstance(obj,dict):
        for k,v in obj.items():
            yield str(k),v
            if isinstance(v,(dict,list)):
                yield from walk(v,limit_list)
    elif isinstance(obj,list):
        for v in obj[:limit_list]:
            if isinstance(v,(dict,list)):
                yield from walk(v,limit_list)

def strategy_of(d):
    if not isinstance(d,dict):
        return ""
    for k in ["strategy","strategy_id","selected_strategy","candidate_strategy","strat","method"]:
        if d.get(k):
            return str(d.get(k))
    blob=json.dumps(d, ensure_ascii=False)
    cur=str(d.get("current") or "")
    for s in sorted(OFFICIAL|NONOFFICIAL, key=len, reverse=True):
        if s in cur or s in blob:
            return s
    return ""

def recursive_num(d, keys):
    if isinstance(d,dict):
        for k in keys:
            if k in d:
                v=fv(d.get(k),None)
                if v is not None:
                    return v,k
    for k,v in walk(d):
        if k in keys:
            n=fv(v,None)
            if n is not None:
                return n,k
    return None,""

def side_of(d, entry=None, sl=None, tp=None):
    s=str(first(d.get("side"),d.get("selected_side"),d.get("signal_side"),"")).replace("enter_","").lower()
    if s in ["long","buy"]:
        return "long"
    if s in ["short","sell"]:
        return "short"
    if entry is not None and sl is not None and tp is not None:
        if sl < entry < tp:
            return "long"
        if tp < entry < sl:
            return "short"
    return "-"

def geometry_ok(side, entry, sl, tp):
    if entry is None or sl is None or tp is None:
        return False
    if side=="long":
        return sl < entry < tp
    if side=="short":
        return tp < entry < sl
    return False

def compute_rr(entry, sl, tp):
    if entry is None or sl is None or tp is None:
        return None
    risk=abs(entry-sl)
    reward=abs(tp-entry)
    if risk <= 0:
        return None
    return round(reward/risk,6)

def candidate_hash(c):
    raw=f"{c.get('strategy')}|{c.get('side')}|{c.get('entry')}|{c.get('sl')}|{c.get('tp')}|{c.get('rr')}|{c.get('path')}|{c.get('parent_index')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

def extract_closes(obj):
    closes=[]
    if isinstance(obj,list):
        for x in obj:
            if isinstance(x,dict):
                v=first(x.get("close"),x.get("c"),x.get("price"),x.get("last"),x.get("mark_price"),x.get("last_price"))
                n=fv(v,None)
                if n is not None:
                    closes.append(n)
            elif isinstance(x,(list,tuple)):
                # OHLCV: [ts, open, high, low, close, volume]
                idx=4 if len(x)>4 else len(x)-1
                n=fv(x[idx],None)
                if n is not None:
                    closes.append(n)
            elif isinstance(x,(int,float,str)):
                n=fv(x,None)
                if n is not None:
                    closes.append(n)
    elif isinstance(obj,dict):
        for k,v in obj.items():
            lk=str(k).lower()
            if lk in ["closes","close","prices","price_series","ohlcv","candles","klines","data","rows"]:
                closes.extend(extract_closes(v))
            elif isinstance(v,(dict,list)):
                sub=extract_closes(v)
                if len(sub)>len(closes):
                    closes=sub
    return closes

def find_price_series():
    candidates=[]
    for root in [API,RUN]:
        if not root.exists():
            continue
        for p in root.glob("*.json"):
            try:
                if p.stat().st_size > 5000000:
                    continue
            except Exception:
                continue
            if not PRICE_FILE_RE.search(p.name):
                continue
            a=age(p)
            if a is None or a>3600:
                continue
            d=load(p)
            closes=extract_closes(d)
            closes=[x for x in closes if x and x>0]
            if len(closes)>=8:
                candidates.append((len(closes), -a, str(p), closes[-200:]))
    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][3], candidates[0][2]
    # fallback: raw/state/display 내부 단일 price들
    vals=[]
    for p in [API/"h87r4czo_shadow_lifecycle_status_latest.json", API/"h87r4czx_display_authority_registry_latest.json", API/"h87_current_session_latest.json"]:
        d=load(p)
        for k,v in walk(d):
            if k in PRICE_KEYS:
                n=fv(v,None)
                if n is not None:
                    vals.append(n)
    if len(vals)>=2:
        return vals[-30:], "fallback_recursive_price_values"
    return [], "NO_PRICE_SERIES"

def ema(values, n):
    if not values:
        return []
    k=2/(n+1)
    out=[values[0]]
    for v in values[1:]:
        out.append(v*k + out[-1]*(1-k))
    return out

def compute_regime():
    closes,src=find_price_series()
    if len(closes)<12:
        return {
            "regime":"NO_DATA",
            "price_source":src,
            "close_count":len(closes),
            "long_mean_revert_ok":False,
            "long_trend_ok":False,
            "short_ok":False,
            "reason":"NO_ENOUGH_PRICE_SERIES"
        }

    c=closes[-80:]
    last=c[-1]
    e8=ema(c,8)
    e21=ema(c,21)
    fast=e8[-1]
    slow=e21[-1]
    prev_slow=e21[-6] if len(e21)>=6 else e21[0]
    slope=(slow-prev_slow)/last if last else 0
    ret5=(last-c[-6])/c[-6] if len(c)>=6 and c[-6] else 0
    ret12=(last-c[-13])/c[-13] if len(c)>=13 and c[-13] else 0
    low8=min(c[-8:])
    high8=max(c[-8:])

    downtrend = last < fast < slow and slope < -0.00015 and ret12 < -0.001
    up_confirm = last > fast > slow and slope > 0.00010 and ret12 > 0.001
    range_reclaim = last > fast and ret5 > 0 and (last-low8)/last > 0.0015
    weak_down = last < fast and ret5 < 0

    if downtrend:
        reg="DOWNTREND"
    elif up_confirm:
        reg="UP_CONFIRM"
    elif range_reclaim:
        reg="RANGE_RECLAIM"
    elif weak_down:
        reg="WEAK_DOWN"
    else:
        reg="NEUTRAL"

    return {
        "regime":reg,
        "price_source":src,
        "close_count":len(closes),
        "last":round(last,8),
        "ema8":round(fast,8),
        "ema21":round(slow,8),
        "slope21":round(slope,8),
        "ret5":round(ret5,8),
        "ret12":round(ret12,8),
        "low8":round(low8,8),
        "high8":round(high8,8),
        "long_mean_revert_ok":bool(up_confirm or range_reclaim),
        "long_trend_ok":bool(up_confirm),
        "short_ok":bool(downtrend or weak_down),
        "reason":"REGIME_DIRECTION_COMPUTED"
    }

def raw_state():
    czo=load(API/"h87r4czo_shadow_lifecycle_status_latest.json")
    czn=load(RUN/"h87r4czn_shadow_only_single_lifecycle_state.json")
    src=czo if czo else czn
    price,_=recursive_num(src,PRICE_KEYS)
    return {
        "raw_closed":iv(first(czo.get("closed"),czo.get("closed_count"),czn.get("closed"),czn.get("closed_count")),0),
        "raw_pnl_r":fv(first(czo.get("pnl_r"),czo.get("total_pnl_r"),czn.get("pnl_r")),0.0),
        "raw_open":iv(first(czo.get("open"),czo.get("open_count"),czn.get("open"),czn.get("open_count")),0),
        "raw_current":first(czo.get("current"),czn.get("current"),""),
        "price":price
    }

def collect_candidates(regime):
    out=[]
    blocked_nonofficial=0
    unknown=0

    for root in [API,RUN]:
        if not root.exists():
            continue
        for p in root.glob("*.json"):
            if not CAND_RE.search(p.name):
                continue
            if EXCL_RE.search(p.name):
                continue
            a=age(p)
            if a is None or a>1200:
                continue
            d=load(p)
            if not isinstance(d,dict) or not d:
                continue

            items=[d]
            if isinstance(d.get("official_candidates"),list):
                for i,x in enumerate(d.get("official_candidates")):
                    if isinstance(x,dict):
                        y=dict(x)
                        y["_parent_index"]=i
                        items.append(y)

            for item in items:
                st=strategy_of(item)
                entry,es=recursive_num(item,ENTRY_KEYS)
                sl,sls=recursive_num(item,SL_KEYS)
                tp,tps=recursive_num(item,TP_KEYS)
                rr,rrs=recursive_num(item,RR_KEYS)
                side=side_of(item,entry,sl,tp)
                geo=geometry_ok(side,entry,sl,tp)
                if rr is None and geo:
                    rr=compute_rr(entry,sl,tp)
                    rrs="computed_from_entry_sl_tp"
                complete=entry is not None and sl is not None and tp is not None and rr is not None and geo

                if st in OFFICIAL:
                    target=TARGET_R.get(st,3.0)
                    rr_ready=bool(complete and rr>=target)
                    key=f"{st}|{side}"

                    allowed=False
                    reason=""
                    if not rr_ready:
                        reason="BLOCK_RR_OR_FIELD"
                    elif key in CONDITIONAL_GROUPS:
                        if regime.get("long_mean_revert_ok"):
                            allowed=True
                            reason="ALLOW_CONDITIONAL_LONG_REGIME_MATCH"
                        else:
                            reason=f"BLOCK_CONDITIONAL_LONG_REGIME_MISMATCH:{regime.get('regime')}"
                    elif st=="trend_rider":
                        if side=="long" and regime.get("long_trend_ok"):
                            allowed=True
                            reason="ALLOW_TREND_LONG_UP_CONFIRM"
                        elif side=="short" and regime.get("short_ok"):
                            allowed=True
                            reason="ALLOW_TREND_SHORT_DOWN_CONFIRM"
                        else:
                            reason=f"BLOCK_TREND_DIRECTION_MISMATCH:{regime.get('regime')}"
                    elif st=="liquidity_sweep":
                        if side=="long" and regime.get("regime") not in ["DOWNTREND","NO_DATA"]:
                            allowed=True
                            reason="ALLOW_LIQUIDITY_LONG_NOT_DOWNTREND"
                        elif side=="short" and regime.get("regime") not in ["UP_CONFIRM","NO_DATA"]:
                            allowed=True
                            reason="ALLOW_LIQUIDITY_SHORT_NOT_UPCONFIRM"
                        else:
                            reason=f"BLOCK_LIQUIDITY_DIRECTION_MISMATCH:{regime.get('regime')}"
                    else:
                        allowed=True
                        reason="ALLOW_DEFAULT_OFFICIAL_RR_PASS"

                    c={
                        "path":str(p),
                        "parent_index":item.get("_parent_index",""),
                        "age_s":a,
                        "strategy":st,
                        "side":side,
                        "entry":entry,
                        "sl":sl,
                        "tp":tp,
                        "rr":rr,
                        "target_r":target,
                        "complete":complete,
                        "geometry_ok":geo,
                        "rr_ready":rr_ready,
                        "regime_allowed":allowed,
                        "decision":reason,
                        "key":key,
                        "entry_src":es,
                        "sl_src":sls,
                        "tp_src":tps,
                        "rr_src":rrs
                    }
                    c["candidate_hash"]=candidate_hash(c)
                    out.append(c)
                elif st in NONOFFICIAL:
                    blocked_nonofficial+=1
                else:
                    unknown+=1

    # dedupe
    seen=set()
    dedup=[]
    for c in sorted(out,key=lambda x:(not x["regime_allowed"], -(x.get("rr") or 0), x.get("age_s") or 999999)):
        h=c["candidate_hash"]
        if h in seen:
            continue
        seen.add(h)
        dedup.append(c)
    return dedup, blocked_nonofficial, unknown

def close_check(open_trade, price):
    if not open_trade or price is None:
        return None
    side=str(open_trade.get("side") or "")
    tp=fv(open_trade.get("tp"),None)
    sl=fv(open_trade.get("sl"),None)
    rr=fv(open_trade.get("rr"),0.0)
    if tp is None or sl is None:
        return None
    if side=="long":
        if price >= tp:
            return "TP", rr
        if price <= sl:
            return "SL", -1.0
    if side=="short":
        if price <= tp:
            return "TP", rr
        if price >= sl:
            return "SL", -1.0
    return None

def norm_row(r):
    out=dict(r)
    out["pnl_r"]=fv(out.get("pnl_r"),0.0)
    return out

base=load(BASELINE_PATH)
state=load(STATE_PATH)

if not isinstance(base,dict):
    base={"closed":0,"pnl_r":0,"wr":0,"rows":[]}
if not isinstance(state,dict):
    state={"open_trade":None,"closed_rows":[],"seen_hashes":[]}
if not isinstance(state.get("closed_rows"),list):
    state["closed_rows"]=[]
if not isinstance(state.get("seen_hashes"),list):
    state["seen_hashes"]=[]

regime=compute_regime()
raw=raw_state()
price=raw.get("price") or regime.get("last")
events=[]

# 기존 open 유지, TP/SL만 처리
open_trade=state.get("open_trade")
hit=close_check(open_trade,price)
if hit:
    reason,pnl=hit
    row=dict(open_trade)
    row["exit"]=price
    row["exit_reason"]=reason
    row["pnl_r"]=round(pnl,6)
    row["closed_utc"]=datetime.datetime.now(datetime.timezone.utc).isoformat()
    row["classification"]="R4D29_EXISTING_OPEN_RESOLVED"
    row["source_owner"]=OWNER
    state["closed_rows"].append(row)
    state["open_trade"]=None
    events.append(f"CLOSED_{reason}:{row.get('trade_id')}:{pnl}R")

candidates, blocked_nonofficial, unknown = collect_candidates(regime)
allowed=[c for c in candidates if c.get("regime_allowed")]
blocked=[c for c in candidates if not c.get("regime_allowed")]

# 신규 open 재개: 장세·방향 일치 후보만
if not state.get("open_trade"):
    seen=set(state.get("seen_hashes",[]))
    new_allowed=[c for c in allowed if c["candidate_hash"] not in seen]
    if new_allowed:
        best=sorted(new_allowed,key=lambda x:(-(x.get("rr") or 0), x.get("age_s") or 999999))[0]
        tid="R4D29-"+best["candidate_hash"]
        state["open_trade"]={
            "trade_id":tid,
            "candidate_hash":best["candidate_hash"],
            "symbol":"SOLUSDT",
            "strategy":best["strategy"],
            "side":best["side"],
            "entry":best["entry"],
            "sl":best["sl"],
            "tp":best["tp"],
            "rr":best["rr"],
            "opened_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "status":"OPEN_WAIT_TP_SL",
            "source":"R4D29_REGIME_DIRECTION_MATCH_OPEN",
            "regime":regime,
            "order_authority":"blocked",
            "execution_authority":"none",
            "paper_execution_allowed":False,
            "live_execution_allowed":False,
            "actual_close_written":False
        }
        state["seen_hashes"].append(best["candidate_hash"])
        state["seen_hashes"]=state["seen_hashes"][-500:]
        events.append(f"OPENED_REGIME_OK:{tid}:{best['strategy']}|{best['side']}:RR={best['rr']}:{regime.get('regime')}")

state["owner"]=OWNER
state["new_shadow_open_allowed"]="conditional"
state["regime_direction_policy"]=regime
state["updated_utc"]=datetime.datetime.now(datetime.timezone.utc).isoformat()
save(STATE_PATH,state)
save(RUN/"h87r4d26_official_shadow_lifecycle_latest.json",state)

life_rows=[norm_row(r) for r in state.get("closed_rows",[])]
base_rows=base.get("rows") if isinstance(base.get("rows"),list) else []
base_closed=iv(base.get("closed"),0)
base_pnl=fv(base.get("pnl_r"),0.0)

closed=base_closed+len(life_rows)
pnl=round(base_pnl+sum(fv(r.get("pnl_r"),0.0) for r in life_rows),6)
wins=sum(1 for r in life_rows if fv(r.get("pnl_r"),0.0)>0)
wr=round(wins/len(life_rows)*100,3) if life_rows else fv(base.get("wr"),0.0)
ev=round(pnl/closed,6) if closed else 0.0

open_trade=state.get("open_trade")
open_count=1 if open_trade else 0

if open_trade:
    status="R4D29_REGIME_MATCH_OPEN_WAIT_TP_SL"
    current=f"{open_trade.get('symbol')} {open_trade.get('strategy')} {open_trade.get('side')} RR={open_trade.get('rr')} regime={regime.get('regime')}"
    strategy=open_trade.get("strategy","-")
    side=open_trade.get("side","-")
    entry=open_trade.get("entry","-")
    sl=open_trade.get("sl","-")
    tp=open_trade.get("tp","-")
else:
    status="R4D29_REGIME_WAIT_DIRECTION_MATCH"
    current=f"R4D29_WAIT_REGIME_MATCH regime={regime.get('regime')}"
    strategy="-"
    side="-"
    entry="-"
    sl="-"
    tp="-"

rows=(base_rows+life_rows)[-300:]

payload={
    "owner":OWNER,
    "display_owner":OWNER,
    "status":status,
    "state":status,
    "epoch":"H87R4D29_REGIME_DIRECTION_CONDITIONAL_ALLOW",
    "mode":"shadow",
    "lane":"ZEL_FOCUS",
    "updated_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "source":"R4D29_REGIME_DIRECTION_CONDITIONAL_ALLOW",
    "src":"R4D29:regime_direction_conditional_allow_resume_negative_pnl",
    "resume_from_current_negative_pnl":True,
    "reset_closed":False,
    "reset_pnl":False,

    "regime":regime,
    "conditional_groups":sorted(list(CONDITIONAL_GROUPS)),
    "candidate":len(candidates),
    "candidate_count":len(candidates),
    "admitted":len(allowed),
    "admitted_count":len(allowed),
    "blocked_by_regime_count":len(blocked),
    "blocked_by_regime":blocked[:50],
    "allowed_candidates":allowed[:50],
    "blocked_nonofficial_candidate_count":blocked_nonofficial,
    "unknown_candidate_count":unknown,

    "raw_state":raw,
    "raw_closed":raw["raw_closed"],
    "raw_pnl_r":raw["raw_pnl_r"],
    "raw_open":raw["raw_open"],
    "raw_current":raw["raw_current"],

    "open":open_count,
    "open_count":open_count,
    "shadow_open":open_count,
    "paper_open":0,
    "live_open":0,
    "open_trade":open_trade,

    "closed":closed,
    "closed_count":closed,
    "total_closed":closed,
    "perfC":closed,
    "pnl_r":pnl,
    "perfR":pnl,
    "wr":wr,
    "wr_pct":wr,
    "EV":ev,
    "last12":f"{pnl}R / EV {ev}R / WR {wr}%",

    "current":current,
    "symbol":"SOLUSDT" if open_trade else "-",
    "strategy":strategy,
    "side":side,
    "entry":entry,
    "sl":sl,
    "tp":tp,

    "lifecycle_events":events,
    "recent_ledger":rows[-12:],
    "recent_rows":rows[-12:],
    "closed_rows":rows,
    "rows":rows,

    "action":"hold",
    "order":"blocked",
    "exec":"none",
    "order_authority":"blocked",
    "execution_authority":"none",
    "paper_request_allowed":False,
    "paper_execution_allowed":False,
    "live_execution_allowed":False,
    "real_order_enabled":False,
    "actual_close_written":False,
    "write_to_actual_request":False,
    "route_allowed":False,
}

for name in DISPLAY_SINKS:
    save(API/name,payload)

save(API/"h87r4d29_regime_direction_conditional_allow_latest.json",payload)
save(RUN/"h87r4d29_regime_direction_conditional_allow_latest.json",payload)

summary="\n".join([
    "RESULT=PASS_R4D29_REGIME_DIRECTION_CONDITIONAL_ALLOW_TICK",
    f"OWNER={OWNER}",
    f"STATE={status}",
    f"REGIME={regime.get('regime')}",
    f"LONG_MEAN_REVERT_OK={regime.get('long_mean_revert_ok')}",
    f"LONG_TREND_OK={regime.get('long_trend_ok')}",
    f"SHORT_OK={regime.get('short_ok')}",
    f"PRICE_SOURCE={regime.get('price_source')}",
    f"CONDITIONAL_GROUPS={sorted(list(CONDITIONAL_GROUPS))}",
    f"CANDIDATE={len(candidates)}",
    f"ADMITTED_AFTER_REGIME={len(allowed)}",
    f"BLOCKED_BY_REGIME={len(blocked)}",
    f"OFFICIAL_OPEN={open_count}",
    f"OFFICIAL_CLOSED={closed}",
    f"OFFICIAL_PNL_R={pnl}",
    f"RAW_CLOSED={raw['raw_closed']}",
    f"RAW_PNL_R={raw['raw_pnl_r']}",
    f"EVENTS={events}",
    f"CURRENT={current}",
    "RESUME_FROM_NEGATIVE_PNL=true",
    "RESET=false",
    "SOURCE=R4D29_REGIME_DIRECTION_CONDITIONAL_ALLOW",
    "ORDER=blocked EXEC=none LIVE=false PAPER_REQUEST=false ACTUAL_CLOSE=false",
])+"\n"
(RUN/"h87r4d29_regime_direction_conditional_allow_summary_latest.txt").write_text(summary,encoding="utf-8")
print(summary)


# H87R4D32_ABCD_POLICY_SIDECAR_AUTORUN
try:
    import subprocess as _h87r4d32_subprocess
    _h87r4d32_subprocess.run(["/usr/bin/python3","/usr/local/bin/zel_h87r4d32_abcd_policy_sidecar.py"], text=True, timeout=60)
except Exception as _h87r4d32_e:
    pass


# H87R4D33_CONDITIONAL_POLICY_SELECTOR_AUTORUN
try:
    import subprocess as _h87r4d33_subprocess
    _h87r4d33_subprocess.run(["/usr/bin/python3","/usr/local/bin/zel_h87r4d33_policy_selector.py"], text=True, timeout=60)
except Exception:
    pass


# H87R4D35_SKILL_ATTRIBUTION_SIDECAR_AUTORUN
try:
    import subprocess as _h87r4d35_subprocess
    _h87r4d35_subprocess.run(["/usr/bin/python3","/usr/local/bin/zel_h87r4d35_skill_attribution_sidecar.py"], text=True, timeout=60)
except Exception:
    pass


# H87R4D38_SKILL_POLICY_SHADOW_MATRIX_AUTORUN
try:
    import subprocess as _h87r4d38_subprocess
    _h87r4d38_subprocess.run(["/usr/bin/python3","/usr/local/bin/zel_h87r4d38_skill_policy_shadow_matrix.py"], text=True, timeout=60)
except Exception:
    pass


# H87R4D40B_VIEW_PNL_POLICY_BINDER_AUTORUN
if _r4d58e_skip_legacy_r4d40_autorun():
    pass
else:
    try:
        import subprocess as _h87r4d40b_subprocess
        _h87r4d40b_subprocess.run(["/usr/bin/python3","/usr/local/bin/zel_h87r4d40b_view_pnl_policy_binder.py"], text=True, timeout=60)
    except Exception:
        pass


# H87R4D40D_RAW_PNL_QUARANTINE_AUTORUN
if _r4d58e_skip_legacy_r4d40_autorun():
    pass
else:
    try:
        import subprocess as _r4d40d_subprocess
        _r4d40d_subprocess.run(["/usr/bin/python3","/usr/local/bin/zel_h87r4d40d_raw_pnl_quarantine.py"], text=True, timeout=60)
    except Exception:
        pass


# H87R4D40J_RAW_PNL_WRITER_CHAIN_GUARD_AUTORUN
if _r4d58e_skip_legacy_r4d40_autorun():
    pass
else:
    try:
        import subprocess as _r4d40j_subprocess
        _r4d40j_subprocess.run(["/usr/bin/python3","/usr/local/bin/zel_h87r4d40j_raw_pnl_writer_chain_guard.py"], text=True, timeout=60)
    except Exception:
        pass
