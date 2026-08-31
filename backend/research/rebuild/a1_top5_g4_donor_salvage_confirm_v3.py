#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from backend.research.rebuild import a1_top5_entry_transplant_replay_v1 as base
from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as child_eval
from backend.research.rebuild import a1_top5_g4_recent_historical_accelerator_v1 as core

ROOT=Path(__file__).resolve().parents[3]
CONTRACT=ROOT/'backend/research/contracts/a1_top5_g4_donor_salvage_confirm_v3.json'
FREEZE=ROOT/'backend/research/contracts/a1_top5_replacement_child_freeze_v2.json'
ORIG=ROOT/'backend/research/contracts/a1_top5_entry_transplant_replay_v1.json'
INTERVAL_MS=14_400_000


def rd(p): return json.loads(Path(p).read_text())
def metric(rows): return base.metric_plus([dict(x) for x in rows])
def subset(rows,a,b): return [x for x in rows if a <= int(x.get('signal_ts') or 0) < b]
def loss_red(parent,child):
    p=float(parent.get('net_pnl_bps') or 0); c=float(child.get('net_pnl_bps') or 0)
    return 0.0 if p>=0 else (c-p)/abs(p)*100.0

def expr_ok(row,bars,engine,expr):
    idx=base.available_bar_index(bars,int(row['signal_ts']))
    if idx is None or idx<50 or str(row.get('side'))!='long': return False
    try: return bool(engine.eval(expr,idx))
    except (TypeError,ValueError,ZeroDivisionError): return False

def built_ok(row,bars,engine,spec):
    ok,_=base.architecture_accepts(row,bars,engine,spec); return bool(ok)

