"""Saved-only closure for Issue #1294.

Reads completed U4 evidence and frozen parent/donor receipts. No strategy replay or economic allocation.
"""
import hashlib,json,math,subprocess
from decimal import Decimal
from math import fsum
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
SCOPE='SQUEEZE_KR3_CORE_PLUS_C54_NATIVE_SLEEVE_AFTER_PR1293_V1'
OUT=ROOT/'research/development_evidence'/SCOPE
CAP=ROOT/'research/development_evidence/C70_TM_PARTIAL_CAPACITY_REUSE_AFTER_PR1260_V1'
C54=ROOT/'research/development_evidence/KR3_C51_ENTRY_CONTEXT_AB_AFTER_PR1225_V1/B'
PERIODS=('DEV2025','SEEN2026')
KEY='squeeze_kr3_native_sleeve_1294_allocation'
BRANCH='codex/squeeze-kr3-native-sleeve-1294'


def need(ok,msg):
    if not ok: raise RuntimeError(msg)

def read(path): return json.loads(Path(path).read_text())
def canon(obj): return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while True:
            b=f.read(1024*1024)
            if not b: break
            h.update(b)
    return h.hexdigest()
def put(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(canon(obj)+b'\n')
def git(*args): return subprocess.check_output(['git',*args],cwd=ROOT,text=True,timeout=45).strip()
def persist(msg):
    git('add','--',str(OUT.relative_to(ROOT)));git('commit','-m',msg+' [skip ci]')
    head=git('rev-parse','HEAD');git('push','origin','HEAD:refs/heads/'+BRANCH)
    remote=git('ls-remote','origin','refs/heads/'+BRANCH).split()[0];need(head==remote,'REMOTE_READBACK_MISMATCH')
    return head

def wins(snapshot):
    if snapshot['win_rate'] is None:return 0
    w=round(int(snapshot['closed'])*float(snapshot['win_rate']))
    need(math.isclose(w/int(snapshot['closed']),float(snapshot['win_rate']),rel_tol=1e-12,abs_tol=1e-12),'WIN_RATE_COUNT_MISMATCH')
    return w

def D(v): return Decimal(str(v))


def main():
    spec=read(OUT/'SPEC.json');budget=read(OUT/'BUDGET.json');q=budget[KEY]
    need((q['reserved'],q['started'],q['completed'],q['failed'],q['remaining'])==(2,2,2,0,0),'BUDGET_NOT_TERMINAL_CLEAN')
    need((budget['cumulative_actual'],budget['cumulative_actual_evaluations'])==(89,161),'ORDINALS_NOT_89_161')
    for per in PERIODS:
        need(sha(CAP/per/'RESULT.json.gz')==spec['core_result_sha256'][per],'CORE_RESULT_DRIFT:'+per)
        need(sha(CAP/per/'SNAPSHOT.json')==spec['core_snapshot_sha256'][per],'CORE_SNAPSHOT_DRIFT:'+per)
        need(sha(C54/per/'RESULT.json.gz')==spec['donor_result_sha256'][per],'DONOR_RESULT_DRIFT:'+per)
        need(sha(C54/per/'RAW.json.gz')==spec['donor_raw_sha256'][per],'DONOR_RAW_DRIFT:'+per)
        need(sha(ROOT/'research/development_evidence/TOP5_SOURCE_CHART_MECHANISMS_AFTER_PR1228_V1/INPUTS'/(per+'.json.gz'))==spec['input_packet_sha256'][per],'INPUT_DRIFT:'+per)
    perdata={};parentdata={};receipts={};bridge_residuals={}
    for per in PERIODS:
        folder=OUT/per;rec=read(folder/'RECEIPT.json');need(rec['state']=='COMPLETED','RECEIPT_NOT_COMPLETED:'+per)
        for fn,key in [('RESULT.json.gz','result_sha256'),('SNAPSHOT.json','snapshot_sha256'),('DECOMPOSITION.json','decomposition_sha256'),('ARBITRATION.json.gz','arbitration_sha256')]:
            need(sha(folder/fn)==rec[key],'SAVED_HASH:'+per+':'+fn)
        s=read(folder/'SNAPSHOT.json');p=read(CAP/per/'SNAPSHOT.json')
        need(float(s['core_retention_fraction'])==1.0,'CORE_RETENTION:'+per)
        delta=D(s['terminal_net_bps'])-D(p['terminal_net_bps'])
        contrib=D(s['donor_net_contribution_bps'])
        bysymbol=sum((D(v) for v in s['donor_net_by_symbol'].values()),Decimal(0))
        delta_residual=delta-contrib; symbol_residual=contrib-bysymbol
        need(delta_residual==0,'DONOR_NET_DELTA_BRIDGE:'+per+':'+str(delta_residual))
        need(abs(symbol_residual)<=Decimal('0.00000001'),'DONOR_SYMBOL_BRIDGE:'+per+':'+str(symbol_residual))
        need(int(s['donor_accepted_T'])==int(s['donor_natural_T'])+int(s['donor_preempted_T']),'DONOR_COUNT_BRIDGE:'+per)
        eligible=float(s['terminal_net_bps'])>0 and float(s['terminal_cost2x_net_bps'])>0 and s['PF'] is not None and float(s['PF'])>=1 and int(s['donor_accepted_T'])>=1
        need(eligible,'PERIOD_ELIGIBILITY_FAIL:'+per)
        bridge_residuals[per]=dict(serialized_net_delta=str(delta),serialized_donor_contribution=str(contrib),delta_residual=str(delta_residual),symbol_sum_residual=str(symbol_residual))
        perdata[per]=s;parentdata[per]=p;receipts[per]=sha(folder/'RECEIPT.json')
    parent_net=fsum(float(parentdata[p]['terminal_net_bps']) for p in PERIODS)
    child_net=fsum(float(perdata[p]['terminal_net_bps']) for p in PERIODS)
    parent_cost2=fsum(float(parentdata[p]['terminal_cost2x_net_bps']) for p in PERIODS)
    child_cost2=fsum(float(perdata[p]['terminal_cost2x_net_bps']) for p in PERIODS)
    parent_closed=sum(int(parentdata[p]['closed']) for p in PERIODS);child_closed=sum(int(perdata[p]['closed']) for p in PERIODS)
    parent_wins=sum(wins(parentdata[p]) for p in PERIODS);child_wins=sum(wins(perdata[p]) for p in PERIODS)
    selected='U4' if child_net>parent_net else 'CAPREUSE'
    state='SELECTED_SQUEEZE_KR3_UNIFIED_V1' if selected=='U4' else 'KEEP_CAPREUSE_AND_C54_SEPARATE'
    need(selected=='U4','FROZEN_ADOPTION_CONTRACT_NOT_MET')
    summary=dict(schema='zel.squeeze_kr3.native_sleeve.saved_close.v1',scope=SCOPE,candidate_ordinal=89,evaluations=[160,161],
        selected=selected,state=state,parent_combined_net_bps=parent_net,U4_combined_net_bps=child_net,
        combined_net_delta_bps=child_net-parent_net,combined_net_improvement_fraction=(child_net-parent_net)/parent_net,
        parent_combined_cost2_bps=parent_cost2,U4_combined_cost2_bps=child_cost2,
        combined_cost2_delta_bps=child_cost2-parent_cost2,
        parent_weighted_WR=parent_wins/parent_closed,U4_weighted_WR=child_wins/child_closed,
        parent_worst_period_DD_bps=max(float(parentdata[p]['marked_DD_trade_sum_bps']) for p in PERIODS),
        U4_worst_period_DD_bps=max(float(perdata[p]['marked_DD_trade_sum_bps']) for p in PERIODS),
        core_retention_fraction=1.0,donor_accepted_T=sum(int(perdata[p]['donor_accepted_T']) for p in PERIODS),
        donor_natural_T=sum(int(perdata[p]['donor_natural_T']) for p in PERIODS),
        donor_preempted_T=sum(int(perdata[p]['donor_preempted_T']) for p in PERIODS),
        donor_excluded_T=sum(int(perdata[p]['donor_excluded_T']) for p in PERIODS),
        serialized_bridge_residuals=bridge_residuals,
        per_period=perdata,parent_per_period=parentdata,formal_credit=0,used_DEV=True,Q_track_touched=False,
        new_economic_execution_in_closure=0,automatic_successor=False)
    put(OUT/'SUMMARY.json',summary)
    seal=dict(schema='zel.squeeze_kr3.unified_v1.native_sleeve.seal.v1',strategy_name='Squeeze-KR3 Unified v1',
        architecture='CAPREUSE82_IMMUTABLE_CORE_PRIORITY_OR_EXACT_C54_NATIVE_DONOR_SLEEVE',candidate_ordinal=89,
        result_receipts=receipts,combined_net_bps=child_net,combined_cost2_bps=child_cost2,weighted_WR=child_wins/child_closed,
        worst_period_DD_bps=summary['U4_worst_period_DD_bps'],core_retention_fraction=1.0,formal_credit=0,
        historical_used_dev_only=True,prospective_boundary_required_after_merge=True)
    put(OUT/'INCUMBENT_SEAL.json',seal)
    put(OUT/'FINAL_STATUS.json',dict(strategy_name='Squeeze-KR3 Unified v1',selected_incumbent='U4',state=state,
        formal_credit=0,Q_track_touched=False,prospective_boundary_required=True,report_only=True))
    put(OUT/'STATUS.json',dict(scope=SCOPE,state=state,selected='U4',formal_credit=0,report_only=True,
        economic_FULL_count=2,new_economic_execution_in_closure=0,remaining_execution=[]))
    lines=['# Squeeze-KR3 native-sleeve Unified — saved-only closure','',
      'Squeeze-KR3 Unified = 생성됨','',
      f'- combined net: {parent_net:.2f} → **{child_net:.2f} bps** ({child_net-parent_net:+.2f}, {(child_net-parent_net)/parent_net*100:+.2f}%)',
      f'- combined cost2: {parent_cost2:.2f} → **{child_cost2:.2f} bps** ({child_cost2-parent_cost2:+.2f})',
      f'- weighted WR: {parent_wins/parent_closed*100:.2f}% → **{child_wins/child_closed*100:.2f}%**',
      f'- worst-period marked DD: {summary["parent_worst_period_DD_bps"]:.2f} → **{summary["U4_worst_period_DD_bps"]:.2f} bps**',
      f'- donor accepted/natural/preempted/excluded: {summary["donor_accepted_T"]}/{summary["donor_natural_T"]}/{summary["donor_preempted_T"]}/{summary["donor_excluded_T"]}',
      '', '|Period|CAP net|U4 net|Δ net|CAP WR|U4 WR|CAP PF|U4 PF|CAP DD|U4 DD|donor accepted/preempted|',
      '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for per in PERIODS:
        p0=parentdata[per];c=perdata[per]
        lines.append(f"|{per}|{p0['terminal_net_bps']:.2f}|{c['terminal_net_bps']:.2f}|{c['terminal_net_bps']-p0['terminal_net_bps']:+.2f}|{p0['win_rate']*100:.2f}%|{c['win_rate']*100:.2f}%|{p0['PF']:.3f}|{c['PF']:.3f}|{p0['marked_DD_trade_sum_bps']:.2f}|{c['marked_DD_trade_sum_bps']:.2f}|{c['donor_accepted_T']}/{c['donor_preempted_T']}|")
    lines+=['','Core CAPREUSE campaign retention=100%. U4 uses exact saved C54 actual donor campaigns only, with chronological same-symbol core-priority arbitration. DD/exposure increase is retained as an explicit tradeoff; WR is not a hard non-degradation gate under the pre-outcome contract. All evidence is USED_DEV/formal_credit=0; fresh/Q/G5 data access=0.']
    (OUT/'REPORT_KO.md').write_text('\n'.join(lines)+'\n')
    commit=persist('Seal saved-only Squeeze-KR3 Unified v1')
    print(json.dumps(dict(state=state,selected='U4',commit=commit,parent_net=parent_net,U4_net=child_net,delta=child_net-parent_net),sort_keys=True))

if __name__=='__main__':main()
