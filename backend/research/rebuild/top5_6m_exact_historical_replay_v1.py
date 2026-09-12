#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import _side, _validate_side
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_top5_g4_recent_historical_accelerator_v1 as hist
from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as child_eval
from backend.research.rebuild import g5_q0_convex_collector_v1 as qcol
from backend.research.rebuild import q0_convex_intrabar_adapter_v1 as qintrabar
from backend.research.rebuild import q0_prospective_engine_v1 as qengine
from backend.research.rebuild import squeeze_kr3_future_dual_generator_v1 as sqgen
from backend.research.rebuild import squeeze_kr3_native_sleeve_v1 as sqarb
from backend.research.rebuild import trend_rider_unified_v1_policy as trpolicy

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = "zel.top5.6m_exact_historical_replay.v1"
START_MS = int(datetime.fromisoformat("2026-03-12T14:00:00+00:00").timestamp() * 1000)
END_MS = int(datetime.fromisoformat("2026-09-12T14:00:00+00:00").timestamp() * 1000)
WINDOW_DAYS = (END_MS - START_MS) / 86_400_000.0
HOUR_MS = 3_600_000
BAR4_MS = 14_400_000
MINUTE_MS = 60_000
SYMBOLS7 = ("1000PEPE-USDT","BCH-USDT","BTC-USDT","ETH-USDT","HYPE-USDT","LINK-USDT","SOL-USDT")
TREND_SYMBOLS = ("BTC-USDT","ETH-USDT")
V2_FREEZE = ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json"
COST_AUTH = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
SQUEEZE_STATE = ROOT / "backend/research/rebuild/g5_squeeze_kr3_unified_state_v1.json"
Q0_STATE = ROOT / "backend/research/rebuild/g5_q0_convex_state_v1.json"
TREND_POLICY_PATH = ROOT / "backend/research/rebuild/trend_rider_unified_v1_policy.py"


def stable(v: Any) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",",":"), ensure_ascii=False, allow_nan=False, default=str).encode()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def percentile(values: Sequence[float], p: float) -> float | None:
    if not values:
        return None
    xs = sorted(float(x) for x in values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs)-1)*p
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    w = pos-lo
    return xs[lo]*(1-w)+xs[hi]*w


def max_concurrent(trades: Sequence[Mapping[str, Any]]) -> int:
    points=[]
    for t in trades:
        if t.get("entry_ts") is None or t.get("exit_ts") is None:
            continue
        points.append((int(t["entry_ts"]),1))
        points.append((int(t["exit_ts"]),-1))
    # exits before entries on the same timestamp
    points.sort(key=lambda x:(x[0],x[1]))
    cur=mx=0
    for _,d in points:
        cur+=d;mx=max(mx,cur)
    return mx


def bucket_counts(trades: Sequence[Mapping[str, Any]], fmt: str) -> dict[str,int]:
    c=Counter()
    for t in trades:
        ts=int(t.get("signal_ts",t.get("entry_ts",0)))
        d=datetime.fromtimestamp(ts/1000,tz=timezone.utc)
        if fmt=="week":
            y,w,_=d.isocalendar();key=f"{y}-W{w:02d}"
        else:
            key=f"{d.year}-{d.month:02d}"
        c[key]+=1
    return dict(sorted(c.items()))


def cost_from_model(model: Mapping[str, Any], hold_ms: int, floor: float=0.0) -> float:
    base=float(model.get("fee_bps",0))+float(model.get("spread_bps",0))+float(model.get("impact_bps",0))
    funding=float(model.get("funding_p95_per_settlement_bps",0))
    settlements=max(0, math.ceil(max(0,hold_ms)/28_800_000))
    return max(float(floor), base + funding*settlements)


def normalize_trade(t: Mapping[str, Any], *, net_bps: float, cost_bps: float) -> dict[str, Any]:
    return {
        "symbol": str(t["symbol"]),
        "signal_ts": int(t["signal_ts"]),
        "entry_ts": int(t["entry_ts"]),
        "exit_ts": int(t["exit_ts"]),
        "side": str(t.get("side","long")),
        "gross_bps": float(t["gross_bps"]),
        "cost_bps": float(cost_bps),
        "net_bps": float(net_bps),
        "exit_reason": str(t.get("exit_reason",t.get("reason","UNKNOWN"))),
        **({"component":str(t["unified_component"])} if t.get("unified_component") else {}),
    }


