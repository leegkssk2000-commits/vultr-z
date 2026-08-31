#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from backend.research.rebuild import a1_top5_entry_transplant_replay_v1 as base
from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as child_eval

ROOT=Path(__file__).resolve().parents[3]
CONTRACT=ROOT/'backend/research/contracts/a1_top5_g4_donor_salvage_v2.json'
FREEZE=ROOT/'backend/research/contracts/a1_top5_replacement_child_freeze_v2.json'
ORIG=ROOT/'backend/research/contracts/a1_top5_entry_transplant_replay_v1.json'
INTERVAL_MS=14_400_000
RECENT3_START=1778796000000  # 2026-05-15T00:00:00Z approx aligned usage by prior fasttrack
RECENT3_END=1786744800000    # 2026-08-15T00:00:00Z approx aligned usage by prior fasttrack


def rd(p): return json.loads(Path(p).read_text())
def finite(v): return isinstance(v,(int,float)) and math.isfinite(float(v))

def key(r: Mapping[str,Any]):
    return (str(r.get('symbol') or ''),int(r.get('signal_ts') or 0),int(r.get('entry_ts') or 0),str(r.get('side') or ''))

def metrics(rows): return base.metric_plus([dict(x) for x in rows])
def recent3(rows): return [x for x in rows if RECENT3_START <= int(x.get('signal_ts') or 0) < RECENT3_END]

def accept_expr(row,bars,engine,expr):
    idx=base.available_bar_index(bars,int(row['signal_ts']))
    if idx is None or idx<50 or str(row.get('side'))!='long': return False
    try: return bool(engine.eval(expr,idx))
    except (TypeError,ValueError,ZeroDivisionError): return False

def builtin_accept(row,bars,engine,spec):
    ok,_=base.architecture_accepts(row,bars,engine,spec)
    return bool(ok)

def loss_reduction_pct(parent_net, child_net):
    p=float(parent_net or 0); c=float(child_net or 0)
    if p>=0: return 0.0
    return (c-p)/abs(p)*100.0

def inclusion_gate(m6,m3,parent,ret,gate):
    pf6=m6.get('profit_factor'); pf3=m3.get('profit_factor')
    checks={
      'T6_min':int(m6.get('trades') or 0)>=int(gate['inclusion_minimum_closed_T']),
      'T3_min':int(m3.get('trades') or 0)>=6,
      'ret_min':ret>=float(gate['inclusion_minimum_retention_pct']),
      'net6_pos':float(m6.get('net_pnl_bps') or 0)>0,
      'net3_pos':float(m3.get('net_pnl_bps') or 0)>0,
      'pf6_min':pf6 is not None and float(pf6)>=float(gate['inclusion_profit_factor_minimum']),
      'pf3_min':pf3 is not None and float(pf3)>=1.0,
      'exp_up':m6.get('net_expectancy_bps') is not None and parent.get('net_expectancy_bps') is not None and float(m6['net_expectancy_bps'])>float(parent['net_expectancy_bps']),
      'dd_up':float(m6.get('drawdown_bps') or 0)<float(parent.get('drawdown_bps') or 0),
    }
    return all(checks.values()),checks

def veto_gate(m6,parent,ret,gate):
    lr=loss_reduction_pct(parent.get('net_pnl_bps'),m6.get('net_pnl_bps'))
    checks={
      'retained_min':ret>=float(gate['veto_minimum_retained_pct']),
      'exp_up':m6.get('net_expectancy_bps') is not None and parent.get('net_expectancy_bps') is not None and float(m6['net_expectancy_bps'])>float(parent['net_expectancy_bps']),
      'dd_up':float(m6.get('drawdown_bps') or 0)<float(parent.get('drawdown_bps') or 0),
      'loss_reduction_min':lr>=float(gate['veto_minimum_loss_reduction_pct']),
    }
    strategy=all(checks.values()) and float(m6.get('net_pnl_bps') or 0)>0
    risk=all(checks.values()) and not strategy
    return strategy,risk,checks,lr

