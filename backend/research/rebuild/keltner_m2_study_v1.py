"""Single authorized M2 context study: bounded inputs, immutable outputs, one writer."""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import gzip
import json
import math
import os
from pathlib import Path
import time

from backend.research.rebuild import keltner_m2_context_v1 as overlay
from backend.research.rebuild import keltner_opportunity_reservation_v1 as m

old, ROOT = m.old, m.ROOT
account = m.prior.previous
metrics = account.metrics
OUTPUT = 'research/development_evidence/KELTNER_M2_CONTEXT_20260907_V1'
SPEC = OUTPUT+'/SPEC.json'
PARENT_SEAL = 'b86757d2271190ffa85d78f01879b3fce57365b6ce03b46f78aff73e011199fe'
CODE = ['backend/research/rebuild/'+p+'_v1.py' for p in
        ('keltner_m2_context','keltner_m2_study','test_keltner_m2_context')]
AUTH = {**m.AUTH, 'comparison_type':'EXIT_CHANGE', 'change_axis':'FIRST_LOW_BREACH_ONCE_CLOSE_BELOW_EMA50_NEXT_OPEN',
        'new_alpha_candidate':False}
RULE = {'parent':'PR1198_M_PARTIAL_DEVELOPMENT_WORKCOPY_RETAINED',
        'low':'ORIGINAL_COMPLETED_ENTRY_SIGNAL_BAR_LOW_FROZEN_BEFORE_ENTRY',
        'trigger':'FIRST_M1_ONLY_COMPLETED_LOW_BREACH; CLOSE_STRICTLY_BELOW_EMA50_ONCE',
        'suppression':'FIRST_CLOSE_GE_EMA50_PERMANENTLY_SUPPRESSES_THIS_POSITION; NO_REARM',
        'fill':'NEXT_OBSERVED_OPEN_STRICTLY_BEFORE_END',
        'priority':'PRIOR_CLOSE_ORDER_AT_OPEN; D_WINS_SAME_TRIGGER; TIMEOUT_CLOSE_BEFORE_NEW_TRIGGER',
        'reference':'UNCHANGED_M_CAUSAL_CLOCK; ACTUAL_M2_EXIT_CANNOT_RELEASE',
        'no_next_open':'PENDING_OPEN_MARK_NOT_FORCED_CLOSED',
        'cost':'UNCHANGED_AUTHORITY_FLOOR20_FUNDING_TO_ACTUAL_EXIT_FULL_COST2',
        'additional_candidate':False, 'numeric_sweep':False, 'native_protective_SL':None}
GOAL = {**metrics.GOAL,
        'focus_2026':'REPORT_CLOSED_AND_TERMINAL_BASE_AND_COST2_DEFICIT_REDUCTION_SEPARATELY',
        'preserve_2025':'REPORT_M_NET_AMOUNT_FRACTION_AND_POSITIVE_TERMINAL_BASE_COST2; NO_POSTHOC_TOLERANCE',
        'workcopy':'NO_AUTOMATIC_REPLACEMENT; UNFAVORABLE_RESULT_RETAINS_M'}


def authorize():
    c=old.read(SPEC); old.probe.verify_seal(c,'M2_SPEC')
    if (c['rule']!=RULE or c['goal']!=GOAL or c['candidate_cumulative_before']!=31
            or c['candidate_ordinal']!=32 or c['allocated_new_candidates']!=1
            or c['M1_control_seal']!=M1_SEAL or c['new_M2_outcomes_seen_at_freeze'] is not False or c['parent_seal']!=PARENT_SEAL):
        raise RuntimeError('M2_RULE_ALLOCATION')
    for k,v in AUTH.items():
        if c.get(k)!=v: raise RuntimeError('M2_AUTHORITY:'+k)
    if set(c['code_files_sha256'])!=set(CODE): raise RuntimeError('M2_CODE_COVERAGE')
    for p,h in {**c['preserved_files_sha256'],**c['code_files_sha256'],**c['ci_files_sha256']}.items():
        if old.file_sha(ROOT/p)!=h: raise RuntimeError('M2_BYTES:'+p)
    if old.file_sha(ROOT/(OUTPUT+'/DESIGN.md'))!=c['design_sha256']:
        raise RuntimeError('M2_DESIGN_BYTES')
    mc=old.read(m.SPEC)
    for k in ('calendars','symbols','data_sha256','cost_sha256','period_data_sha256'):
        if c[k]!=mc[k]: raise RuntimeError('M2_PARENT_INPUT:'+k)
    return c