def summarize(name: str, trades: Sequence[Mapping[str, Any]], *, signals: int, opens: int, integrity: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    tr=[dict(x) for x in trades if START_MS <= int(x["signal_ts"]) < END_MS and x.get("exit_ts") is not None]
    tr.sort(key=lambda x:(int(x["exit_ts"]),int(x["signal_ts"]),x["symbol"]))
    vals=[float(x["net_bps"]) for x in tr]
    gross=[float(x["gross_bps"]) for x in tr]
    costs=[float(x["cost_bps"]) for x in tr]
    wins=[x for x in vals if x>0];losses=[-x for x in vals if x<0]
    eq=peak=dd=0.0
    for x in vals:
        eq+=x;peak=max(peak,eq);dd=max(dd,peak-eq)
    holds=[(int(x["exit_ts"])-int(x["entry_ts"]))/3_600_000 for x in tr]
    sym=Counter(x["symbol"] for x in tr)
    top_sym,top_n=(sym.most_common(1)[0] if sym else (None,0))
    avg_win=sum(wins)/len(wins) if wins else None
    avg_loss=sum(losses)/len(losses) if losses else None
    return {
        "strategy":name,
        "signals":int(signals),
        "opens":int(opens),
        "closed_T":len(tr),
        "T_per_day":len(tr)/WINDOW_DAYS,
        "expected_days_for_20T":20.0/(len(tr)/WINDOW_DAYS) if tr else None,
        "hold_hours":{"mean":statistics.mean(holds) if holds else None,"median":statistics.median(holds) if holds else None,"p95":percentile(holds,.95)},
        "max_concurrent_positions":max_concurrent(tr),
        "symbol_concentration":{"counts":dict(sorted(sym.items())),"top_symbol":top_sym,"top_share":top_n/len(tr) if tr else None},
        "weekly_T":bucket_counts(tr,"week"),
        "monthly_T":bucket_counts(tr,"month"),
        "gross_pnl_bps":sum(gross),
        "net_pnl_bps":sum(vals),
        "net_bps_per_day":sum(vals)/WINDOW_DAYS,
        "net_expectancy_bps":sum(vals)/len(vals) if vals else None,
        "win_rate":len(wins)/len(vals) if vals else None,
        "profit_factor":sum(wins)/sum(losses) if losses else (None if not wins else "INF"),
        "payoff":avg_win/avg_loss if avg_win is not None and avg_loss not in (None,0) else None,
        "drawdown_bps":dd,
        "cost_bps_total":sum(costs),
        "cost2_net_bps":sum(gross)-2*sum(costs),
        "integrity":dict(integrity),
        "source":dict(source),
        "trades_sha256":stable(tr),
        "trades":tr,
    }


def trend_replay() -> dict[str, Any]:
    auth=ev.load_json(COST_AUTH)
    if auth.get("state")!="FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY":
        raise RuntimeError("TREND_COST_AUTHORITY_INVALID")
    policy_sha=ev.git_blob_sha(TREND_POLICY_PATH)
    cfg=trpolicy.TrendRiderUnifiedV1Config()
    interval=ev.interval_for_ms(int(cfg.timeframe_ms))
    if interval!="1h": raise RuntimeError("TREND_INTERVAL_DRIFT")
    max_hold=int(getattr(cfg,"timeout_bars",48))
    evaluation_end=END_MS+(max_hold+2)*HOUR_MS
    all_trades=[];source={};signals=0;opens=0;cost_receipts={}
    for symbol in TREND_SYMBOLS:
        bars=hist.paged_bars(symbol,"1h",START_MS,evaluation_end)
        source[symbol]={"bars":len(bars),"first_ts":int(bars[0]["ts"]) if bars else None,"last_ts":int(bars[-1]["ts"]) if bars else None,"sha256":stable(bars)}
        snap=ev.fetch_execution_snapshot(symbol,dict(auth))
        cost_bps=float(snap["pretrade_verified_cost_bps"]);cost_receipts[symbol]=str(snap["snapshot_sha256"])
        blocked_until=-1
        for i in range(64,len(bars)-1):
            signal_ts=int(bars[i]["ts"])
            if signal_ts<START_MS: continue
            if signal_ts>=END_MS: break
            try:
                f=trpolicy.compute_trend_rider_feature(bars[:i+1],symbol=symbol,now_ts_ms=signal_ts,config=cfg)
                if bool(f.values.get("long_confirm"))==bool(f.values.get("short_confirm")): continue
                intent=trpolicy.build_trend_rider_intent(f,policy_source_sha=policy_sha,verified_round_trip_cost_bps=cost_bps,config=cfg)
            except ValueError as exc:
                if str(exc).startswith(("WARMUP_","WINDOW_","ATR_")): continue
                raise
            if bool(getattr(intent,"no_trade")): continue
            signals+=1
            side_name=str(getattr(intent,"side"));entry_i=i+1;entry_ts=int(bars[entry_i]["ts"])
            owns,cooldown=ev.execution_ownership_policy(intent)
            if owns and ev.ownership_blocked(entry_ts,blocked_until): continue
            opens+=1
            entry=float(bars[entry_i]["open"]);sgn=1.0 if side_name=="long" else -1.0
            timeout=int((getattr(intent,"timeout",{}) or {}).get("bars",getattr(cfg,"timeout_bars",1)))
            sl,tp=getattr(intent,"sl",None),getattr(intent,"tp",None)
            last_j=min(len(bars)-1,entry_i+max(1,timeout))
            exit_px=exit_ts=reason=None
            for j in range(entry_i,last_j+1):
                b=bars[j];lo,hi=float(b["low"]),float(b["high"])
                if sl is not None and ((sgn>0 and lo<=float(sl)) or (sgn<0 and hi>=float(sl))): exit_px,exit_ts,reason=float(sl),int(b["ts"]),"SL";break
                if tp is not None and ((sgn>0 and hi>=float(tp)) or (sgn<0 and lo<=float(tp))): exit_px,exit_ts,reason=float(tp),int(b["ts"]),"TP";break
            if exit_px is None:
                if last_j>=len(bars): continue
                exit_px,exit_ts,reason=float(bars[last_j]["close"]),int(bars[last_j]["ts"]),"TIMEOUT"
            if owns:
                blocked_until=max(blocked_until,ev.reserve_position_ownership(exit_ts=int(exit_ts),open_horizon_ts=None,cooldown_bars=cooldown,timeframe_ms=HOUR_MS))
            gross=sgn*(float(exit_px)-entry)/entry*10_000.0
            all_trades.append(normalize_trade({"symbol":symbol,"signal_ts":signal_ts,"entry_ts":entry_ts,"exit_ts":int(exit_ts),"side":side_name,"gross_bps":gross,"exit_reason":reason},net_bps=gross-cost_bps,cost_bps=cost_bps))
    return summarize("TrendRider Unified",all_trades,signals=signals,opens=opens,integrity={"duplicate":len(all_trades)!=len({stable((x['symbol'],x['signal_ts'],x['entry_ts'],x['exit_ts'],x['side'])) for x in all_trades}),"lookahead":False,"fresh_rows_used":False},source={"bars":source,"cost_snapshot_sha256":cost_receipts,"policy_blob_sha":policy_sha})


def v2_replay(child_id: str, public_name: str) -> dict[str, Any]:
    freeze=read(V2_FREEZE);child=next(x for x in freeze["children"] if x["child_id"]==child_id)
    trades,source=hist.v2_trades(child,START_MS,END_MS,SYMBOLS7)
    # v2_trades already enforces same-symbol non-overlap and fixed 20bps.
    all_rows=[normalize_trade({**t,"exit_reason":t.get("reason","TIME_STOP")},net_bps=float(t["net_bps"]),cost_bps=20.0) for t in trades]
    spec=child["executable_spec"];raw_signals=0
    for symbol in SYMBOLS7:
        bars=hist.paged_bars(symbol,"4h",START_MS,END_MS+(int(spec["max_hold_bars"])+2)*BAR4_MS)
        if len(bars)<60: continue
        _,eng=child_eval._features(bars,spec);eng.validate(str(spec["entry_rule"]));_validate_side(str(spec["side_rule"]),eng)
        for i in range(50,len(bars)-1):
            ts=int(bars[i]["ts"])
            if ts<START_MS: continue
            if ts>=END_MS: break
            try: fire=bool(eng.eval(str(spec["entry_rule"]),i))
            except (TypeError,ZeroDivisionError,ValueError): fire=False
            if fire: raw_signals+=1
    return summarize(public_name,all_rows,signals=raw_signals,opens=len(all_rows),integrity={"duplicate":False,"lookahead":False,"fresh_rows_used":False,"fixed_cost_bps":20.0},source={"bars":source,"freeze_sha256":stable(freeze),"child_id":child_id})


def squeeze_replay() -> dict[str, Any]:
    st=read(SQUEEZE_STATE);all_tr=[];signals=opens=0;source={};seen=set()
    for symbol in SYMBOLS7:
        rows0=hist.paged_bars(symbol,"4h",START_MS,END_MS+30*BAR4_MS)
        rows=[{"bar_open_ts":int(x["ts"]),"bar_close_ts":int(x["ts"])+BAR4_MS,"open":float(x["open"]),"high":float(x["high"]),"low":float(x["low"]),"close":float(x["close"]),"volume":float(x.get("volume",0.0))} for x in rows0]
        source[symbol]={"bars":len(rows),"first_ts":rows[0]["bar_open_ts"] if rows else None,"last_ts":rows[-1]["bar_open_ts"] if rows else None,"sha256":stable(rows)}
        model=st["cost_models"][symbol]["model"]
        r=sqgen.generate_symbol_campaigns(rows,symbol=symbol,eval_start_ms=START_MS,eval_end_ms=END_MS,cost_model=model)
        signals+=len(r["core_campaigns"])+len(r["donor_campaigns"])
        accepted=[]
        for row in r["core_campaigns"]: accepted.append(deepcopy(row))
        for item in r["arbitration_plan"]["accepted_natural"]: accepted.append(deepcopy(item["row"]))
        for item in r["arbitration_plan"]["accepted_preempt"]:
            row=sqarb.preempt_raw(item["row"],rows,int(item["preempt_ts"]));row["symbol"]=symbol;row["unified_component"]="C54_B_DONOR";accepted.append(row)
        for row in accepted:
            if int(row["signal_ts"])<START_MS or int(row["signal_ts"])>=END_MS: continue
            key=(symbol,int(row["signal_ts"]),int(row["entry_ts"]),row.get("unified_component","CAPREUSE82_CORE"))
            if key in seen: continue
            seen.add(key);opens+=1
            if "exit_ts" not in row: continue
            gross=float(row["gross_bps"]);hold=int(row["exit_ts"])-int(row["entry_ts"]);cost=cost_from_model(model,hold)
            all_tr.append(normalize_trade(row,net_bps=gross-cost,cost_bps=cost))
    return summarize("Squeeze-KR3 Unified",all_tr,signals=signals,opens=opens,integrity={"duplicate":False,"lookahead":False,"fresh_rows_used":False,"rule_id":sqgen.RULE_ID},source={"bars":source,"cost_state_sha256":str(st["state_sha256"]),"generator_rule":sqgen.RULE_ID})


def minute_witness(symbol: str, bar_open: int, bar_close: int) -> list[dict[str, Any]]:
    raw=hist.decode(hist.req({"symbol":symbol,"interval":"1m","limit":500,"endTime":bar_close-1}))
    rows=[{"ts_ms":int(x["ts"]),"open":float(x["open"]),"high":float(x["high"]),"low":float(x["low"]),"close":float(x["close"]),"volume":float(x.get("volume",0.0))} for x in raw if bar_open<=int(x["ts"])<bar_close]
    rows.sort(key=lambda x:x["ts_ms"])
    if len(rows)!=240 or any(rows[i]["ts_ms"]-rows[i-1]["ts_ms"]!=MINUTE_MS for i in range(1,len(rows))):
        raise RuntimeError(f"Q0_1M_WITNESS_NONCONTIGUOUS:{symbol}:{bar_open}:{len(rows)}")
    return rows


def q0_replay() -> dict[str, Any]:
    st=read(Q0_STATE);rows_by={};source={}
    for symbol in SYMBOLS7:
        rows0=hist.paged_bars(symbol,"4h",START_MS-180*BAR4_MS,END_MS+BAR4_MS)
        rows=[{"bar_open_ts":int(x["ts"]),"bar_close_ts":int(x["ts"])+BAR4_MS,"open":float(x["open"]),"high":float(x["high"]),"low":float(x["low"]),"close":float(x["close"]),"volume":float(x.get("volume",0.0))} for x in rows0]
        rows_by[symbol]=rows;source[symbol]={"bars":len(rows),"first_ts":rows[0]["bar_open_ts"] if rows else None,"last_ts":rows[-1]["bar_open_ts"] if rows else None,"sha256":stable(rows)}
    warm=qcol.common_warmup(rows_by,START_MS,max_bars=180)
    es=qengine.initialize(warm,list(SYMBOLS7),START_MS,END_MS)
    maps={s:{int(r["bar_open_ts"]):r for r in rows_by[s]} for s in SYMBOLS7};witness_n=0
    while int(es["cursor_close_ts"])<END_MS:
        open_ts=int(es["cursor_close_ts"])
        if open_ts>=END_MS: break
        batch={s:deepcopy(maps[s][open_ts]) for s in SYMBOLS7 if open_ts in maps[s]}
        if len(batch)!=len(SYMBOLS7): raise RuntimeError(f"Q0_4H_SOURCE_GAP:{open_ts}")
        before=deepcopy(es);after=qengine.advance(es,batch);needs=[]
        for symbol in SYMBOLS7:
            prior_n=len(before["by_symbol"][symbol]["trades"])
            for t in after["by_symbol"][symbol]["trades"][prior_n:]:
                if t.get("exit_reason")=="PROTECTIVE_STOP_INTRABAR": needs.append(symbol)
        minute={s:minute_witness(s,open_ts,open_ts+BAR4_MS) for s in sorted(set(needs))}
        after,w=qintrabar.repair_new_intrabar_trades(before,after,batch,rows_by,minute);witness_n+=len(w);es=after
    all_tr=[];signals=opens=0
    for symbol in SYMBOLS7:
        lane=es["by_symbol"][symbol]
        signals+=sum(1 for e in lane.get("events",[]) if e.get("direction")=="UP" and START_MS<=int(e["signal_ts"])<END_MS)
        trades=[t for t in lane.get("trades",[]) if START_MS<=int(t["signal_ts"])<END_MS]
        opens+=len(trades)+(1 if lane.get("position") else 0)
        model=st["cost_models"][symbol]["model"]
        for t in trades:
            if t.get("exit_reason")=="PROTECTIVE_STOP_INTRABAR" and not t.get("intrabar_stop_4h_timing_resolved"):
                raise RuntimeError(f"Q0_INTRABAR_UNRESOLVED:{symbol}:{t['signal_ts']}")
            gross=float(t["gross_bps"]);hold=int(t["exit_ts"])-int(t["entry_ts"]);cost=cost_from_model(model,hold,floor=20.0)
            row={"symbol":symbol,"signal_ts":int(t["signal_ts"]),"entry_ts":int(t["entry_ts"]),"exit_ts":int(t["exit_ts"]),"side":"long","gross_bps":gross,"exit_reason":t["exit_reason"]}
            all_tr.append(normalize_trade(row,net_bps=gross-cost,cost_bps=cost))
    return summarize("Q0 Channel Breakout",all_tr,signals=signals,opens=opens,integrity={"duplicate":False,"lookahead":False,"fresh_rows_used":False,"intrabar_witness_count":witness_n,"missing_intrabar_witness":0},source={"bars":source,"q0_state_sha256":str(st["state_sha256"]),"engine_sha256":str(st["engine_sha256"]),"intrabar_adapter_sha256":str(st["intrabar_adapter_sha256"])})


def main() -> int:
    ap=argparse.ArgumentParser();ap.add_argument("--out",default="out/top5_6m_exact_historical_replay_v1.json");args=ap.parse_args()
    started=time.time()
    results=[]
    results.append(trend_replay())
    results.append(squeeze_replay())
    results.append(v2_replay("keltner_replacement_trend_pull_long_4h_h12_v2","Keltner Reclaim"))
    results.append(v2_replay("supertrend_replacement_highvol_mom_long_4h_h12_v2","Supertrend Momentum"))
    results.append(q0_replay())
    receipt={
        "schema_version":SCHEMA,
        "state":"TERMINAL_TOP5_6M_EXACT_HISTORICAL_REPLAY",
        "window":{"start_ms":START_MS,"end_ms":END_MS,"start_utc":"2026-03-12T14:00:00Z","end_exclusive_utc":"2026-09-12T14:00:00Z","calendar_days":WINDOW_DAYS},
        "fresh_rows_used":False,"historical_backfill_to_g5":False,"formal_credit":0,"strategy_tuning":False,"threshold_grid":False,"symbol_cherry_pick":False,"paid_ai":0,"orders":0,"live":0,"deploy":0,
        "results":results,"runtime_seconds":time.time()-started,
        "source_identity":{"master_head_at_runtime":ev.git_head_sha(),"script_blob_sha":ev.git_blob_sha(Path(__file__)),"v2_freeze_sha256":stable(read(V2_FREEZE)),"squeeze_frozen_state_sha256":str(read(SQUEEZE_STATE)["state_sha256"]),"q0_frozen_state_sha256":str(read(Q0_STATE)["state_sha256"])},
    }
    receipt["receipt_sha256"]=stable(receipt)
    p=Path(args.out);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(receipt,sort_keys=True,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({"state":receipt["state"],"receipt_sha256":receipt["receipt_sha256"],"runtime_seconds":receipt["runtime_seconds"],"closed_T":{x["strategy"]:x["closed_T"] for x in results}},sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