def main(a):
    c=rd(CONTRACT); freeze=rd(FREEZE); orig=rd(ORIG)
    assert c['state']=='PREREGISTERED_9M_SALVAGE_CONFIRM_NO_MORE_RETUNE'
    start=core.utc_ms(c['window']['start_utc']); end=core.utc_ms(c['window']['end_utc']); prior6=core.utc_ms(c['window']['prior_6m_start_utc'])
    children={str(x['lane_id']):x for x in freeze['children']}
    break_child=children['break_and_continue_main']; super_child=children['supertrend_pullback_main']
    break_rows,break_src=core.v2_trades(break_child,start,end,freeze['frozen_symbol_universe'])
    super_rows,super_src=core.v2_trades(super_child,start,end,freeze['frozen_symbol_universe'])
    parents={'break_and_continue_main':break_rows,'supertrend_pullback_main':super_rows}
    allrows=break_rows+super_rows; symbols=sorted({str(x['symbol']) for x in allrows})
    bars={s:child_eval._bars(s,'4h',start,end+INTERVAL_MS) for s in symbols}
    archs={x['architecture_id']:x for x in base.architectures(orig,freeze)}
    super_arch=archs['supertrend_replacement_highvol_mom_long_4h_h12_v2']
    custom={}
    expr='abs(ret1) >= 1.00 * retstd20 and ret1 > 0 and ema20 > ema50'
    for s,b in bars.items():
        _,e=child_eval._features(b,super_arch['spec']); e.validate(expr); custom[s]=e
    built={}
    for aid in ['break_replacement_breakout50_long_4h_h6_v2','keltner_replacement_trend_pull_long_4h_h12_v2']:
        spec=archs[aid]['spec']
        for s,b in bars.items():
            _,e=child_eval._features(b,spec); e.validate(str(spec['entry_rule'])); built[(aid,s)]=e

    cells=[]
    for t in c['frozen_tests']:
        pl=t['recipient']; rows=[dict(x) for x in parents[pl]]; pm9=metric(rows); pm6=metric(subset(rows,prior6,end)); kept=[]; vetoed=[]
        for r in rows:
            s=str(r['symbol'])
            if t['mode']=='INCLUSION':
                if s not in set(t['symbols']): continue
                if expr_ok(r,bars[s],custom[s],t['rule']): kept.append(r)
            else:
                ids=[t['donor']] if t['mode']=='VETO' else list(t['donors']); veto=False
                for aid in ids:
                    allow={'HYPE-USDT','LINK-USDT'} if aid=='break_replacement_breakout50_long_4h_h6_v2' else set()
                    if allow and s not in allow: continue
                    if built_ok(r,bars[s],built[(aid,s)],archs[aid]['spec']): veto=True; break
                (vetoed if veto else kept).append(r)
        m9=metric(kept); m6=metric(subset(kept,prior6,end)); ext=metric(subset(kept,start,prior6)); ret=(len(kept)/len(rows)*100) if rows else 0.0
        if t['mode']=='INCLUSION':
            g=c['gates']['break_inclusion']; checks={
              'T9':int(m9.get('trades') or 0)>=int(g['minimum_9m_T']),
              'net9':float(m9.get('net_pnl_bps') or 0)>0,
              'pf9':m9.get('profit_factor') is not None and float(m9['profit_factor'])>=float(g['profit_factor_9m_minimum']),
              'exp9':m9.get('net_expectancy_bps') is not None and float(m9['net_expectancy_bps'])>0,
              'net6':float(m6.get('net_pnl_bps') or 0)>0,
              'pf6':m6.get('profit_factor') is not None and float(m6['profit_factor'])>=float(g['prior_6m_profit_factor_minimum']),
              'dd9':float(m9.get('drawdown_bps') or 0)<float(pm9.get('drawdown_bps') or 0),
            }
            decision='CONFIRMED_HISTORICAL_SALVAGE_CANDIDATE_FRESH_REQUIRED' if all(checks.values()) else 'NOT_CONFIRMED'
            lr9=lr6=None
        else:
            g=c['gates']['risk_filter']; lr9=loss_red(pm9,m9); lr6=loss_red(pm6,m6); checks={
              'retained':ret>=float(g['minimum_retained_pct']),
              'lossred9':lr9>=float(g['minimum_9m_loss_reduction_pct']),
              'lossred6':lr6>=float(g['minimum_prior_6m_loss_reduction_pct']),
              'dd9':float(m9.get('drawdown_bps') or 0)<float(pm9.get('drawdown_bps') or 0),
              'exp9':m9.get('net_expectancy_bps') is not None and pm9.get('net_expectancy_bps') is not None and float(m9['net_expectancy_bps'])>float(pm9['net_expectancy_bps']),
            }
            decision='CONFIRMED_RISK_FILTER_DONOR_ONLY' if all(checks.values()) else 'NOT_CONFIRMED'
        cells.append({'test_id':t['id'],'recipient':pl,'mode':t['mode'],'kept_T':len(kept),'vetoed_T':len(vetoed),'retention_pct':ret,'parent_9m':pm9,'metrics_9m':m9,'parent_prior6m':pm6,'metrics_prior6m':m6,'metrics_extension3m':ext,'loss_reduction_9m_pct':lr9,'loss_reduction_prior6m_pct':lr6,'checks':checks,'decision':decision})
    confirmed=[x for x in cells if x['decision'].startswith('CONFIRMED_')]
    out={'schema_version':'zel.a1.top5.g4.donor_salvage_confirm.receipt.v3','state':'PASS_9M_SALVAGE_CONFIRM_COMPLETE','observed_at_utc':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'window':c['window'],'cell_count':len(cells),'confirmed_count':len(confirmed),'confirmed':confirmed,'cells':cells,'source_summary':{'break':break_src,'supertrend':super_src},'historical_formal_g4_credit':0,'historical_formal_g5_credit':0,'fresh_credit':0,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED'}
    Path(a.out).write_text(json.dumps(out,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print(json.dumps({'state':out['state'],'confirmed_count':len(confirmed),'decisions':[[x['test_id'],x['decision'],x['kept_T'],x['metrics_9m'].get('net_pnl_bps'),x['metrics_9m'].get('profit_factor')] for x in cells]},sort_keys=True))

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--out',required=True); main(p.parse_args())
