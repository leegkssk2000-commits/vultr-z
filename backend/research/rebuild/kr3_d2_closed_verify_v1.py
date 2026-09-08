"""Verify D2's closed two-run scope from saved ledgers, without strategy replay."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
from backend.research.rebuild import kr3_d2_failure_study_v1 as m

FILES = ('ACCOUNTING.json', 'REPORT.md', 'CLOSED_ACCOUNTING.json', 'INTERPRETATION.md')
WIN_FIELDS = ['entry_ts','entry_price','exit_ts','exit_price','gross_bps','net_bps',
 'cost_bps','cost2x_net_bps','fee_bps','funding_bps','mfe_bps','mae_bps','exit_anchor_index',
 'runner_extension','low_exit_state','hold_ms','frozen_signal_low']

def read(path):
    data = Path(path).read_bytes()
    return json.loads(gzip.decompress(data) if str(path).endswith('.gz') else data)

def validate_budget(budget, spec):
    slot = budget[m.KEY]
    m.need(slot['scope']==m.SCOPE and slot['specification_sha256']==spec['receipt_sha256'], 'BUDGET_SCOPE_BINDING')
    m.need(slot['used']==slot['completed']==slot['max_executions']==2 and slot['max_candidates']==1 and slot['no_retry'] is True, 'ALLOCATION_2_OF_2')
    m.need(budget['cumulative_actual']>=47 and budget['cumulative_actual_evaluations']>=68,'COUNTERS_BELOW_COMPLETED_SCOPE')
    for ordinal, period in ((67,'DEV2025'),(68,'SEEN2026')):
        found=[v for v in budget['trials'] if v['actual_experiment_ordinal']==ordinal]
        m.need(len(found)==1 and found[0]['scope']==m.SCOPE and found[0]['period']==period and found[0]['specification_sha256']==spec['receipt_sha256'], 'EXACT_COMPLETED_TRIAL')
    cand=[v for v in budget['candidate_trials'] if v['ordinal']==47]
    m.need(len(cand)==1 and cand[0]['candidate']==m.c.CANDIDATE and cand[0]['scope']==m.SCOPE,'EXACT_CANDIDATE')

def verify_bound_files(root):
    manifest=read(root/'SUMMARY_BINDING.json')
    m.need(set(manifest['files_sha256'])==set(FILES), 'SUMMARY_FILE_SET')
    for name,digest in manifest['files_sha256'].items():
        m.need(hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,'SUMMARY_BYTES_DRIFT:'+name)

def verify():
    root=m.ROOT/m.OUT;spec=read(root/'SPEC.json')
    m.need(m.saved_check(spec)['completed']==2,'TWO_COMPLETED_RESULTS_REQUIRED')
    validate_budget(read(m.ROOT/m.p.BUDGET),spec)
    verify_bound_files(root)
    accounting=read(root/'ACCOUNTING.json');closed=read(root/'CLOSED_ACCOUNTING.json')
    for period in m.RUNS:
        folder=root/period;at=read(folder/'ATTEMPT.json');started=read(folder/'EXECUTION_STARTED.json');receipt=read(folder/'RECEIPT.json')
        m.need(at['scope']==m.SCOPE and at['period']==period and at['github_run_attempt']=='1','ATTEMPT_BINDING')
        m.need(at['specification_sha256']==spec['receipt_sha256'] and receipt['specification_sha256']==spec['receipt_sha256'],'ATTEMPT_SPEC_BINDING')
        m.need(started['reservation_commit']==receipt['reservation_commit'] and started['run']==at['github_run_id'],'EXECUTION_RESERVATION_BINDING')
        base=m.ROOT/m.p.CAMPAIGN
        d=read(base/('MECHANISM_SEPARATION/W6_RECHECK_SHIFTED_EXIT_ANCHOR/RESULT.json.gz' if period=='DEV2025' else 'D_PARENT_2026/RESULT.json.gz'))
        child=read(folder/'RESULT.json.gz')
        kr3=m.a.normalize_kr3(read(m.ROOT/'research/development_evidence/FOCUSED_REPAIR_20260907_V1/KR3'/f'{period}.json.gz'))
        expected=accounting[period]
        m.need(m.p.sha(expected['D_to_D2'])==m.p.sha(m.a.compare(d,child)),'D_ACCOUNTING_SEMANTICS')
        m.need(m.p.sha(expected['KR3_to_D2'])==m.p.sha(m.a.compare(kr3,child)),'KR3_ACCOUNTING_SEMANTICS')
        m.need(m.p.sha(expected['repair_cohorts'])==m.p.sha(m.a.repair_cohorts(kr3,d,child)),'REPAIR_COHORT_SEMANTICS')
        m.need(expected['snapshots']=={n:m.a.snapshot(v) for n,v in [('KR3',kr3),('D',d),('D2',child)]},'SNAPSHOT_SEMANTICS')
        sd,sc=expected['snapshots']['D'],expected['snapshots']['D2']
        checks={'positive_terminal_net':sc['terminal_net_bps']>0,'positive_all_cost2':sc['terminal_cost2x_net_bps']>0,'net_not_worse_D':sc['terminal_net_bps']>=sd['terminal_net_bps'],'cost2_not_worse_D':sc['terminal_cost2x_net_bps']>=sd['terminal_cost2x_net_bps'],'DD_not_worse_D':sc['marked_DD_trade_sum_bps']<=sd['marked_DD_trade_sum_bps']}
        m.need(checks==expected['checks'],'CHECK_RESULTS_SEMANTICS')
        m.need(d['reference_events']==child['reference_events'] and d['reference_opportunities']==child['reference_opportunities'],'UNCHANGED_REFERENCE_LIFECYCLE')
        key=lambda t:(t['symbol'],t['mechanism_origin_id'])
        ds,cs=({key(t):t for t in v['trades']} for v in (d,child))
        m.need(len(ds)==len(d['trades']) and len(cs)==len(child['trades']) and ds.keys()==cs.keys(),'CLOSED_ORIGIN_PARITY')
        m.need(all(all(v[f]==cs[k][f] for f in ('entry_ts','entry_price','decision_index','exit_anchor_index')) for k,v in ds.items()),'UNCHANGED_ENTRY_GEOMETRY')
        winners=[k for k,v in ds.items() if v['net_bps']>0]
        m.need(all(all(ds[k].get(f)==cs[k].get(f) for f in WIN_FIELDS) for k in winners),'WINNER_ECONOMIC_PARITY')
        changes=[{'origin':k[1],'symbol':k[0],'parent_net_bps':ds[k]['net_bps'],'child_net_bps':cs[k]['net_bps'],'delta_bps':cs[k]['net_bps']-ds[k]['net_bps']} for k in ds if ds[k]['net_bps']!=cs[k]['net_bps']]
        record=closed[period]
        m.need(record['changes']==changes and record['winner_economic_fields_preserved']==len(winners),'DETAILED_EXIT_ATTRIBUTION')
        m.need(record['parent_grouped_max_loss']==d['metrics']['closed_loss_groups']['max_loss_trade_sum_bps'] and record['child_grouped_max_loss']==child['metrics']['closed_loss_groups']['max_loss_trade_sum_bps'],'LOSS_RUN_RISK_RECORDED')
    return {'scope':m.SCOPE,'completed_economic_runs':2,'replayed_economic_runs':0,'summaries_verified':True,'formal_pass':False}

if __name__=='__main__':
    print(json.dumps(verify(),sort_keys=True))
