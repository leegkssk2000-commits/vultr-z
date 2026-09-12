"""Saved-only final selection for Issue #1291.

No strategy replay. Reads the six completed child results/snapshots plus the already
verified CAPREUSE parent evidence and applies the selection contract frozen in SPEC.
"""
from math import fsum
from pathlib import Path
import json

from backend.research.rebuild import squeeze_kr3_unified_study_v1 as s
from backend.research.rebuild import squeeze_kr3_unified_v1 as child

ROOT=s.ROOT; OUT=s.OUT; PERIODS=s.PERIODS


def need(ok,msg):
    if not ok: raise RuntimeError(msg)


def campaign_values(result):
    rows=result['trades']
    wins=[float(t['net_bps']) for t in rows if float(t['net_bps'])>0]
    losses=[float(t['net_bps']) for t in rows if float(t['net_bps'])<0]
    mean_win=fsum(wins)/len(wins) if wins else None
    mean_loss=fsum(losses)/len(losses) if losses else None
    return dict(closed=len(rows),wins=len(wins),losses=len(losses),
                win_rate=len(wins)/len(rows) if rows else None,
                PF=fsum(wins)/abs(fsum(losses)) if losses else None,
                payoff=mean_win/abs(mean_loss) if mean_win is not None and mean_loss else None)


def one(label, per, result, snap):
    c=campaign_values(result)
    c.update(open=snap['open'],terminal_net_bps=snap['terminal_net_bps'],
             terminal_cost2x_net_bps=snap['terminal_cost2x_net_bps'],
             marked_DD_bps=snap['marked_DD_trade_sum_bps'],
             ordinary_winner_retention=snap.get('ordinary_winner_retention'),
             top_decile_winner_retention=snap.get('top_decile_winner_retention'),
             loss_tail_worst_bps=snap.get('loss_tail_worst_bps'),
             loss_tail_worst_decile_mean_bps=snap.get('loss_tail_worst_decile_mean_bps'),
             quantity_exposure_symbol_days=snap.get('quantity_exposure_symbol_days'),
             mean_quantity_exposure_positions=snap.get('mean_quantity_exposure_positions'))
    c.update(label=label,period=per)
    return c


def combined(label, perdata, results):
    rows=[t for r in results for t in r['trades']]
    wins=[float(t['net_bps']) for t in rows if float(t['net_bps'])>0]
    losses=[float(t['net_bps']) for t in rows if float(t['net_bps'])<0]
    mw=fsum(wins)/len(wins) if wins else None; ml=fsum(losses)/len(losses) if losses else None
    return dict(label=label,closed=len(rows),open=sum(x['open'] for x in perdata.values()),
        wins=len(wins),losses=len(losses),win_rate=len(wins)/len(rows) if rows else None,
        terminal_net_bps=fsum(x['terminal_net_bps'] for x in perdata.values()),
        terminal_cost2x_net_bps=fsum(x['terminal_cost2x_net_bps'] for x in perdata.values()),
        PF=fsum(wins)/abs(fsum(losses)) if losses else None,
        payoff=mw/abs(ml) if mw is not None and ml else None,
        worst_period_marked_DD_bps=max(x['marked_DD_bps'] for x in perdata.values()),
        per_period=perdata)


def load_parent():
    pdata={};results=[]
    for per in PERIODS:
        result=s.parent(per);snap=s.read(s.capacc.OUT/per/'SNAPSHOT.json')
        pdata[per]=one('CAPREUSE',per,result,snap);results.append(result)
    return combined('CAPREUSE',pdata,results)


def load_child(v):
    pdata={};results=[];decomps=[];raws=[]
    for per in PERIODS:
        folder=OUT/v/per
        receipt=s.read(folder/'RECEIPT.json')
        need(receipt['state']=='COMPLETED','CHILD_NOT_COMPLETED:'+v+':'+per)
        need(s.h(folder/'RESULT.json.gz')==receipt['result_sha256'],'RESULT_HASH:'+v+':'+per)
        need(s.h(folder/'RAW.json.gz')==receipt['raw_sha256'],'RAW_HASH:'+v+':'+per)
        need(s.h(folder/'SNAPSHOT.json')==receipt['snapshot_sha256'],'SNAPSHOT_HASH:'+v+':'+per)
        need(s.h(folder/'DECOMPOSITION.json')==receipt['decomposition_sha256'],'DECOMP_HASH:'+v+':'+per)
        result=s.gz(folder/'RESULT.json.gz');snap=s.read(folder/'SNAPSHOT.json')
        pdata[per]=one(v,per,result,snap);results.append(result)
        decomps.append(s.read(folder/'DECOMPOSITION.json'));raws.append(s.gz(folder/'RAW.json.gz'))
    out=combined(v,pdata,results)
    out['eligible']=all(pdata[p]['terminal_net_bps']>0 and pdata[p]['terminal_cost2x_net_bps']>0 and
                        pdata[p]['PF'] is not None and pdata[p]['PF']>=1 for p in PERIODS)
    out['k1_veto_T']=sum(sum(a.get('k1_veto_T',0) for a in raw['audit'].values()) for raw in raws)
    out['k2_arm_T']=sum(sum(a.get('k2_arm_T',0) for a in raw['audit'].values()) for raw in raws)
    out['k2_trigger_T']=sum(sum(a.get('k2_trigger_T',0) for a in raw['audit'].values()) for raw in raws)
    keys=('reduced_existing_loss_gross_bps','extended_existing_win_gross_bps','cut_existing_win_gross_bps',
          'added_existing_loss_gross_bps','additional_common_cost_funding_bps','occupancy_new_excluded_net_bps',
          'terminal_delta_bps')
    out['component_bridge']={k:fsum(float(d[k]) for d in decomps) for k in keys}
    return out