M1_OUTPUT = 'research/development_evidence/KELTNER_M1_SIGNAL_LOW_20260907_V1'
M1_SEAL = '4a682681ae571e43bf9dde156e8013d2a24089ac7348a0f513a0f694229e3142'


def stored_m1():
    r=old.read(M1_OUTPUT+'/receipt.json'); old.probe.verify_seal(r,'M2_M1_CONTROL')
    if r['receipt_sha256']!=M1_SEAL or r['candidate_cumulative_after']!=31:
        raise RuntimeError('M2_M1_CONTROL_RESULT')
    return {p:json.loads(gzip.decompress((ROOT/r['artifacts'][p]['path']).read_bytes()))
            for p in ('DEV2025','SEEN2026')}


def context_effects(parent,child,effects):
    decisions=[t for t in child['trace'] if t['kind']==overlay.DECISION]
    entries=effects['entries']; positives=[e for e in entries if e['net_delta']>0]
    top=max(positives,key=lambda e:e['net_delta']) if positives else None
    increment=sum(e['net_delta'] for e in entries)
    def group(large):
        es=[e for e in entries if e['parent_kind']=='trades' and e['parent_net_or_mark']>0 and e['parent_large_winner']==large]
        original=sum(e['parent_net_or_mark'] for e in es)
        retained=sum(min(e['parent_net_or_mark'],max(0.,e['child_net_or_mark'])) for e in es)
        return {'T':len(es),'parent_positive_amount':original,'child_signed_amount':sum(e['child_net_or_mark'] for e in es),
                'capped_preserved_amount':retained,'capped_preserved_fraction':retained/original if original else None,
                'profit_cut_including_loss_extension':sum(max(0.,-e['net_delta']) for e in es),
                'winner_to_loss_T':sum(e['child_net_or_mark']<0 for e in es)}
    return {'first_decision_T':len(decisions),'allowed_T':sum(t['status']==overlay.ALLOWED for t in decisions),
            'suppressed_T':sum(t['status']==overlay.SUPPRESSED for t in decisions),
            'no_first_standalone_breach_T':len(entries)-len(decisions),
            'ordinary_winners':group(False),'large_winners':group(True),
            'helpful_T':sum(e['net_delta']>0 for e in entries),'harmful_T':sum(e['net_delta']<0 for e in entries),
            'unchanged_T':sum(e['net_delta']==0 for e in entries),
            'loser_to_winner_T':sum(e['parent_net_or_mark']<0<e['child_net_or_mark'] for e in entries),
            'largest_positive_contribution':top,
            'largest_positive_share_of_net_increment':top['net_delta']/increment if top and increment else None,
            'increment_without_largest_positive':increment-(top['net_delta'] if top else 0.),
            'post_outcome_diagnostic_selected_rule':True,'independent':False}


def stored():
    r=old.read(m.OUTPUT+'/receipt.json'); old.probe.verify_seal(r,'M2_PARENT')
    if r['receipt_sha256']!=PARENT_SEAL or r['candidate_cumulative_after']!=30:
        raise RuntimeError('M2_PARENT_RESULT')
    return {p:json.loads(gzip.decompress((ROOT/r['artifacts'][p]['path']).read_bytes()))
            for p in ('DEV2025','SEEN2026')}


def entry_parity(a,b):
    def keys(view):
        return {(t['symbol'],t['signal_index']):(t['origin_key'],t['entry_ts'],t['entry_price'])
                for k in ('trades','open_observations') for t in view[k]}
    if keys(a)!=keys(b): raise RuntimeError('M2_ENTRY_IDENTITY_DRIFT')
    for k in ('reference_events','reference_opportunities','reference_states'):
        if a[k]!=b[k]: raise RuntimeError('M2_REFERENCE_DRIFT:'+k)
    e=lambda v:[(t['symbol'],t['signal_ts'],t['admission'],t.get('exclusion_reason')) for t in v['events']]
    if e(a)!=e(b): raise RuntimeError('M2_SIGNAL_ADMISSION_DRIFT')


