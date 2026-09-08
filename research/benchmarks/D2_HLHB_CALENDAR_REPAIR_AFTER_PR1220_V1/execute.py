"""Finite successor: preserve failed attempts; exactly two new reserved runs.

No strategy optimization. Original2025/native results are comparison-only.
Every runtime claim must be committed and read back before a market replay.
"""
from __future__ import annotations
import argparse,gzip,hashlib,json,os,subprocess,sys,traceback
from datetime import datetime,timezone
from pathlib import Path
import boundary as b
import run_benchmark as old
import accounting as a
HERE=b.HERE;ROOT=HERE.parents[2];FROZEN=b.FROZEN
SCOPE=HERE.name
RUNS={'D2':77,'HLHB':78}
START,END=1778198400000,1788566400000
SOURCE='6d6335d1c9ad7ecb1e9597da85c2eb87635561e1'

def enc(x):return old.encoded(x)
def sha_bytes(raw):return hashlib.sha256(raw).hexdigest()
def sha_file(p):return sha_bytes(Path(p).read_bytes())
def load(p):return json.loads(Path(p).read_bytes())
def gzload(p):return json.loads(gzip.decompress(Path(p).read_bytes()))
def new(p,x):return old.write_once(p,x)
def overwrite(p,x):
    p=Path(p);tmp=p.with_suffix('.pending')
    with tmp.open('xb') as f:f.write(enc(x));f.flush();os.fsync(f.fileno())
    os.replace(tmp,p)
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()

def packet_checked(path):
    packet=gzload(path)
    if old.digest(packet['rows_by'])!=old.ROW_SHA['SEEN2026'] or old.digest(packet['policy'])!=old.POLICY_SHA['SEEN2026']:
        raise ValueError('ORIGINAL_SEEN_INPUT_OR_POLICY_DRIFT')
    a.verify_cost_binding(packet['costs'])
    if packet['policy']['data_ref']!=SOURCE or packet['policy']['development_interval_ms']!=[START,END]:
        raise ValueError('SOURCE_OR_CALENDAR_DRIFT')
    if len(packet['rows_by'])!=7 or any(len(x)!=3748 for x in packet['rows_by'].values()):
        raise ValueError('ORIGINAL_SEVEN_PREFIXES_REQUIRED')
    return packet

def prepare(source_dir,path):
    sys.path.insert(0,str(ROOT))
    from backend.research.rebuild import q0_b_seen_adapter_v1 as adapter
    contract=load(ROOT/'research/development_evidence/Q0_B_SEEN_2026_V1/SPEC.json')
    policy,dev,rows,access=adapter.load_seen_inputs(str(source_dir),contract)
    packet={'rows_by':rows,'policy':policy,'costs':dev['cost_by_symbol'],
            'lineage':{'source_ref':SOURCE,'access':access,'independent':False,'new_source_requests':0}}
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:f.write(gzip.compress(enc(packet),mtime=0))
    packet_checked(path)
    print('EXACT_USED_SEEN_PREFIX_PREPARED_NO_ECONOMIC_RUN')

def bindings():
    source=load(FROZEN/'SPEC.json')
    for name,digest in source['scientific_sha256'].items():
        if sha_file(FROZEN/name)!=digest:raise ValueError('ORIGINAL_SCIENCE_DRIFT:'+name)
    files={str((HERE/name).relative_to(ROOT)):sha_file(HERE/name) for name in ['boundary.py','execute.py','test_boundary.py']}
    files.update({str((FROZEN/name).relative_to(ROOT)):digest for name,digest in source['scientific_sha256'].items()})
    return files

