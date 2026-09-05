"""One preregistered Top5 development comparison; no operational mutations."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
import gzip
import hashlib
import json
import math
from pathlib import Path

from backend.research.architecture_factory import g5a_development_probe_v1 as probe
from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v1 as common
from backend.research.architecture_factory.g5a_source_admission_v1 import ROOT, read, seal, file_sha, require_development
from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as dsl
from backend.research.rebuild import g5_clean_runner_binding_fix_v1 as binding
from backend.research.rebuild import top5_development_native_v1 as native

POLICY = 'backend/research/contracts/top5_development_repair_v1.json'
CHILDREN = 'backend/research/contracts/top5_development_children_v1.json'
OUTPUT = 'research/development_evidence/TOP5_DEV_REPAIR_20260905_V1'
FREEZE = 'backend/research/contracts/a1_top5_replacement_child_freeze_v2.json'
LANES = ['trend_rider_primary_wr8125','trend_rider_broad_wr7000','break_and_continue_main','keltner_trend_main','supertrend_pullback_main']


def digest(x):
    return probe.alpha.sha(x)


def geometry(rows, i, side='long'):
    r=rows[i]; prev=rows[i-1]; sign=1 if side=='long' else -1
    body=sign*(r['close']-r['open']); previous_body=sign*(prev['close']-prev['open'])
    return {'directional_body_positive':body>0,
            'previous_directional_body_positive':previous_body>0,
            'body_progress':body>=previous_body,
            'close_retains_prior_extreme': r['close']>=prev['high'] if side=='long' else r['close']<=prev['low'],
            'close_on_directional_half':r['close']>=(r['high']+r['low'])/2 if side=='long' else r['close']<=(r['high']+r['low'])/2,
            'previous_bar_inside':prev['high']<=rows[i-2]['high'] and prev['low']>=rows[i-2]['low'] if i>=2 else False}


def charge(raw, symbol, lane, scenario, policy, costs, rows, interval):
    t=dict(raw)
    parts=probe.cost_components(t['entry_ts'],t['exit_ts'],costs[symbol])
    reserve=max(0.0,20.0-parts['cost_bps']); parts['frozen_floor_reserve_bps']=reserve;parts['cost_bps']+=reserve
    t.update(parts);t.update({'net_bps':t['gross_bps']-parts['cost_bps'], 'cost2x_net_bps':t['gross_bps']-2*parts['cost_bps'],
        'batch_id':policy['batch_id'],'lane_id':lane,'scenario':scenario,'symbol':symbol,'split':'REUSED_DEVELOPMENT',
        'fill_kind':'MODELLED_NOT_ACTUAL_FILLS','native_interval_ms':interval,'data_sha256':policy['combined_data_sha256'],
        'config_sha256':policy['receipt_sha256'],'code_sha256':digest(policy['code_files_sha256']),
        'cost_sha256':policy['cost_binding_sha256'],'account_return_claimed':False,**probe.DEV_AUTH})
    t['identity']=digest({k:t[k] for k in ['symbol','signal_ts','entry_ts','exit_ts','side']})
    t['trade_sha256']=digest(t)
    return t


def four_hour(rows, symbol, child, policy, costs, scenario, predicate=None):
    spec=child['executable_spec'];lane=child['lane_id'];start,end=policy['development_interval_ms']
    converted=[dict(r,ts=r['bar_open_ts']) for r in rows]
    arrays,engine=dsl._features(converted,spec)
    signals=[];events=[]
    for i in range(239,len(rows)):
        if not bool(engine.eval(spec['entry_rule'],i)):
            continue
        g=geometry(rows,i);allowed=g[predicate] if predicate else True
        event={'lane_id':lane,'scenario':scenario,'symbol':symbol,'signal_index':i,'signal_ts':rows[i]['bar_close_ts'],
               'features':g,'admission':allowed,'formal_credit':0}
        events.append(event)
        if allowed:signals.append(i)
    raw=common.evaluate_development_events(rows,signals,split_start_ms=start,split_end_ms=end,interval_ms=14400000,hold_bars=spec['max_hold_bars'])
    trades=[charge(t,symbol,lane,scenario,policy,costs,rows,14400000) for t in raw['trades']]
    completed={t['signal_index'] for t in trades}; excluded={e['signal_index']:e['reason'] for e in raw['exclusions']}
    for e in events:
        i=e['signal_index'];e['status']='COMPLETED' if i in completed else 'EXCLUDED'
        e['exclusion_reason']=None if i in completed else ('CHILD_ENTRY_VETO' if not e['admission'] else excluded[i])
    return trades,events


def one_hour(rows,symbol,lane,policy,costs,scenario,predicate=None):
    start,end=policy['development_interval_ms'];is_primary=lane==LANES[0]
    def admission(i,feature,intent):
        return geometry(rows,i,intent.side)[predicate] if predicate else True
    path='backend/research/rebuild/'+('trend_rider_wr80_us_chase_cooling_child_policy_v1.py' if is_primary else 'trend_policy_batch_v1.py')
    raw,events=native.native_replay(rows,symbol,'primary' if is_primary else 'broad',start,end,admission,policy['code_files_sha256'][path])
    indices={r['ts_ms']:i for i,r in enumerate(rows)};trades=[]
    for r in raw:
        i=indices[r['signal_ts']];ei=indices[r['entry_ts']];xi=indices[r['exit_ts']]
        if r['exit_ts']+native.HOUR>=end:continue
        sign=1 if r['side']=='long' else -1;px=r['entry_px'];path_rows=rows[ei:xi+1]
        hi=max(b['high'] for b in path_rows);lo=min(b['low'] for b in path_rows)
        t={'signal_index':i,'entry_index':ei,'exit_index':xi,'signal_ts':r['signal_ts']+native.HOUR,
           'entry_ts':r['entry_ts'],'exit_ts':r['exit_ts']+native.HOUR,'side':r['side'],
           'entry_price':px,'exit_price':r['exit_px'],'gross_bps':r['gross_bps'],'exit_reason':r['reason'],
           'native_exit_bar_open_ts':r['exit_ts'],'exit_timestamp_semantics':'CLOSED_EXIT_BAR_UPPER_BOUND; NATIVE_INTRABAR_FILL_TIME_UNKNOWN',
           'hold_ms':r['exit_ts']+native.HOUR-r['entry_ts'],
           'mfe_bps':max(0,(hi/px-1)*10000 if sign>0 else (1-lo/px)*10000),
           'mae_bps':min(0,(lo/px-1)*10000 if sign>0 else (1-hi/px)*10000),
           'excursion_semantics':'FULL_EXIT_BAR_BOUND_INCLUDES_UNKNOWN_POST_STOP_PATH; DIAGNOSTIC_ONLY',
           'native_risk_preserved':True}
        trades.append(charge(t,symbol,lane,scenario,policy,costs,rows,native.HOUR))
    completed={t['signal_index'] for t in trades}
    for e in events:
        e['features'].update(geometry(rows,e['signal_index'],e['side']))
        e.update({'lane_id':lane,'scenario':scenario,'formal_credit':0})
        e['status']='COMPLETED' if e['signal_index'] in completed else 'EXCLUDED'
        e['exclusion_reason']=None if e['status']=='COMPLETED' else ('CHILD_ENTRY_VETO' if not e['admission'] else 'NATIVE_OWNERSHIP_OR_UNCLOSED_AT_SPLIT_END')
    return trades,events


def metrics(trades,events,policy,symbols):
    kwargs={'start_ms':policy['development_interval_ms'][0],'end_ms':policy['development_interval_ms'][1],'symbol_count':len(symbols)}
    b=probe.summarize(trades,**kwargs);stress=probe.summarize(trades,cost2x=True,**kwargs)
    b.pop('entry_outside_overlap_T');stress.pop('entry_outside_overlap_T')
    n=len(trades);b['gross_expectancy_bps']=b['gross_bps']/n if n else None
    b['mean_mfe_bps']=sum(t['mfe_bps'] for t in trades)/n if n else None
    b['mean_mae_bps']=sum(t['mae_bps'] for t in trades)/n if n else None
    b['mean_cost_components_bps']={k:sum(t[k] for t in trades)/n if n else None for k in ['fee_bps','spread_bps','impact_bps','slippage_bps','funding_bps','frozen_floor_reserve_bps']}
    return {'base_cost':b,'cost2x':stress,'raw_signals':len(events),'admitted_signals':sum(e['admission'] for e in events),
            'excluded':dict(Counter(e['exclusion_reason'] for e in events if e['status']!='COMPLETED')),
            'by_symbol':{s:probe.summarize([t for t in trades if t['symbol']==s],**{**kwargs,'symbol_count':1}) for s in symbols},
            'by_year':{str(y):probe.summarize([t for t in trades if probe.stamp_year(t['entry_ts'])==y],**kwargs) for y in sorted({probe.stamp_year(t['entry_ts']) for t in trades})}}


def diagnose(trades,events):
    fmap={(e['symbol'],e['signal_index']):e['features'] for e in events};answer={}
    names=list(geometry([{'open':1,'close':1,'high':2,'low':.5}]*3,2))
    for name in names:
        groups={}
        for value in [False,True]:
            selected=[t for t in trades if fmap[(t['symbol'],t['signal_index'])][name]==value]
            groups[str(value)]={'T':len(selected),'wins':sum(t['net_bps']>0 for t in selected),'net_bps':sum(t['net_bps'] for t in selected),
                                'mean_net_bps':sum(t['net_bps'] for t in selected)/len(selected) if selected else None}
        answer[name]=groups
    return {'observation_only_not_causal_proof':True,'fixed_ordinal_questions':answer}


def compare(parent,child,control,pm,cm,uncertainty,gate):
    pids={t['identity'] for t in parent};cids={t['identity'] for t in child}
    winners={t['identity'] for t in parent if t['net_bps']>0}
    removed=[t for t in parent if t['identity'] not in cids]
    p=pm['base_cost'];c=cm['base_cost'];n=c['completed_T']
    delta=c['expectancy_bps_per_trade']-p['expectancy_bps_per_trade'] if n and parent else None
    retention=len(cids&pids)/len(parent) if parent else None
    reasons=[]
    if n<gate['minimum_closed_T'] or c['PF'] is None or c['realized_payoff'] is None:state='INSUFFICIENT';reasons=['SAMPLE_OR_PAYOFF_UNDEFINED']
    else:
        checks={'positive_expectancy':c['expectancy_bps_per_trade']>0,'PF_above_one':c['PF']>1,'positive_cost2x':cm['cost2x']['net_bps']>0,
                'positive_increment':delta is not None and delta>0,'retention':retention>=gate['minimum_retention_pct']/100,
                'payoff':c['realized_payoff']>=gate['minimum_payoff_ratio'],
                'win_rate_harm':(p['win_rate']-c['win_rate'])*100<=gate['maximum_win_rate_harm_pp'],
                'no_exposure_increase':c['exposure_symbol_days']<=p['exposure_symbol_days']}
        reasons=[k for k,v in checks.items() if not v]
        state='DEV_PROMISING' if not reasons else 'DEV_REJECT'
    pair=uncertainty['paired_base_minus_control_95pct_interval_bps']['child']
    child_minus_parent=[-pair[1],-pair[0]] if pair[0] is not None else [None,None]
    return {'decision':state,'failed_checks':reasons,'expectancy_delta_bps':delta,'retention':retention,
            'winner_retention':len(cids&winners)/len(winners) if winners else None,
            'removed_losses_T':sum(t['net_bps']<0 for t in removed),'removed_loss_bps':sum(-t['net_bps'] for t in removed if t['net_bps']<0),
            'missed_winners_T':sum(t['net_bps']>0 for t in removed),'missed_winner_bps':sum(t['net_bps'] for t in removed if t['net_bps']>0),
            'newly_admitted_T':len(cids-pids),'child_minus_parent_95pct_interval_bps':child_minus_parent,
            'increment_uncertainty':'INCLUDES_ZERO' if child_minus_parent[0] is not None and child_minus_parent[0]<=0<=child_minus_parent[1] else 'SEE_INTERVAL',
            'formal_pass':False,'validation':'NOT_RUN','OOS':'NOT_RUN'}


def run(data_dir,stage,verify_only=False):
    p=read(POLICY);probe.verify_seal(p,'TOP5_POLICY')
    if p['authorization']!='EXPLICIT_USER_TOP5_DEVELOPMENT_ONLY' or p['first_round_challenger_budget_per_lane']!=1:raise RuntimeError('AUTHORITY_OR_BUDGET')
    for k in ['selection_authority','promotion_authority','exchange_order_submitted','g5b_entry_authorized','g5b_fresh_boundary_created']:
        if p[k] is not False:raise RuntimeError('AUTHORITY_DRIFT')
    for path,sha in p['code_files_sha256'].items():
        if file_sha(ROOT/path)!=sha:raise RuntimeError('CODE_IDENTITY:'+path)
    for path,sha in p['immutable_files_sha256'].items():
        if file_sha(ROOT/path)!=sha:raise RuntimeError('PARENT_IDENTITY:'+path)
    old=read(probe.POLICY);dev=require_development(read(probe.STAGE),ROOT)
    if dev['receipt_sha256']!=p['cost_binding_sha256']:raise RuntimeError('COST_IDENTITY')
    freezes=read(FREEZE)['children'];children=read(CHILDREN) if stage=='comparison' else None
    if children:probe.verify_seal(children,'CHILD_FREEZE')
    gate=read('backend/research/contracts/a1_top5_entry_transplant_replay_v1.json')['selection_rule']
    nroot=ROOT/OUTPUT/'native_1h';nmanifest=json.loads((nroot/'manifest.json').read_text());probe.verify_seal(nmanifest,'NATIVE_MANIFEST')
    if file_sha(nroot/'manifest.json')!=p['native_manifest_file_sha256']:raise RuntimeError('NATIVE_MANIFEST_IDENTITY')
    out=ROOT/OUTPUT/stage
    if not verify_only:out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((data_dir/'development_manifest.json').read_text())
    allowed=[data_dir/'development_manifest.json']+[data_dir/x for x in manifest['dataset_files']]+[data_dir/x['path'] for x in manifest['cost_snapshots'].values()]
    allowed += [nroot/(s+'.json.gz') for s in p['native_symbols']]
    alltrades=[];allevents=[];results={}
    with probe.io_boundary(allowed,out):
        rows4,access=probe.load_development(data_dir,old,dev);rows1={}
        for symbol in p['native_symbols']:
            path=nroot/(symbol+'.json.gz')
            if file_sha(path)!=nmanifest['symbols'][symbol]['file_sha256']:raise RuntimeError('NATIVE_DATA_SHA')
            rows1[symbol]=json.loads(gzip.decompress(path.read_bytes()));native.validate_native(rows1[symbol],*p['development_interval_ms'])
        for lane in LANES:
            is_native=lane in LANES[:2];symbols=p['native_symbols'] if is_native else p['symbols'];child=next((x for x in freezes if x['lane_id']==lane),None)
            scenarios={'base':None}
            if children:scenarios['child']=children['lanes'][lane]['predicate']
            trades_by={};metrics_by={};events_by={}
            for scenario,predicate in scenarios.items():
                ts=[];es=[]
                for symbol in symbols:
                    if is_native:t,e=one_hour(rows1[symbol],symbol,lane,p,dev['cost_by_symbol'],scenario,predicate)
                    else:t,e=four_hour(rows4[symbol],symbol,child,p,dev['cost_by_symbol'],scenario,predicate)
                    ts.extend(t);es.extend(e)
                trades_by[scenario]=ts;events_by[scenario]=es;metrics_by[scenario]=metrics(ts,es,p,symbols)
                alltrades.extend(ts);allevents.extend(es)
            if children:
                count=len(trades_by['child']);control=sorted(trades_by['base'],key=lambda t:digest(['fixed_seed_1179',t['identity']]))[:count]
                trades_by['matched_hash_control']=control;metrics_by['matched_hash_control']=metrics(control,[],p,symbols)
            u=probe.cluster_uncertainty(trades_by,p)
            result={'lane_id':lane,'parent_id':p['parents'][lane]['id'],'parent_sha256':p['parents'][lane]['sha256'],'native_timeframe':'1h' if is_native else '4h',
                    'symbol_universe':symbols,'metrics':metrics_by,'uncertainty':u,'diagnosis':diagnose(trades_by['base'],events_by['base']),
                    'causal_ablation':'BASE_IS_CHILD_FILTER_REMOVED; NOT_INDEPENDENT_EVIDENCE','economic_state':'MEASURED','validation':'NOT_RUN','OOS':'NOT_RUN'}
            if children:
                result['child_id']=children['lanes'][lane]['child_id'];result['child_spec_sha256']=digest(children['lanes'][lane])
                result['comparison']=compare(trades_by['base'],trades_by['child'],control,metrics_by['base'],metrics_by['child'],u,gate)
            results[lane]=result
        if len({t['trade_sha256'] for t in alltrades})!=len(alltrades):raise RuntimeError('DUPLICATE_TRADE')
        artifacts={}
        for name,values in [('trades',alltrades),('events',allevents)]:
            plain=b''.join(probe.canonical(x) for x in sorted(values,key=lambda x:(x['lane_id'],x['scenario'],x['symbol'],x['signal_ts'])))
            path=out/(name+'.jsonl.gz')
            compressed=path.read_bytes() if path.exists() else gzip.compress(plain,mtime=0)
            if gzip.decompress(compressed)!=plain:raise RuntimeError('REPRODUCTION_MISMATCH')
            probe.write_immutable(path,compressed,verify_only=verify_only)
            artifacts[name]={'path':str(path.relative_to(ROOT)),'rows':len(values),'file_sha256':hashlib.sha256(compressed).hexdigest(),'uncompressed_sha256':hashlib.sha256(plain).hexdigest()}
        receipt=seal({'batch_id':p['batch_id'],'stage':stage,'data_semantics':'REUSED_DEVELOPMENT','policy_sha256':p['receipt_sha256'],
                      'code_sha256':digest(p['code_files_sha256']),'data_sha256':p['combined_data_sha256'],'cost_sha256':p['cost_binding_sha256'],
                      'lanes':results,'artifacts':artifacts,'source_access':access,'native_decoded_rows':{s:len(v) for s,v in rows1.items()},
                      'validation_rows_decoded':0,'OOS_rows_decoded':0,'new_g5b_boundary':False,'formal_credit':0,'production_grade_credit':0,
                      'G5B_fresh_T_created':0,'native_raw_trade_duplicate_credit_across_lanes':False,'lane_results_must_not_be_summed':True,
                      'paid_AI_calls':0,**probe.DEV_AUTH})
        probe.write_immutable(out/'receipt.json',probe.canonical(receipt),verify_only=verify_only)
    return receipt


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--data-dir',type=Path,required=True);ap.add_argument('--stage',choices=['baseline','comparison'],required=True);ap.add_argument('--verify-only',action='store_true');a=ap.parse_args()
    r=run(a.data_dir.resolve(),a.stage,a.verify_only)
    print(json.dumps({'stage':r['stage'],'receipt_sha256':r['receipt_sha256'],'lanes':{k:{'parent':v['metrics']['base']['base_cost'],'comparison':v.get('comparison')} for k,v in r['lanes'].items()}}))

if __name__=='__main__':main()
