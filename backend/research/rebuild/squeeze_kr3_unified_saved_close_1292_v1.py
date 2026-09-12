"""Saved-only closure for Issue #1292.

Reads immutable completed evidence only. It cannot execute strategy replay or allocate economics.
"""
import gzip, hashlib, json, math, os, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
SCOPE='SQUEEZE_KR3_TRUE_COMPONENT_UNIFIED_EXECUTION_REPAIR_AFTER_1291_V1'
OUT=ROOT/'research/development_evidence'/SCOPE
CAP=ROOT/'research/development_evidence/C70_TM_PARTIAL_CAPACITY_REUSE_AFTER_PR1260_V1'
PERIODS=('DEV2025','SEEN2026')
VARIANTS=('U1','U2','U3')
KEY='squeeze_kr3_unified_repair_1292_allocation'


def need(ok,msg):
    if not ok: raise RuntimeError(msg)

def canon(obj):
    return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()

def read(path):
    return json.loads(Path(path).read_text())

def gz(path):
    with gzip.open(path,'rt',encoding='utf-8') as f: return json.load(f)

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while True:
            b=f.read(1024*1024)
            if not b: break
            h.update(b)
    return h.hexdigest()

def put(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(canon(obj)+b'\n')

def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT,text=True,timeout=45).strip()

def persist(message):
    git('add','--',str(OUT.relative_to(ROOT)))
    git('commit','-m',message+' [skip ci]')
    head=git('rev-parse','HEAD')
    git('push','origin','HEAD:refs/heads/codex/squeeze-kr3-unified-repair-1292')
    remote=git('ls-remote','origin','refs/heads/codex/squeeze-kr3-unified-repair-1292').split()[0]
    need(head==remote,'REMOTE_READBACK_MISMATCH')
    return head

def snapshot_view(label,period,s):
    return dict(label=label,period=period,closed=int(s['closed']),open=int(s['open']),
        win_rate=s.get('win_rate'),terminal_net_bps=float(s['terminal_net_bps']),
        terminal_cost2x_net_bps=float(s['terminal_cost2x_net_bps']),PF=s.get('PF'),
        payoff=s.get('realized_payoff'),marked_DD_bps=float(s['marked_DD_trade_sum_bps']),
        expectancy_bps_per_trade=s.get('expectancy_bps_per_trade'),
        ordinary_winner_retention=s.get('ordinary_winner_retention'),
        top_decile_winner_retention=s.get('top_decile_winner_retention'),
        loss_tail_worst_bps=s.get('loss_tail_worst_bps'),
        loss_tail_worst_decile_mean_bps=s.get('loss_tail_worst_decile_mean_bps'),
        quantity_exposure_symbol_days=s.get('quantity_exposure_symbol_days'),
        mean_quantity_exposure_positions=s.get('mean_quantity_exposure_positions'))

def combine(label,pdata):
    closed=sum(x['closed'] for x in pdata.values())
    wins=sum(round(x['closed']*x['win_rate']) if x['win_rate'] is not None else 0 for x in pdata.values())
    return dict(label=label,closed=closed,open=sum(x['open'] for x in pdata.values()),wins=wins,
        weighted_win_rate=(wins/closed if closed else None),
        combined_terminal_net_bps=sum(x['terminal_net_bps'] for x in pdata.values()),
        combined_cost2_bps=sum(x['terminal_cost2x_net_bps'] for x in pdata.values()),
        worst_period_DD_bps=max(x['marked_DD_bps'] for x in pdata.values()),per_period=pdata)

def parent():
    pdata={}
    for p in PERIODS:
        pdata[p]=snapshot_view('CAPREUSE',p,read(CAP/p/'SNAPSHOT.json'))
    return combine('CAPREUSE',pdata)