def freeze(inputs,qa):
    packet_checked(inputs);receipt=load(qa)
    if not receipt['success'] or receipt['tests']<14:raise ValueError('BOUNDARY_QA_INCOMPLETE')
    cases={(x['kind'],x['offset']) for x in receipt['cases']}
    if cases!={(k,o) for k in RUNS for o in (0,120,3028)}:raise ValueError('NONZERO_START_CASE_MISSING')
    original=load(FROZEN/'BUDGET.json')
    if (original['cumulative_actual'],original['cumulative_actual_evaluations'])!=(49,76):raise ValueError('INHERITED_COUNTS_DRIFT')
    new(HERE/'SYNTHETIC_QA.json',receipt)
    spec={'scope':SCOPE,'authorization':'USER_NEXT_AS_PROPOSED_AFTER_PR1220','code_commit':git('rev-parse','HEAD'),
          'files_sha256':bindings(),'engine_core_sha256':b.installed_core_identity(),
          'old_budget_sha256':sha_file(FROZEN/'BUDGET.json'),'old_spec_sha256':sha_file(FROZEN/'SPEC.json'),
          'input_file_sha256':sha_file(inputs),'input_rows_sha256':old.ROW_SHA['SEEN2026'],
          'policy_sha256':old.POLICY_SHA['SEEN2026'],'cost_sha256':a.FROZEN_COST_SHA256,
          'period':[START,END],'run_ordinals':RUNS,'max_full':2,'new_hypotheses':0,
          'original_rules_unchanged':True,'runtime_change':'POST_INDICATOR_VIEW_ALIGNMENT_AND_FATAL_INVARIANT_ASSERTIONS_ONLY',
          'engine_source':'52bc96f4480b1a0da6a9b455bd00b17fbb6786a5','version':'2026.7',
          'preserve':['ALL_PR1220_BYTES','VALID_DEV2025','FAILED_SEEN_ATTEMPTS','ALL_PRIOR_BUDGET_FIELDS'],
          'known_fill_difference':'NATIVE_TIMEOUT_CLOSE_VS_FT_NEXT_OPEN','formal_credit':0,'independent':False,
          'new_collection':0,'unused_oos_reads':0,'paid_ai_calls':0,'orders':0,'retry':False,
          'frozen_at':datetime.now(timezone.utc).isoformat(),'qa_sha256':sha_file(HERE/'SYNTHETIC_QA.json')}
    new(HERE/'SPEC.json',spec)
    original['calendar_repair_allocation']={'scope':SCOPE,'max_executions':2,'used':0,'started':0,'completed':0,'failed':0,
                                          'remaining':2,'retry':False,'new_hypotheses':0,'spec_sha256':sha_file(HERE/'SPEC.json')}
    new(HERE/'BUDGET.json',original)
    print('FROZEN_NO_NEW_MARKET_REPLAY')

def verify_spec(inputs=None):
    spec=load(HERE/'SPEC.json')
    if spec['files_sha256']!=bindings():raise ValueError('FROZEN_SOURCE_CHANGED')
    if spec['engine_core_sha256']!=b.installed_core_identity():raise ValueError('INSTALLED_CORE_CHANGED')
    if inputs:
        if spec['input_file_sha256']!=sha_file(inputs):raise ValueError('PREPARED_PACKET_BYTES_CHANGED')
        packet_checked(inputs)
    return spec

def reserve(kind):
    spec=verify_spec();budget=load(HERE/'BUDGET.json');allocation=budget['calendar_repair_allocation']
    expected_used=0 if kind=='D2' else 1
    if allocation['used']!=expected_used or allocation['remaining']<=0:raise ValueError('RESERVATION_SEQUENCE_OR_BUDGET')
    if kind=='HLHB' and allocation['completed']!=1:raise ValueError('FIRST_RUN_NOT_VALID_NO_SECOND_DISPATCH')
    claim={'scope':SCOPE,'run':kind+'_SEEN2026','ordinal':RUNS[kind],
           'state':'RESERVED_BEFORE_ENGINE','owner_run_id':os.environ['GITHUB_RUN_ID'],
           'owner_job':os.environ['GITHUB_JOB'],'owner_attempt':os.environ['GITHUB_RUN_ATTEMPT'],
           'spec_sha256':sha_file(HERE/'SPEC.json'),'reserved_at':datetime.now(timezone.utc).isoformat(),
           'new_hypothesis':False,'retry':False}
    if claim['owner_attempt']!='1':raise ValueError('WORKFLOW_RETRY_FORBIDDEN')
    new(HERE/'attempts'/f'{kind}.json',claim)
    allocation['used']+=1;allocation['remaining']-=1
    budget['trials'].append({'actual_experiment_ordinal':RUNS[kind],'scope':SCOPE,'run':claim['run'],
                             'status':'RESERVED_NOT_STARTED','new_candidate':False,'retry_allowed':False})
    overwrite(HERE/'BUDGET.json',budget)
    print('RUNTIME_CLAIM_MUST_BE_PUSHED_AND_READ_BACK_BEFORE_EXECUTE')

