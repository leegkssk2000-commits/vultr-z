"""Read-only proof of the one measured deferred-entry rule; no engine imports.

The previous C69 verifier supplies pure cost/EMA/metric arithmetic. Optional
original packets bind all prices and first decisions; routine CI pins that proof.
"""
import argparse,importlib.util,json,gzip,hashlib,math
from pathlib import Path
from copy import deepcopy
from collections import Counter
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2]
C69='research/development_evidence/C63_DAILY_EMA21_HORTON_TIP_AFTER_PR1241_V1'
C63='research/development_evidence/M1_ER_RANGE_RESCUE_AFTER_PR1232_V1'
if hashlib.sha256((REPO/C69/'verify_saved.py').read_bytes()).hexdigest()!='e7db902001f2c11c8b21d4f319e84da203ebf8539dd26db328469b0ca4d4fcd0':raise ValueError('PRIOR_ARITHMETIC_SOURCE_DRIFT')
util=importlib.util.spec_from_file_location('prior_daily_arithmetic',REPO/C69/'verify_saved.py')
v=importlib.util.module_from_spec(util);util.loader.exec_module(v)
read,gz,sha,canon,need,same=v.read,v.gz,v.sha,v.canon,v.need,v.same
BAR=14400000;PERIODS=('DEV2025','SEEN2026');KEY='c63_daily21_deferred_allocation'
EVIDENCE_SHA='fee54ef9da0dfc2201828a27a686b5bf585634a6882de478df141031f71c9cdc'

def check_day(obs,rows=None):
    return v.daily_context(dict(signal_index=obs['signal_index'],signal_ts=obs['available_at'],er_context={'daily_context':obs}),rows)

def why(close,floor,mom,elapsed):
    return 'FIXED_FLOOR_CLOSE' if close<=floor else 'MOMENTUM_NONPOSITIVE_CLOSE' if mom<=0 else 'FIXED_TIME_CLOSE' if elapsed>=20 else None

def details(parent,child):
    out=v.details(parent,child);pi,ci=v.index(parent),v.index(child)
    # An open mark must never count as restored completed winner profit.
    wins=sorted([k for k,x in pi.items() if x[0]=='C' and v.val(x)>0],key=lambda k:(-v.val(pi[k]),k))
    for name,keys in [('all_winners',wins),('top_decile',wins[:math.ceil(len(wins)*.1)])]:
        den=sum(v.val(pi[k]) for k in keys)
        kept=sum(min(v.val(pi[k]),max(0,v.val(ci[k]))) for k in keys if k in ci and ci[k][0]=='C')
        out['retention'][name].update(kept_profit=kept,fraction=kept/den if den else None)
    return out