def child(v):
    pdata={};k1=k2arm=k2trigger=0
    bridge={k:0.0 for k in ('reduced_existing_loss_gross_bps','extended_existing_win_gross_bps','cut_existing_win_gross_bps','added_existing_loss_gross_bps','additional_common_cost_funding_bps','occupancy_new_excluded_net_bps','terminal_delta_bps')}
    for p in PERIODS:
        folder=OUT/v/p;receipt=read(folder/'RECEIPT.json')
        need(receipt['state']=='COMPLETED','NOT_COMPLETED:'+v+':'+p)
        for fn,key in (('RAW.json.gz','raw_sha256'),('RESULT.json.gz','result_sha256'),('SNAPSHOT.json','snapshot_sha256'),('DECOMPOSITION.json','decomposition_sha256')):
            need(sha(folder/fn)==receipt[key],'HASH:'+v+':'+p+':'+fn)
        snap=read(folder/'SNAPSHOT.json'); pdata[p]=snapshot_view(v,p,snap)
        raw=gz(folder/'RAW.json.gz')
        for rr in raw.values():
            a=rr['audit'];k1+=int(a.get('k1_veto_T',0));k2arm+=int(a.get('k2_arm_T',0));k2trigger+=int(a.get('k2_trigger_T',0))
        d=read(folder/'DECOMPOSITION.json')
        for key in bridge: bridge[key]+=float(d.get(key,0.0))
    c=combine(v,pdata)
    c['eligible']=all(pdata[p]['terminal_net_bps']>0 and pdata[p]['terminal_cost2x_net_bps']>0 and pdata[p]['PF'] is not None and pdata[p]['PF']>=1 for p in PERIODS)
    c.update(k1_veto_T=k1,k2_arm_T=k2arm,k2_trigger_T=k2trigger,component_bridge=bridge)
    return c