def execute(kind,inputs,claim_commit,remote_sha):
    spec=verify_spec(inputs);packet=packet_checked(inputs);claim=load(HERE/'attempts'/f'{kind}.json')
    if claim_commit!=remote_sha or git('rev-parse','HEAD')!=claim_commit:raise ValueError('REMOTE_CLAIM_READBACK_REQUIRED')
    rel=str((HERE/'attempts'/f'{kind}.json').relative_to(ROOT))
    committed=subprocess.check_output(['git','show',claim_commit+':'+rel],cwd=ROOT)
    if sha_bytes(committed)!=sha_file(HERE/'attempts'/f'{kind}.json'):raise ValueError('REMOTE_ATTEMPT_BYTES_DIFFER')
    if claim['owner_run_id']!=os.environ['GITHUB_RUN_ID'] or claim['spec_sha256']!=sha_file(HERE/'SPEC.json'):
        raise ValueError('CLAIM_OWNER_OR_SPEC')
    out=HERE/'results'/kind
    new(out/'LOCAL_START.json',{'run':claim['run'],'claim_commit':claim_commit,'remote_readback_sha':remote_sha,
                               'started_at':datetime.now(timezone.utc).isoformat(),'pid':os.getpid(),'retry':False})
    budget=load(HERE/'BUDGET.json');allocation=budget['calendar_repair_allocation']
    budget['cumulative_actual_evaluations']+=1;allocation['started']+=1
    if budget['cumulative_actual_evaluations']!=RUNS[kind]:raise ValueError('EVALUATION_ORDINAL_DRIFT')
    budget['trials'][-1]['status']='STARTED';overwrite(HERE/'BUDGET.json',budget)
    try:
        frames={s.replace('-','/'):b.ft.frame(rows) for s,rows in packet['rows_by'].items()}
        (result,signals,audit,resolved,config,markets),views=b.run_frame(kind,frames,START,END,out/'engine')
        df=result['results'];raw=df.astype(object).where(df.notna(),None).to_dict('records')
        raw_value={'trades':raw,'resolved':resolved,'config':config,'metadata':markets,'audit':audit,'engine_views':views}
        with (out/'RAW_ENGINE.json.gz').open('xb') as f:f.write(gzip.compress(enc(raw_value),mtime=0))
        normalized=a.normalize_engine(raw,packet,END)
        metrics=a.metrics(normalized,packet,START,END)
        report={'scope':SCOPE,'run':claim['run'],'engine_version':'2026.7','period':[START,END],
                'independent':False,'formal_credit':0,'normalized_trades':normalized,'metrics':metrics,'resolved':resolved,
                'engine_views':views,'raw_sha256':sha_file(out/'RAW_ENGINE.json.gz'),'spec_sha256':sha_file(HERE/'SPEC.json'),
                'ft_native_accounting':{'profit_abs_sum_including_force_exit':sum(float(r['profit_abs']) for r in raw),
                  'profit_ratio_sum_including_force_exit':sum(float(r['profit_ratio']) for r in raw),'fee_per_side':.0005},
                'validity':{'entries_in_period':True,'callback_errors':0,'rules_unchanged':True}}
        if kind=='D2':
            path=ROOT/'research/development_evidence/ZEL_PARENT_CLOSURE_TO_G5_SURVIVOR/D2_FAILURE/SEEN2026/RESULT.json.gz'
            native=gzload(path);report['parity']=old.compare(native,raw,normalized,audit,packet)
            report['native_reference_sha256']=sha_file(path)
        with (out/'RESULT.json.gz').open('xb') as f:f.write(gzip.compress(enc(report),mtime=0))
        new(out/'RECEIPT.json',{'status':'COMPLETED','run':claim['run'],'ordinal':RUNS[kind],
                              'result_sha256':sha_file(out/'RESULT.json.gz'),'raw_sha256':sha_file(out/'RAW_ENGINE.json.gz'),
                              'spec_sha256':sha_file(HERE/'SPEC.json'),'claim_commit':claim_commit,
                              'finished_at':datetime.now(timezone.utc).isoformat()})
        allocation['completed']+=1;budget['trials'][-1]['status']='COMPLETED'
        overwrite(HERE/'BUDGET.json',budget)
        print(json.dumps({'run':claim['run'],'metrics':{k:v for k,v in metrics.items() if not k.startswith('equity4h')}},default=old.json_default))
    except BaseException as exc:
        new(out/'FAILURE.json',{'status':'FAILED_CONSUMED','type':type(exc).__name__,'error':str(exc),
                              'traceback':traceback.format_exc(),'retry':False,'claim_commit':claim_commit})
        allocation['failed']+=1;budget['trials'][-1]['status']='FAILED_CONSUMED'
        overwrite(HERE/'BUDGET.json',budget)
        raise