def cell(per,inputs=None,root=HERE):
    root=Path(root);repo=root.parents[2];spec=read(root/'SPEC.json');cal=spec['periods'][per]
    raw=gz(root/per/'RAW.json.gz');result=gz(root/per/'RESULT.json.gz');par=gz(repo/C63/per/'RESULT.json.gz');pr=gz(repo/C63/per/'RAW.json.gz');c69=gz(repo/C69/per/'RESULT.json.gz')
    packet=None
    if inputs:
        ip=Path(inputs)/(per+'.json.gz');need(sha(ip)==spec['input_packet_sha256'][per],'INPUT_HASH');packet=gz(ip)
    signals=held=pending_closes=0;expected=[];delayed=[]
    charged_index=v.index(result);raw_origins=set()
    for sym,x in sorted(raw.items()):
        old={e['signal_index']:e for e in pr[sym]['events']};original_indices=list(old)
        need([e['signal_index'] for e in x['events']]==original_indices,'SIGNAL_POOL')
        need(x['setup_events']==pr[sym]['setup_events'],'SETUP_POOL')
        rows=packet['rows_by'][sym] if packet else None
        pos={t['signal_index']:t for k in ('trades','open_positions') for t in x[k]}
        need(len(pos)==len(x['trades'])+len(x['open_positions']),'DUPLICATE_RAW_POSITION')
        last=-1;tail=False;pending_entries=[]
        for num,e in enumerate(x['events']):
            signals+=1;i=e['signal_index'];before=old[i]
            need(e['er_context']==before['er_context'],'ORIGINAL_C63_QUALIFICATION')
            for k in ('signal_ts','episode_start','floor','target','expiry','max_hold_bars','feature','setup_id','setup_available_at'):need(e[k]==before[k],'ORIGINAL_'+k)
            day=e['initial_daily_context'];above=check_day(day,rows);decision=None;reason=None
            if tail or e['signal_ts']<=last:reason='ACTUAL_POSITION_OCCUPIED_AT_DECISION'
            elif e['expiry'] is not None and e['signal_ts']>=e['expiry']:reason='SETUP_EXPIRED_BEFORE_ENTRY'
            elif not e['er_context']['eligible']:reason=e['er_context']['reason']
            elif day['value'] is None:reason=v.MISSING
            elif above:decision=i
            elif e['signal_ts']>=cal['runoff_end_ms']:reason='PENDING_RECLAIM_OUTSIDE_WINDOW'
            elif rows is not None and rows[i+1]['open']<=e['floor']:reason='GAP_INVALIDATES_FIXED_SETUP'
            elif rows is None and not e['pending_observations'] and e['exclusion_reason']=='GAP_INVALIDATES_FIXED_SETUP':reason=e['exclusion_reason']
            else:
                next_signal=original_indices[num+1] if num+1<len(original_indices) else None
                for offset,h in enumerate(e['pending_observations'],1):
                    j=i+offset;pending_closes+=1;need(h['index']==j and h['available_at']==e['signal_ts']+offset*BAR and h['original_clock_bars']==offset,'PENDING_ORDER_OR_CLOCK')
                    if rows:
                        need(h['close']==rows[j]['close'] and h['available_at']==rows[j]['bar_close_ts'],'PENDING_SOURCE_PRICE')
                        same(h['momentum'],rows[j]['close']-rows[j-14]['close'],'PENDING_SOURCE_MOMENTUM')
                    invalid=why(h['close'],e['floor'],h['momentum'],offset)
                    if j==next_signal:invalid='REPLACED_BY_NEW_NATIVE_SIGNAL'
                    need(h['invalidation']==invalid,'PENDING_INVALIDATION_PRIORITY')
                    if invalid:
                        need('daily_context' not in h and offset==len(e['pending_observations']),'NO_CONFIRM_AFTER_INVALIDATION')
                        reason='PENDING_CANCEL_'+invalid;break
                    if check_day(h['daily_context'],rows):
                        need(offset==len(e['pending_observations']),'NOT_FIRST_RECLAIM')
                        need(e['reclaim_daily_context']==h['daily_context'],'RECLAIM_BINDING')
                        decision=j;break
                if reason is None and decision is None:
                    reason='PENDING_RECLAIM_OUTSIDE_WINDOW'
                    need(bool(e['pending_observations']) and e['pending_observations'][-1]['available_at']==cal['runoff_end_ms'],'PREMATURE_PENDING_END')
            if decision is None:
                need(e['decision_index'] is None and e['decision_ts'] is None and e['wait_bars']==0,'ABSENT_DECISION')
            else:
                need(e['decision_index']==decision and e['decision_ts']==e['signal_ts']+(decision-i)*BAR and e['wait_bars']==decision-i,'ENTRY_DECISION_CLOCK')
                if e['decision_ts']>=cal['runoff_end_ms']:reason='NO_NEXT_OPEN_IN_APPROVED_WINDOW'
                elif rows is not None and rows[decision+1]['open']<=e['floor']:reason='GAP_INVALIDATES_FIXED_SETUP'
                elif rows is None and e['exclusion_reason']=='GAP_INVALIDATES_FIXED_SETUP':reason=e['exclusion_reason']
            need(e['exclusion_reason']==reason and e['admission']==(reason is None),'ACTUAL_ADMISSION')
            need((i in pos)==e['admission'],'RAW_POSITION_ADMISSION')
            if reason in ('PENDING_RECLAIM_OUTSIDE_WINDOW','NO_NEXT_OPEN_IN_APPROVED_WINDOW'):pending_entries.append(e)
            expected.append(dict(e,symbol=sym,lane_id='source_squeeze_momentum_long',comparison_stage=spec['candidate'],scenario=spec['candidate']))
            if i not in pos:continue
            t=pos[i];ei=decision+1;delay=decision-i
            key=(sym,i,e['signal_ts']);raw_origins.add(key)
            need(key in charged_index,'CHARGED_ORIGIN')
            kind,charged=charged_index[key]
            need(kind==('C' if 'exit_ts' in t else 'O'),'CHARGED_STATE')
            for field,value in t.items():need(charged.get(field)==value,'RAW_CHARGED_FIELD:'+field)
            need(t['decision_index']==decision and t['entry_index']==ei and t['entry_ts']==e['decision_ts']==t['decision_ts'],'ACTUAL_ENTRY_CLOCK')
            need(t['signal_ts']==e['signal_ts'] and t['wait_bars']==delay and t['original_clock_end_index']==i+20 and not t['entry_clock_reset'],'ORIGINAL_CLOCK_NOT_RESET')
            if rows:need(t['entry_price']==rows[ei]['open']>e['floor'],'SOURCE_ENTRY_PRICE')
            tr=[h for h in x['trace'] if h['signal_index']==i];observed=[h for h in tr if h['kind']=='HELD_CLOSE_OBSERVATION'];trigger=None
            need(bool(observed),'MISSING_HELD_PATH')
            for offset,h in enumerate(observed,1):
                j=ei+offset-1;held+=1;need(trigger is None,'IGNORED_EXIT')
                need(h['index']==j and h['held_bars']==offset and h['original_clock_bars']==offset+delay and h['decision_index']==decision,'HELD_ORIGINAL_CLOCK')
                if rows:
                    need(h['close']==rows[j]['close'] and h['ts']==rows[j]['bar_close_ts'],'HELD_SOURCE_PRICE')
                    same(h['momentum'],rows[j]['close']-rows[j-14]['close'],'HELD_SOURCE_MOMENTUM')
                exit_reason=why(h['close'],e['floor'],h['momentum'],offset+delay)
                need(h['exit_reason']==exit_reason,'FIRST_NATIVE_EXIT')
                if exit_reason:trigger=dict(signal_index=j,signal_ts=h['ts'],observed_close=h['close'],reason=exit_reason)
            if 'exit_ts' in t:
                need(trigger==t['exit_trigger'] and t['exit_index']==trigger['signal_index']+1 and t['exit_ts']==trigger['signal_ts']<cal['runoff_end_ms'],'EXIT_NEXT_OPEN')
                need(t['exit_reason']==trigger['reason']+'_NEXT_OPEN','EXIT_REASON');last=t['exit_ts'];end=last;px=t['exit_price']
                if rows:need(px==rows[t['exit_index']]['open'],'SOURCE_EXIT_PRICE')
            else:
                need(t['pending_exit_trigger']==trigger and t['mark_ts']==cal['runoff_end_ms'] and not t['terminal_liquidation'],'OPEN_MARK_NOT_FILL');tail=True;end=t['mark_ts'];px=t['mark_price']
                need(observed[-1]['ts']==end,'OPEN_PATH_END')
                if rows:need(px==rows[t['mark_index']]['close'],'SOURCE_MARK_PRICE')
            need(t['hold_ms']==end-t['entry_ts'],'NO_COST_DURING_WAIT')
            if rows:
                gross=(px/t['entry_price']-1)*10000;path=rows[ei:observed[-1]['index']+1]
                same(t['mfe_bps'],max(0.,gross,max((b['high']/t['entry_price']-1)*10000 for b in path)),'MFE_SOURCE')
                same(t['mae_bps'],min(0.,gross,min((b['low']/t['entry_price']-1)*10000 for b in path)),'MAE_SOURCE')
            if delay:delayed.append(dict(symbol=sym,signal_index=i,signal_ts=e['signal_ts'],decision_ts=e['decision_ts'],wait_bars=delay))
        need(len(x['pending_entries'])==len(pending_entries),'PENDING_ENTRY_COUNT')
        for stored,e in zip(x['pending_entries'],pending_entries):
            for key in ('signal_index','signal_ts','exclusion_reason','decision_index','decision_ts','pending_observations'):need(stored[key]==e[key],'PENDING_ENTRY_EVIDENCE')
    need(result['events']==expected,'CHARGED_EVENT_PARITY')
    need(raw_origins==set(charged_index),'CHARGED_ORIGIN_COVERAGE')
    v.metrics(result,packet)
    for row in result['trades']+result['open_observations']:
        need(not row['independent'] and row['formal_credit']==0 and not row['exchange_order_submitted'],'AUTHORITY')
    out={}
    for label,parent in [('C63',par),('C69',c69)]:
        d=details(parent,result);ac=read(root/per/('ACCOUNTING_'+label+'.json'))
        same(ac['marked_delta_bps_not_realized'],d['net_delta'],'ATTRIBUTION_DELTA')
        for name,own in [('winner','all_winners'),('large_winner','top_decile')]:same(ac[name]['amount_retention_lower'],d['retention'][own]['fraction'],'WINNER_RETENTION')
        out[label]=d
    return dict(signals=signals,positions=len(v.index(result)),held_closes=held,pending_closes=pending_closes,daily_marks=len(result['metrics']['daily']),deferred=delayed,details=out)

