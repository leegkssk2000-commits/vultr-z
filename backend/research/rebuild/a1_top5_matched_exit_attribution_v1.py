#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, statistics
from pathlib import Path
from typing import Any, Mapping
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_top5_fixed_rr_payoff_shadow_v1 as rr

SCHEMA='zel.a1.top5.matched_exit_attribution.v1'


def stable(v:Any)->str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False,default=str).encode()).hexdigest()


def med(xs:list[float])->float|None:
    return None if not xs else float(statistics.median(xs))


def q(xs:list[float],p:float)->float|None:
    if not xs:return None
    ys=sorted(xs); i=(len(ys)-1)*p; lo=int(i); hi=min(lo+1,len(ys)-1); w=i-lo
    return float(ys[lo]*(1-w)+ys[hi]*w)


def summary(rows:list[dict[str,Any]])->dict[str,Any]:
    return {
      'T':len(rows),
      'hold_bars_median':med([float(x['hold_bars']) for x in rows]),
      'hold_bars_p75':q([float(x['hold_bars']) for x in rows],0.75),
      'mfe_r_median':med([float(x['mfe_r']) for x in rows]),
      'mae_r_median':med([float(x['mae_r']) for x in rows]),
      'giveback_r_median':med([float(x['giveback_r']) for x in rows]),
      'realized_r_median':med([float(x['realized_r']) for x in rows]),
    }


def row_path(src:Mapping[str,Any],bars:list[dict[str,Any]])->dict[str,Any]:
    idx={int(b['ts_ms']):i for i,b in enumerate(bars)}
    si=idx.get(int(src['signal_ts'])); ei=idx.get(int(src['entry_ts'])); xi=idx.get(int(src['exit_ts']))
    if si is None or ei is None or xi is None: raise RuntimeError(f"ROW_BAR_MISSING:{src.get('symbol')}:{src.get('signal_ts')}")
    entry=float(src.get('entry') or bars[ei]['open']); side=str(src['side']); one_r=rr.native_r(src,bars,si,entry)
    if one_r<=0: raise RuntimeError('NONPOSITIVE_NATIVE_R')
    mfe=mae=0.0
    for j in range(ei,xi+1):
        hi=float(bars[j]['high']); lo=float(bars[j]['low'])
        if side=='long': fav=max(0.0,hi-entry); adv=max(0.0,entry-lo)
        else: fav=max(0.0,entry-lo); adv=max(0.0,hi-entry)
        mfe=max(mfe,fav); mae=max(mae,adv)
    realized_bps=float(src.get('net_bps') or 0.0)
    r_bps=one_r/entry*10000.0
    realized_r=realized_bps/r_bps if r_bps else 0.0
    mfe_r=mfe/one_r; mae_r=mae/one_r; giveback=max(0.0,mfe_r-realized_r)
    return {
      'symbol':src.get('symbol'),'signal_ts':src.get('signal_ts'),'entry_ts':src.get('entry_ts'),'exit_ts':src.get('exit_ts'),
      'side':side,'reason':src.get('reason'),'net_bps':realized_bps,'hold_bars':xi-ei+1,
      'realized_r':realized_r,'mfe_r':mfe_r,'mae_r':mae_r,'giveback_r':giveback,
    }


def next_axis(win:dict[str,Any],loss:dict[str,Any])->str:
    # Diagnostic-only hypothesis selector. No same-sample adoption or promotion authority.
    if int(loss.get('T') or 0)>=3:
        lm=loss.get('mfe_r_median'); lh=loss.get('hold_bars_median'); wh=win.get('hold_bars_median')
        if lm is not None and lh is not None and wh is not None and lm<0.5 and lh>wh:
            return 'TIME_STOP_ONLY_PROSPECTIVE_HYPOTHESIS'
    if int(win.get('T') or 0)>=3:
        wm=win.get('mfe_r_median'); wg=win.get('giveback_r_median')
        if wm is not None and wg is not None and wm>=2.0 and wg>=0.5:
            return 'CONDITIONAL_RUNNER_TRAIL_ONLY_PROSPECTIVE_HYPOTHESIS'
    return 'HOLD_NO_SINGLE_CAUSAL_EXIT_AXIS_YET'


def run(trend_path:Path,a4dir:Path,breakdir:Path,out:Path)->dict[str,Any]:
    trend=rr.read(trend_path); lanes=rr.latest_sets(trend,a4dir,breakdir)
    syms=sorted({str(t['symbol']) for lane in lanes for t in lane['rows']})
    bars_by={s:ev.fetch_bars(s,'1h',1000) for s in syms}
    results=[]
    for lane in lanes:
        rows=[row_path(x,bars_by[str(x['symbol'])]) for x in lane['rows']]
        winners=[x for x in rows if float(x['net_bps'])>0]; losers=[x for x in rows if float(x['net_bps'])<0]
        by_reason={}
        for x in rows: by_reason[str(x.get('reason') or 'UNKNOWN')]=by_reason.get(str(x.get('reason') or 'UNKNOWN'),0)+1
        ws,ls=summary(winners),summary(losers)
        results.append({
          'lane':lane['lane'],'strategy_id':lane['strategy_id'],'reference':lane['reference'],'T':len(rows),
          'winner':ws,'loser':ls,'exit_reason_counts':dict(sorted(by_reason.items())),
          'next_single_axis':next_axis(ws,ls),'same_sample_adoption_forbidden':True,
          'rows':rows,
        })
    r={
      'schema_version':SCHEMA,'state':'PASS_TOP5_MATCHED_EXIT_ATTRIBUTION_COMPLETE','lanes':results,
      'purpose':'CAUSE_ATTRIBUTION_BEFORE_NEXT_EXIT_ONLY_TEST','fixed_tp_retest_forbidden':True,
      'loss_cap_retest_forbidden':True,'same_sample_selection_or_adoption_forbidden':True,
      'trend_rider_broad_g5_reference_mutated':False,'shadow_only':True,'production_mutated':False,
      'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','action':'hold'
    }
    r['receipt_sha256']=stable(r); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+'\n'); return r


def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--trend70-source',type=Path); ap.add_argument('--a4-source-dir',type=Path); ap.add_argument('--break-source-dir',type=Path); ap.add_argument('--out',type=Path,default=Path('out/a1_top5_matched_exit_attribution_v1.json')); ap.add_argument('--self-test',action='store_true'); a=ap.parse_args()
    if a.self_test:
        assert next_axis({'T':3,'hold_bars_median':10,'mfe_r_median':1,'giveback_r_median':0},{'T':3,'hold_bars_median':20,'mfe_r_median':0.2})=='TIME_STOP_ONLY_PROSPECTIVE_HYPOTHESIS'
        assert next_axis({'T':3,'hold_bars_median':10,'mfe_r_median':2.5,'giveback_r_median':0.8},{'T':2})=='CONDITIONAL_RUNNER_TRAIL_ONLY_PROSPECTIVE_HYPOTHESIS'
        print('PASS_A1_TOP5_MATCHED_EXIT_ATTRIBUTION_V1_SELF_TEST'); return 0
    if None in (a.trend70_source,a.a4_source_dir,a.break_source_dir): raise SystemExit('sources required')
    r=run(a.trend70_source,a.a4_source_dir,a.break_source_dir,a.out)
    print(json.dumps({'state':r['state'],'lanes':[{'lane':x['lane'],'T':x['T'],'winner':x['winner'],'loser':x['loser'],'next_single_axis':x['next_single_axis']} for x in r['lanes']]},sort_keys=True)); return 0

if __name__=='__main__': raise SystemExit(main())