def summarize():
    reports={k:gzload(HERE/'results'/k/'RESULT.json.gz') for k in RUNS}
    text=['# PR1220 calendar/cache correction — two exact 2026 comparisons','',
          'Both are already-used DEV, equal-entry-notional trade-bps, not account returns or live futures proof.',
          'Original 2025 results, failed attempts, rules, costs and native controls were not rerun or overwritten.','',
          '|2026 execution|Closed/open|Win %|Payoff|PF|Net including open mark|Cost2|4h marked DD|',
          '|---|---:|---:|---:|---:|---:|---:|---:|']
    for k,r in reports.items():
        m=r['metrics'];text.append(f"|{k} / FT2026.7|{m['closed']}/{m['open']}|{100*m['win_rate']:.2f}|{m['payoff']:.3f}|{m['PF']:.3f}|{m['terminal_net']:.2f}|{m['terminal_cost2']:.2f}|{m['mark4h_DD']:.2f}|")
    p=reports['D2']['parity']
    summary={k:len(p[k]) for k in ['signal_differences','entry_differences','reference_differences','exit_differences','cost_differences','callback_errors']}
    text+=['','## D2 independent engine differences',json.dumps(summary,indent=2),'',
           'Full first-difference details are in results/D2/RESULT.json.gz parity. Native timeout close versus FT next open remains explicit; no price overwrites.',
           'Calendar repair is an integration repair, not new alpha. High win rate is not profitability. Existing G5A HOLD and all operational authorities stay unchanged.',
           'Original signed funding, intrabar price order, live fills, margin and liquidation remain outside this offline research comparison.',
           'Candidate count49 remains; exactly two new begun evaluations77/78. Old attempts73–76 remain intact, including failures74/76.',
           'This report records economic work; final review/CI/merge closure is recorded separately.','']
    new(HERE/'SUMMARY.json',{'metrics':{k:r['metrics'] for k,r in reports.items()},'d2_difference_counts':summary})
    with (HERE/'REPORT.md').open('x') as f:f.write('\n'.join(text))
    print('\n'.join(text))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','freeze','reserve','execute','summarize'])
    p.add_argument('--inputs',type=Path);p.add_argument('--source',type=Path);p.add_argument('--qa',type=Path)
    p.add_argument('--kind',choices=list(RUNS));p.add_argument('--claim-commit');p.add_argument('--remote-sha')
    x=p.parse_args()
    if x.action=='prepare':prepare(x.source,x.inputs)
    elif x.action=='freeze':freeze(x.inputs,x.qa)
    elif x.action=='reserve':reserve(x.kind)
    elif x.action=='execute':execute(x.kind,x.inputs,x.claim_commit,x.remote_sha)
    else:summarize()