def verify(root=HERE,inputs=None,full_repository=False,proof_sha=None):
    root=Path(root);repo=root.parents[2];need(sha(root/'EVIDENCE_HASHES.json')==EVIDENCE_SHA,'MANIFEST_PIN')
    for n,d in read(root/'EVIDENCE_HASHES.json').items():need(sha(root/n)==d,'FROZEN_OUTPUT:'+n)
    spec=read(root/'SPEC.json');b=deepcopy(read(root/'BUDGET.json'));slot=b.pop(KEY)
    need((slot['reserved'],slot['started'],slot['completed'],slot['failed'],slot['remaining'])==(2,2,2,0,0),'CLOSED_SCOPE')
    need((b['cumulative_actual'],b['cumulative_actual_evaluations'])==(70,124),'CUMULATIVE_COUNTS')
    need([t['actual_experiment_ordinal'] for t in b['trials'][-2:]]==[123,124],'TRIAL_IDS')
    b['trials']=b['trials'][:-2];b['candidate_trials']=b['candidate_trials'][:-1];b['cumulative_actual']-=1;b['cumulative_actual_evaluations']-=2;b['new_candidate_runs']-=1
    need(b==read(root/'HISTORY_PRIOR.json') and b['chart_allocation']['remaining']==6,'ORIGINAL_HISTORY')
    if full_repository:
        for n,d in spec['source_files_sha256'].items():need(sha(repo/n)==d,'FROZEN_SOURCE:'+n)
    summary=read(root/'SUMMARY.json');output={};flags=[]
    for per in PERIODS:
        for n,d in spec['parent_results_sha256'][per].items():need(sha(repo/C63/per/n)==d,'C63_PIN')
        need(sha(repo/C69/per/'RESULT.json.gz')==spec['comparator_sha256'][per],'C69_PIN')
        at,start,receipt=[read(root/per/n) for n in ('ATTEMPT.json','EXECUTION_STARTED.json','RECEIPT.json')]
        need(at['spec_sha256']==receipt['spec_sha256']==sha(root/'SPEC.json'),'SPEC_BINDING')
        need(spec['frozen_ns']<at['time_ns']<start['time_ns'],'FREEZE_BEFORE_EXECUTION')
        need(start['claim_commit']==start['remote_readback_sha']==receipt['claim_commit'] and start['owner_run']==at['owner_run'],'REMOTE_CLAIM')
        need(receipt['result_sha256']==sha(root/per/'RESULT.json.gz') and receipt['raw_sha256']==sha(root/per/'RAW.json.gz'),'RECEIPT_HASH')
        output[per]=cell(per,inputs,root)
        par=gz(repo/C63/per/'RESULT.json.gz');res=gz(root/per/'RESULT.json.gz');pm,cm=par['metrics'],res['metrics']
        checks={k:(cv>pv and not math.isclose(cv,pv,rel_tol=1e-12,abs_tol=1e-7)) for k,cv,pv in [('WR_up',cm['base_cost']['win_rate'],pm['base_cost']['win_rate']),('net_up',cm['terminal_net_bps'],pm['terminal_net_bps']),('cost2_up',cm['terminal_cost2x_net_bps'],pm['terminal_cost2x_net_bps']),('DD_down',pm['marked_DD_trade_sum_bps'],cm['marked_DD_trade_sum_bps'])]}
        need(checks==summary['periods'][per]['checks'],'SUMMARY_GOALS');flags.append(checks)
        for label,r in [('C63',par),('C69',gz(repo/C69/per/'RESULT.json.gz')),('C70',res)]:
            snap=summary['periods'][per]['snapshots'][label];m=r['metrics']
            need(snap['closed']==len(r['trades']) and snap['open']==len(r['open_observations']),'SUMMARY_COUNTS')
            for key in ('win_rate','average_win_bps','average_loss_bps','PF','realized_payoff'):same(snap[key],m['base_cost'][key],'SUMMARY_BASE')
            for key in ('terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps'):same(snap[key],m[key],'SUMMARY_TOTAL')
    goal=all(all(x.values()) for x in flags);gain=all(x['net_up'] and x['cost2_up'] for x in flags)
    need(summary['status']==('DEVELOPMENT_GOAL_MET' if goal else 'PARTIAL_IMPROVEMENT' if gain else 'REJECT_KEEP_C63'),'FROZEN_VERDICT')
    if proof_sha:
        need(sha(root/'SOURCE_PROOF.json')==proof_sha,'SOURCE_PROOF_PIN');proof=read(root/'SOURCE_PROOF.json')
        need(proof['periods_canonical_sha256']==hashlib.sha256(canon(output)).hexdigest() and proof['input_packet_sha256']==spec['input_packet_sha256'],'SOURCE_PROOF_BINDING')
    return dict(status=summary['status'],periods=output,new_economic_replays=0,original_inputs_checked=inputs is not None,full_source_checked=full_repository)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--inputs');p.add_argument('--full-repository',action='store_true');p.add_argument('--proof-sha');args=p.parse_args()
    out=verify(inputs=args.inputs,full_repository=args.full_repository,proof_sha=args.proof_sha)
    print(json.dumps({k:x if k!='periods' else {per:{n:d[n] for n in ('signals','positions','held_closes','pending_closes','daily_marks')} for per,d in x.items()} for k,x in out.items()},indent=2))