def replay(rows_by,bundles,costs,policy,start,end,*,fixed=None):
    answer={k:[] for k in ('trades','open_observations','events','trace','reference_events','reference_opportunities')}
    answer.update(admission={},reference_states={})
    for symbol,rows in sorted(rows_by.items()):
        raw=overlay.replay(rows,bundles[symbol],eval_start_ms=start,eval_end_ms=end,
                          fixed_signal_indices=None if fixed is None else fixed[symbol])
        value=m.charge(raw,symbol,policy,costs,rows)
        for k,seal in (('trades','trade_sha256'),('open_observations','observation_sha256')):
            for t in value[k]:
                t.pop(seal,None); t.update(candidate_id=overlay.RULE_ID,comparison_type='EXIT_CHANGE',
                    evidence_type='REUSED_DEV_M2_SIGNAL_LOW_EXIT',comparison_stage='M2',scenario='M2')
                t[seal]=old.digest(t)
        for k in ('events','trace'):
            for t in value[k]: t.update(comparison_stage='M2',scenario='M2')
        for k in answer:
            if k not in ('admission','reference_states'): answer[k].extend(value[k])
        answer['admission'][symbol]=value['audit']; answer['reference_states'][symbol]=value['reference_state']
    return answer


def intervention(parent,child,p_reference):
    def idx(view):
        return {t['origin_key']:(k,t) for k in ('trades','open_observations') for t in view[k]}
    pp,cc,original=idx(parent),idx(child),idx(p_reference)
    val=lambda k,t: t['net_bps'] if k=='trades' else t['hypothetical_liquidation_net_mark_bps']
    cost=lambda k,t: t['cost_bps'] if k=='trades' else t['hypothetical_liquidation_cost_bps']
    winners=sorted([t for t in parent['trades'] if t['net_bps']>0],key=lambda t:(-t['net_bps'],t['origin_key']))
    large={t['origin_key'] for t in winners[:math.ceil(len(winners)*.1)]}
    traces={}
    for t in child['trace']: traces.setdefault((t['symbol'],t['signal_index']),[]).append(t)
    refs={(t['symbol'],t['reference_signal_index']):t for t in child['reference_opportunities']}
    effects=[];groups={}; entry_months={}
    for origin,(pk,p) in pp.items():
        ck,c=cc[origin]; events=traces.get((p['symbol'],p['signal_index']),[])
        trigger=[e for e in events if e['kind']==overlay.TRIGGER]
        ties=[e for e in events if e['kind']=='TREND_INVALIDATION_CLOSE' and e.get('low_condition')]
        parent_changed=False; category='NEW_TO_P'
        if origin in original:
            ok,o=original[origin]
            parent_changed=pk!=ok or p.get('exit_ts')!=o.get('exit_ts') or p.get('exit_price')!=o.get('exit_price')
            delta_to_P=val(pk,p)-val(ok,o)
            category=('HELPFUL_D_EXIT' if delta_to_P>0 else 'HARMFUL_D_EXIT') if parent_changed else (
                'UNCHANGED_EXIT_LOSS' if val(pk,p)<0 else 'UNCHANGED_EXIT_NONLOSS')
        if pk!='trades': category='PARENT_OPEN'
        pv,cv=val(pk,p),val(ck,c); ref=refs[p['symbol'],p['signal_index']]
        actual_exit=c.get('exit_ts',c.get('mark_ts'))
        release=ref['release_ts'] if ref['release_ts'] is not None else child['admission'][p['symbol']]['common_end_mark_ts']
        wait=max(0,release-actual_exit) if ck=='trades' else 0
        effect={'origin_key':origin,'symbol':p['symbol'],'signal_index':p['signal_index'],
            'entry_ts':p['entry_ts'],'parent_kind':pk,'child_kind':ck,'parent_net_or_mark':pv,'child_net_or_mark':cv,
            'net_delta':cv-pv,'cost_saving_already_in_net':cost(pk,p)-cost(ck,c),
            'parent_category':category,'parent_large_winner':origin in large,
            'M2_triggered':bool(trigger),'M2_trigger_events':trigger,'D_priority_overlap_events':ties,
            'M2_executed':c.get('exit_reason')==overlay.EXIT,
            'reference_retained_after_actual_exit_ms':wait,
            'original_timeout_loss':pk=='trades' and pv<0 and any(e['kind']=='ORIGINAL_TIME_STOP_CLOSE'
                for e in parent['trace'] if e['symbol']==p['symbol'] and e['signal_index']==p['signal_index'])}
        effects.append(effect)
        month=datetime.fromtimestamp(p['entry_ts']/1000,timezone.utc).strftime('%Y-%m')
        em=entry_months.setdefault(month,{'T':0,'M_net_or_mark':0.,'M2_net_or_mark':0.,'delta':0.})
        em['T']+=1;em['M_net_or_mark']+=pv;em['M2_net_or_mark']+=cv;em['delta']+=cv-pv
        g=groups.setdefault(category,{'T':0,'triggered_T':0,'parent_net_or_mark':0.,'child_net_or_mark':0.,'delta':0.})
        g['T']+=1;g['triggered_T']+=bool(trigger);g['parent_net_or_mark']+=pv;g['child_net_or_mark']+=cv;g['delta']+=cv-pv
    return {'entries':effects,'groups':groups,'entry_month_cohorts':entry_months,
        'triggered_T':sum(e['M2_triggered'] for e in effects),
        'trigger_count_semantics':'M2_PRIORITY_TRIGGER; LOW_PLUS_EMA_REPORTED_SEPARATELY_AS_D_PRIORITY_OVERLAP',
        'untriggered_T':sum(not e['M2_triggered'] for e in effects),
        'executed_M2_T':sum(e['M2_executed'] for e in effects),
        'D_priority_overlap_T':sum(bool(e['D_priority_overlap_events']) for e in effects),
        'original_timeout_loss_T':sum(e['original_timeout_loss'] for e in effects),
        'original_timeout_loss_triggered_T':sum(e['original_timeout_loss'] and e['M2_triggered'] for e in effects),
        'original_timeout_loss_delta':sum(e['net_delta'] for e in effects if e['original_timeout_loss']),
        'winner_profit_cut':sum(max(0,e['parent_net_or_mark']-e['child_net_or_mark']) for e in effects if e['parent_kind']=='trades' and e['parent_net_or_mark']>0),
        'large_winner_profit_cut':sum(max(0,-e['net_delta']) for e in effects if e['parent_large_winner']),
        'entry_identities_unchanged':True,'reference_events_unchanged':True,
        'post_outcome_labels_are_execution_features':False,'new_or_removed_entries_T':0}