def main():
    spec=s.check();budget=s.read(OUT/'BUDGET.json');q=budget[s.KEY]
    need(q['completed']==6 and q['failed']==0 and q['started']==q['reserved']==6,'NOT_SIX_CLEAN_FULLS')
    parent=load_parent();candidates={v:load_child(v) for v in child.VARIANTS}
    eligible=[c for c in candidates.values() if c['eligible']]
    eligible.sort(key=lambda c:(c['terminal_net_bps'],c['terminal_cost2x_net_bps'],
                                -c['worst_period_marked_DD_bps'],c['win_rate']),reverse=True)
    best=eligible[0] if eligible else None
    selected=best['label'] if best and best['terminal_net_bps']>parent['terminal_net_bps'] else 'CAPREUSE'
    state='SELECTED_NEW_CUMULATIVE_INCUMBENT' if selected!='CAPREUSE' else 'KEEP_CAPREUSE_NO_CHILD_BEAT_COMBINED_NET'
    summary=dict(schema='zel.squeeze_kr3.true_component_unified.final.v1',scope=child.SCOPE,
        parent=parent,candidates=candidates,selected=selected,state=state,
        selection_objective=spec['selection_objective'],selection_contract_frozen_before_outcomes=True,
        formal_credit=0,used_DEV=True,Q_track_touched=False,
        candidate_count=3,economic_FULL_count=6,new_future_boundary_required=selected!='CAPREUSE',
        automatic_successor=False)
    s.put(OUT/'SUMMARY.json',summary)
    final=dict(strategy_name='Squeeze-KR3 Unified' if selected!='CAPREUSE' else None,
               selected_incumbent=selected,state=state,formal_credit=0,
               historical_used_dev_only=True,Q_track_touched=False,
               prospective_boundary_required=selected!='CAPREUSE')
    s.put(OUT/'FINAL_STATUS.json',final)
    lines=['# Squeeze-KR3 true-component Unified 결과','',
           ('Squeeze-KR3 Unified = 생성됨' if selected!='CAPREUSE' else 'Squeeze-KR3 Unified = 생성안됨'),
           '',f'- 선택: `{selected}`',f'- 상태: `{state}`','',
           '| 후보 | Combined Net | Combined cost2 | Weighted WR | PF | Payoff | Worst-period DD | Eligible |',
           '|---|---:|---:|---:|---:|---:|---:|---|']
    for name,c in [('CAPREUSE',parent)]+[(v,candidates[v]) for v in child.VARIANTS]:
        lines.append(f"| {name} | {c['terminal_net_bps']:.2f} | {c['terminal_cost2x_net_bps']:.2f} | {100*(c['win_rate'] or 0):.2f}% | {(c['PF'] or 0):.3f} | {(c['payoff'] or 0):.3f} | {c['worst_period_marked_DD_bps']:.2f} | {c.get('eligible',True)} |")
    lines+=['','## 기간별']
    for name,c in [('CAPREUSE',parent)]+[(v,candidates[v]) for v in child.VARIANTS]:
        for per in PERIODS:
            x=c['per_period'][per]
            lines.append(f"- {name} {per}: closed/open={x['closed']}/{x['open']}, WR={100*(x['win_rate'] or 0):.2f}%, net={x['terminal_net_bps']:.2f}, cost2={x['terminal_cost2x_net_bps']:.2f}, PF={(x['PF'] or 0):.3f}, payoff={(x['payoff'] or 0):.3f}, DD={x['marked_DD_bps']:.2f}")
    lines+=['','## Component effects']
    for v in child.VARIANTS:
        c=candidates[v];b=c['component_bridge']
        lines.append(f"- {v}: K1 veto={c['k1_veto_T']}, K2 arms={c['k2_arm_T']}, K2 triggers={c['k2_trigger_T']}, net delta vs CAPREUSE={b['terminal_delta_bps']:.2f}bps, loss reduction gross={b['reduced_existing_loss_gross_bps']:.2f}, winner extension gross={b['extended_existing_win_gross_bps']:.2f}, winner cut gross={b['cut_existing_win_gross_bps']:.2f}, added loss gross={b['added_existing_loss_gross_bps']:.2f}, occupancy net={b['occupancy_new_excluded_net_bps']:.2f}")
    lines+=['','모든 결과는 기존 USED_DEV 두 구간이며 formal_credit=0. Top6 Q-track/fresh/G5 자료는 사용하지 않았다.']
    (OUT/'REPORT_KO.md').write_text('\n'.join(lines)+'\n')
    s.atomic(OUT/'STATUS.json',dict(scope=child.SCOPE,state=state,selected=selected,formal_credit=0,report_only=True))
    s.persist('Finalize saved-only Squeeze/KR3 Unified selection')
    print(json.dumps(summary,sort_keys=True))

if __name__=='__main__': main()