def main():
    budget=read(OUT/'BUDGET.json'); q=budget[KEY]
    need((q['reserved'],q['started'],q['completed'],q['failed'],q['remaining'])==(6,6,6,0,0),'BUDGET_NOT_TERMINAL_CLEAN')
    need(budget['cumulative_actual']==88 and budget['cumulative_actual_evaluations']==159,'ORDINALS_NOT_88_159')
    need((OUT.parent/'SQUEEZE_KR3_TRUE_COMPONENT_UNIFIED_AFTER_TOP6_V1/U1/DEV2025/FAILURE.json').exists(),'PREDECESSOR_FAILURE_MISSING')
    need(not (OUT.parent/'SQUEEZE_KR3_TRUE_COMPONENT_UNIFIED_AFTER_TOP6_V1/U1/DEV2025/RESULT.json.gz').exists(),'PREDECESSOR_RESULT_SHOULD_NOT_EXIST')
    p=parent(); cs={v:child(v) for v in VARIANTS}
    eligible=[c for c in cs.values() if c['eligible']]
    eligible.sort(key=lambda c:(c['combined_terminal_net_bps'],c['combined_cost2_bps'],-c['worst_period_DD_bps'],c['weighted_win_rate'] or -1),reverse=True)
    best=eligible[0] if eligible else None
    selected=best['label'] if best and best['combined_terminal_net_bps']>p['combined_terminal_net_bps'] else 'CAPREUSE'
    state='SELECTED_NEW_CUMULATIVE_INCUMBENT' if selected!='CAPREUSE' else 'KEEP_CAPREUSE_NO_CHILD_BEAT_COMBINED_NET'
    summary=dict(schema='zel.squeeze_kr3.true_component_unified.saved_close.v1',scope=SCOPE,
        predecessor_no_output_failure='candidate85/evaluation153',parent=p,candidates=cs,selected=selected,state=state,
        ranking=['combined_terminal_net_bps','combined_cost2_bps','lower_worst_period_DD_bps','weighted_win_rate'],
        eligibility='each period terminal_net>0 AND cost2>0 AND PF>=1',WR_hard_gate=False,
        economic_FULL_count=6,new_economic_execution_in_closure=0,formal_credit=0,Q_track_touched=False,
        automatic_successor=False)
    put(OUT/'SUMMARY.json',summary)
    if selected!='CAPREUSE':
        put(OUT/'INCUMBENT_SEAL.json',dict(schema='zel.squeeze_kr3.unified_v1.seal.v1',strategy_name='Squeeze-KR3 Unified v1',selected=selected,
            source_scope=SCOPE,combined=cs[selected],formal_credit=0,prospective_boundary_required_after_merge=True))
    put(OUT/'FINAL_STATUS.json',dict(strategy_name=('Squeeze-KR3 Unified v1' if selected!='CAPREUSE' else None),selected_incumbent=selected,state=state,
        formal_credit=0,Q_track_touched=False,prospective_boundary_required=(selected!='CAPREUSE'),report_only=True))
    lines=['# Squeeze-KR3 true-component Unified — saved-only closure','',('Squeeze-KR3 Unified = 생성됨' if selected!='CAPREUSE' else 'Squeeze-KR3 Unified = 생성안됨'),'',f'- 선택: `{selected}`',f'- 상태: `{state}`','',
      '|후보|Combined net|Combined cost2|Weighted WR|Worst-period DD|Eligible|','|---|---:|---:|---:|---:|---|']
    for name,c in [('CAPREUSE',p)]+[(v,cs[v]) for v in VARIANTS]:
        lines.append(f"|{name}|{c['combined_terminal_net_bps']:.2f}|{c['combined_cost2_bps']:.2f}|{100*(c['weighted_win_rate'] or 0):.2f}%|{c['worst_period_DD_bps']:.2f}|{c.get('eligible',True)}|")
    lines+=['','## 기간별']
    for name,c in [('CAPREUSE',p)]+[(v,cs[v]) for v in VARIANTS]:
        for period in PERIODS:
            x=c['per_period'][period]
            wr='NA' if x['win_rate'] is None else f"{100*x['win_rate']:.2f}%"
            pf='NA' if x['PF'] is None else f"{x['PF']:.3f}"
            payoff='NA' if x['payoff'] is None else f"{x['payoff']:.3f}"
            lines.append(f"- {name} {period}: closed/open={x['closed']}/{x['open']}, WR={wr}, net={x['terminal_net_bps']:.2f}, cost2={x['terminal_cost2x_net_bps']:.2f}, PF={pf}, payoff={payoff}, DD={x['marked_DD_bps']:.2f}")
    lines+=['','## Component accounting']
    for v in VARIANTS:
        c=cs[v];d=c['component_bridge']
        lines.append(f"- {v}: K1 veto={c['k1_veto_T']}, K2 arm={c['k2_arm_T']}, K2 trigger={c['k2_trigger_T']}, two-period net delta={d['terminal_delta_bps']:.2f}bps, reduced-loss gross={d['reduced_existing_loss_gross_bps']:.2f}, extended-winner gross={d['extended_existing_win_gross_bps']:.2f}, cut-winner gross={d['cut_existing_win_gross_bps']:.2f}, added-loss gross={d['added_existing_loss_gross_bps']:.2f}, occupancy net={d['occupancy_new_excluded_net_bps']:.2f}")
    lines+=['','candidate85/eval153 no-output wiring failure is preserved. Closure economic reruns=0. All measured U1/U2/U3 evidence is USED_DEV/formal_credit=0; Top6 fresh/Q/G5 data was not accessed.']
    (OUT/'REPORT_KO.md').write_text('\n'.join(lines)+'\n')
    commit=persist('Close saved-only Squeeze/KR3 Unified selection')
    print(json.dumps(dict(selected=selected,state=state,commit=commit,parent_net=p['combined_terminal_net_bps'],candidate_net={v:cs[v]['combined_terminal_net_bps'] for v in VARIANTS}),sort_keys=True))

if __name__=='__main__': main()