def artifact(name,value,verify):
    p=ROOT/OUTPUT/name; raw=old.probe.canonical(value)
    payload=p.read_bytes() if p.exists() else gzip.compress(raw,mtime=0)
    if gzip.decompress(payload)!=raw: raise RuntimeError('M2_REPLAY_DRIFT:'+name)
    old.probe.write_immutable(p,payload,verify_only=verify)
    return {'path':str(p.relative_to(ROOT)),'file_sha256':old.file_sha(p)}


def log(phase,**kw):
    print(json.dumps({'phase':phase,'utc':datetime.now(timezone.utc).isoformat(),'pid':os.getpid(),
        'github_run_id':os.environ.get('GITHUB_RUN_ID'),'github_run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT'),**kw}),flush=True)


def run(data_dir,verify_only=False):
    began=time.monotonic();c=authorize(); out=ROOT/OUTPUT
    if (out/'receipt.json').exists()!=verify_only: raise RuntimeError('M2_CONSUMED_OR_MISSING')
    if not verify_only and (out/'ATTEMPT.json').exists(): raise RuntimeError('M2_ATTEMPT_ALREADY_CONSUMED')
    log('START',mode='REPRODUCTION' if verify_only else 'NEW_CANDIDATE32')
    documents=stored(); previous=stored_m1(); base,costs,periods,access=account.load_inputs(Path(data_dir),c)
    mc=old.read(m.SPEC); results={};artifacts={}
    # Consumption precedes the first M2 counterfactual, including partial runs.
    if not verify_only:
        old.probe.write_immutable(out/'ATTEMPT.json',old.probe.canonical({'candidate_ordinal':32,
            'prior_count':31,'new_candidate_attempts':1,'spec_seal':c['receipt_sha256'],
            'started_utc':datetime.now(timezone.utc).isoformat(),'pid':os.getpid(),
            'status':'ATTEMPT_CONSUMED_BEFORE_COUNTERFACTUAL'}))
    for period,(start,end) in c['calendars'].items():
        tick=time.monotonic();log('PERIOD_START',period=period)
        rows=periods[period]; doc=documents[period]; parent=doc['views']['M']
        bundles={s:overlay.parent.build_bundle(v,overlay.d.PARENT_SPEC,eval_start_ms=start,eval_end_ms=end) for s,v in rows.items()}
        original_policy={**base,'batch_id':mc['batch_id'],'receipt_sha256':mc['receipt_sha256'],
            'code_files_sha256':mc['code_files_sha256'],'combined_data_sha256':mc['period_data_sha256'][period],
            'development_interval_ms':[start,end]}
        policy={**original_policy,'batch_id':c['batch_id'],'receipt_sha256':c['receipt_sha256'],'code_files_sha256':c['code_files_sha256']}
        with old.probe.io_boundary([],out):
            disabled=m.replay(rows,bundles,costs,original_policy,start,end)
            if disabled!=parent: raise RuntimeError('M2_DISABLED_EXACT_STORED_M_PARITY')
            full=replay(rows,bundles,costs,policy,start,end);entry_parity(parent,full)
            origins={s:[t['signal_index'] for k in ('trades','open_observations') for t in parent[k] if t['symbol']==s] for s in rows}
            fixed=replay(rows,bundles,costs,policy,start,end,fixed=origins)
            for k in ('trades','open_observations','trace'):
                if fixed[k]!=full[k]: raise RuntimeError('M2_FIXED_FULL_PARITY:'+k)
            ps=doc['record']['stages']['M']
            prior_stage=previous[period]['record']['stages']['M1']
            cs=metrics.build_stage(full['trades'],full['open_observations'],full['events'],rows,costs,policy,c['symbols'],start,end)
            cmp=metrics.compare(ps,cs,parent['trades'],parent['open_observations'],full['trades'],full['open_observations'],rows,costs,start,end)
            effects=intervention(parent,full,doc['views']['P'])
        pv,cv=m.metrics.stage_values(ps),m.metrics.stage_values(cs)
        av=m.metrics.stage_values(prior_stage); av['raw_signal_T']=len(previous[period]['M1_full']['events'])
        context=context_effects(parent,full,effects)
        pv['raw_signal_T']=len(parent['events']);cv['raw_signal_T']=len(full['events'])
        economics=('closed_net_bps','closed_cost2x_net_bps','terminal_net_bps_hypothetical','terminal_cost2x_net_bps_hypothetical')
        focus={key:{'M':pv[key],'M2':cv[key],'delta':cv[key]-pv[key],
                    'M2_fraction_of_M_positive':cv[key]/pv[key] if pv[key]>0 else None,
                    'deficit_reduced':max(0,-pv[key])-max(0,-cv[key]),'remaining_deficit':max(0,-cv[key])} for key in economics}
        record={'period':period,'comparison_type':'EXIT_CHANGE','independent':False,
            'fixed_entry_vs_full':'EXACT_ALL_CLOSED_OPEN_AND_TRACES; SAME_METRICS_NOT_DUPLICATE_TRIAL',
            'disabled_M_exact_parity':True,'reference_and_entry_parity':True,
            'stages':{'M':ps,'M1':prior_stage,'M2':cs},'context_effects':context,'comparison':cmp,'effects':effects,'focus':focus,
            'table':[{'metric':k,'M':pv[k],'M1':av[k],'M2':cv[k],'delta':cv[k]-pv[k] if cv[k] is not None and pv[k] is not None else None,'M2_minus_M1':cv[k]-av[k] if cv[k] is not None and av[k] is not None else None} for k in pv],
            'P_D_N_sealed_reference':{k:m.metrics.stage_values(doc['record']['stages'][k]) for k in ('P','D','N')}}
        artifacts[period]=artifact(period+'.json.gz',{'record':record,'M2_full':full,'M2_fixed':fixed},verify_only)
        summary=deepcopy(record)
        for v in summary['stages'].values():v.pop('daily',None)
        summary['comparison'].pop('same_calendar_windows',None)
        summary['effects'].pop('entries',None)
        results[period]=summary
        log('PERIOD_COMPLETE',period=period,elapsed_seconds=round(time.monotonic()-tick,3),
            net=cv['closed_net_bps'],terminal_cost2=cv['terminal_cost2x_net_bps_hypothetical'],artifact_sha=artifacts[period]['file_sha256'])
    decision={p:r['comparison']['decision'] for p,r in results.items()}
    result=old.seal({**AUTH,'schema':'keltner.m2.context.result.v1','candidate_id':overlay.RULE_ID,
        'candidate_cumulative_before':31,'candidate_cumulative_after':32,'new_candidates_measured':1,
        'remaining_allocated_candidates':0,'candidate_period_applications':2,'fixed_and_full_each_period':True,
        'parent_seal':PARENT_SEAL,'M1_seal':M1_SEAL,'spec_seal':c['receipt_sha256'],'results':results,'artifacts':artifacts,
        'decision_by_period':decision,'automatic_workcopy_replacement':False,'M_preserved':True,
        'source_access':access,'decoded_after_20260905_00UTC':0,'prior_seen_evaluation':'1/1_PRESERVED',
        'prior_independent_comparison':c['prior_independent_comparison'],'Gemini_actual_video':'NOT_RUN',
        'same_result_reproductions_are_new_candidates':False})
    old.probe.write_immutable(out/'receipt.json',old.probe.canonical(result),verify_only=verify_only)
    old.probe.write_immutable(out/'RESULTS.md',report(result),verify_only=verify_only)
    paths=[SPEC,OUTPUT+'/DESIGN.md',OUTPUT+'/ATTEMPT.json',OUTPUT+'/receipt.json',OUTPUT+'/RESULTS.md']+[x['path'] for x in artifacts.values()]
    durable=old.seal({**AUTH,'result_receipt_sha256':result['receipt_sha256'],
        'files_sha256':{p:old.file_sha(ROOT/p) for p in paths},'code_files_sha256':c['code_files_sha256'],
        'preserved_files_sha256':c['preserved_files_sha256']})
    old.probe.write_immutable(out/'durable_receipt.json',old.probe.canonical(durable),verify_only=verify_only)
    log('COMPLETE',elapsed_seconds=round(time.monotonic()-began,3),result_sha=result['receipt_sha256'],
        durable_sha=old.file_sha(out/'durable_receipt.json'),economic_decisions={p:d['decision'] for p,d in decision.items()})
    return result