def main(a):
    c=rd(CONTRACT); freeze=rd(FREEZE); orig=rd(ORIG)
    assert c['state']=='PREREGISTERED_DONOR_SALVAGE_V2_DEVELOPMENT_ONLY'
    parents={x['lane_id']:x for x in map(rd,[a.break_json,a.supertrend_json])}
    archs={x['architecture_id']:x for x in base.architectures(orig,freeze)}
    allrows=[t for p in parents.values() for t in p['trades']]
    min_ts=min(int(x['signal_ts']) for x in allrows); max_ts=max(int(x['signal_ts']) for x in allrows)
    symbols=sorted({str(x['symbol']) for x in allrows})
    bars={s:child_eval._bars(s,'4h',min_ts,max_ts+INTERVAL_MS) for s in symbols}
    # Supertrend feature engine supports the nested relaxed thresholds; exact donor engines support veto tests.
    super_arch=archs['supertrend_replacement_highvol_mom_long_4h_h12_v2']
    engines={}
    for s,b in bars.items():
        _,e=child_eval._features(b,super_arch['spec']);
        for expr in [x['rule'] for x in c['experiments'] if x.get('rule')]: e.validate(expr)
        # Keltner veto rule uses only EMA features already present in the supertrend engine.
        for expr in [x['veto_rule'] for x in c['experiments'] if x.get('veto_rule')]: e.validate(expr)
        engines[('custom',s)]=e
    for aid in ['break_replacement_breakout50_long_4h_h6_v2','keltner_replacement_trend_pull_long_4h_h12_v2']:
        spec=archs[aid]['spec']
        for s,b in bars.items():
            _,e=child_eval._features(b,spec); e.validate(str(spec['entry_rule'])); engines[(aid,s)]=e

    outcells=[]; gate=c['candidate_gate']
    for ex in c['experiments']:
        pl=ex['recipient']; rows=[dict(x) for x in parents[pl]['trades']]; pm=metrics(rows)
        kept=[]; vetoed=[]
        for r in rows:
            s=str(r['symbol']); allow=set(ex.get('symbol_allow') or [])
            if ex['mode'].startswith('INCLUSION'):
                if allow and s not in allow: continue
                ok=accept_expr(r,bars[s],engines[('custom',s)],ex['rule'])
                if not ok: continue
                if ex['mode']=='INCLUSION_WITH_VETO' and accept_expr(r,bars[s],engines[('custom',s)],ex['veto_rule']):
                    vetoed.append(r); continue
                kept.append(r)
            else:
                veto=False
                ids=[]
                if ex['mode']=='VETO': ids=[ex['veto_donor']]
                elif ex['mode']=='VETO_UNION': ids=list(ex['veto_donors'])
                for aid in ids:
                    scope_allow=set()
                    if aid=='break_replacement_breakout50_long_4h_h6_v2': scope_allow={'HYPE-USDT','LINK-USDT'}
                    if scope_allow and s not in scope_allow: continue
                    if builtin_accept(r,bars[s],engines[(aid,s)],archs[aid]['spec']): veto=True; break
                (vetoed if veto else kept).append(r)
        m6=metrics(kept); m3=metrics(recent3(kept)); ret=(len(kept)/len(rows)*100) if rows else 0.0
        if ex['mode'].startswith('INCLUSION'):
            cand,checks=inclusion_gate(m6,m3,pm,ret,gate); risk=False; lr=None
            decision='SALVAGE_TRANSPLANT_CANDIDATE_REQUIRES_FRESH_CONFIRMATION' if cand else 'NO_FORMAL_SALVAGE_CANDIDATE'
        else:
            cand,risk,checks,lr=veto_gate(m6,pm,ret,gate)
            decision='SALVAGE_STRATEGY_FILTER_CANDIDATE_REQUIRES_FRESH_CONFIRMATION' if cand else ('RISK_FILTER_DONOR_ONLY_NOT_G4_SURVIVOR' if risk else 'NO_FORMAL_SALVAGE_CANDIDATE')
        outcells.append({
          'experiment_id':ex['id'],'recipient':pl,'mode':ex['mode'],'kept_T':len(kept),'vetoed_T':len(vetoed),'retention_pct':ret,
          'parent_metrics':pm,'metrics_6m':m6,'metrics_recent3m':m3,'loss_reduction_pct':lr,'checks':checks,'decision':decision,
          'kept_trade_keys':[list(key(x)) for x in kept], 'vetoed_trade_keys':[list(key(x)) for x in vetoed]
        })
    candidates=[x for x in outcells if x['decision'].startswith('SALVAGE_')]
    risk=[x for x in outcells if x['decision']=='RISK_FILTER_DONOR_ONLY_NOT_G4_SURVIVOR']
    result={
      'schema_version':'zel.a1.top5.g4.donor_salvage.receipt.v2','state':'PASS_DONOR_SALVAGE_V2_COMPLETE','observed_at_utc':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
      'source_run_id':c['source_run_id'],'cell_count':len(outcells),'candidate_count':len(candidates),'risk_filter_count':len(risk),'candidates':candidates,'risk_filters':risk,'cells':outcells,
      'formal_g4_credit':0,'formal_g5_credit':0,'fresh_credit':0,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED'
    }
    Path(a.out).write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print(json.dumps({'state':result['state'],'candidate_count':len(candidates),'risk_filter_count':len(risk),'decisions':[[x['experiment_id'],x['decision'],x['kept_T'],x['metrics_6m'].get('net_pnl_bps')] for x in outcells]},sort_keys=True))

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--break-json',required=True); p.add_argument('--supertrend-json',required=True); p.add_argument('--out',required=True); main(p.parse_args())