def report(r):
    fmt=lambda v:'NA' if v is None else f'{v:,.4f}'
    lines=['# M → M2: signal-low completed-close exit','',
        'Equal-nominal trade-bps; not account returns/MDD. Reused data, independent=false. All M entries including winners and open positions are included.','',
        '| Period / metric | M | M1 | M2 | M2-M | M2-M1 |','|---|---:|---:|---:|---:|---:|']
    for p,v in r['results'].items():
        for row in v['table']:lines.append('| '+p+' / '+row['metric']+' | '+' | '.join(fmt(row[k]) for k in ('M','M1','M2','delta','M2_minus_M1'))+' |')
    for p,v in r['results'].items():
        lines+=['',p+' focus, attribution and uncertainty:','','```json',json.dumps({
            'focus':v['focus'],'context_effects':v['context_effects'],'effects':v['effects'],'attribution':v['comparison']['attribution'],
            'net_decomposition':v['comparison']['net_decomposition'],'uncertainty':v['comparison']['uncertainty'],
            'decision':v['comparison']['decision']},indent=2),'```']
    lines+=['','M2 checks price < EMA50 only at the first M1-only completed low breach; rejection permanently suppresses this exit, never rearms. D wins simultaneous conditions and timeout close precedes a new trigger. No native protective SL exists; this is not an exchange stop order.',
        'Full reference-clock replay preserves every M admission and reference event. Fixed-entry output equals full replay for every closed/open position and trace. Early real-model exit stops actual funding/exposure; virtual reservations remain zero economics.',
        'PR1186 Supertrend signal-low fixed-entry delta -4809.587903 trade-bps, winner profit cut11973.979751,17 winner-to-loss conversions, DEV_REJECT is counterevidence. Different M reclaim entry/D exit/N selection/reference ownership is an adaptation, not transferred success.',
        'Frozen research costs,20bps floor and full cost2 apply. Open terminal marks include hypothetical roundtrip cost and are not forced completed trades. No post2026-09-05T00Z or Q0 prospective input decoded. Old seen partition labels retained; no claim of independent OOS.',
        'Per-origin intervention timestamps, unchanged/helpful/harmful/timeout-loss and winner cohorts, retained-reference intervals, same-calendar contribution windows and daily/monthly/symbol concentration are in the two period ledgers. Different maximum episodes are not causal contributions.',
        'Prior31 preserved, M2 ordinal32, remaining0. One economic writer; fixed/full two-period applications and receipt reproductions are not new candidates. No automatic M3 or baseline replacement. execution=NONE/order=BLOCKED/live=BLOCKED, paid external AI0.']
    return ('\n'.join(lines)+'\n').encode()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path);p.add_argument('--verify-only',action='store_true');p.add_argument('--check-only',action='store_true');a=p.parse_args()
    if a.check_only: print(json.dumps({'check':'PASS','spec':authorize()['receipt_sha256']}))
    else:
        if not a.data_dir:p.error('--data-dir required')
        run(a.data_dir.resolve(),a.verify_only)
