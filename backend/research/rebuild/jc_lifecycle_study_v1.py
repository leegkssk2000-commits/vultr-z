"""Exactly two first FULLs, with remote attempt reservation; saved-only verify."""
import argparse,gzip,json,os,time,traceback
from pathlib import Path
from backend.research.rebuild import c63_initial_failure_f_study_v1 as old
from backend.research.rebuild import jc_lifecycle_v1 as engine
from backend.research.rebuild import jc_lifecycle_account_v1 as account
from backend.research.rebuild import jc_lifecycle_source_v1 as source
ROOT=old.ROOT;SCOPE='TRADER_LIFECYCLE_BENCHMARK_AFTER_PR1249_V1';OUT=ROOT/'research/development_evidence'/SCOPE
BRANCH='research/trader-lifecycle-after-pr1249-v1';PERIODS=old.PERIODS
read,gz,h,p,a=old.read,old.gz,old.h,old.p,old.a
CAL={'DEV2025':dict(start_ms=1734595200000,runoff_end_ms=1766995200000),'SEEN2026':dict(start_ms=1778198400000,runoff_end_ms=1788566400000)}
INPUT_HASH={'DEV2025':'4c1936726690fd29407694bf55e1047c4870d524843dd5b3420e60ac238a919c','SEEN2026':'91d6e07a38c6b0dd3bcfcfa4b1b10bcf8cb3595d35fba183765f8e02a6a24a70'}

def put(name,value):source.save(OUT/name,value)
def need(ok,message):
 if not ok:raise RuntimeError(message)
def owner():
 need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1' and os.environ.get('GITHUB_REF_NAME')==BRANCH,'NO_RETRY_OR_WRONG_OWNER')
 return os.environ['GITHUB_RUN_ID']
def packet(per):
 path=ROOT/old.INPUTS/(per+'.json.gz');need(h(path)==INPUT_HASH[per],'INPUT_DRIFT');return gz(path)
def code_hashes():
 names=['jc_lifecycle_v1.py','jc_lifecycle_account_v1.py','jc_lifecycle_study_v1.py','jc_lifecycle_source_v1.py','test_jc_lifecycle_v1.py','chart_mechanism_features_v1.py','parallel_exit_metrics_v1.py','parallel_exit_dev_v1.py','kr3_profit_zone_exit_v1.py']
 return {f'backend/research/rebuild/{n}':h(ROOT/'backend/research/rebuild'/n) for n in names}
def sources():
 return {str(x.relative_to(ROOT)):h(x) for folder in ['HANDOFF','SOURCE'] for x in (OUT/folder).rglob('*') if x.is_file()}

def prepare_binding():
 # Already downloaded bytes only. Never retries a GET or uses crossing daily OHLC.
 receipts=read(OUT/'SOURCE/REQUESTS.json');binding={'warmup':{},'ticks':{},'boundary':{},'listing_origin_verified':False}
 for rec in receipts:
  symbol=rec['symbol'];path=OUT/'SOURCE/raw'/(symbol+'.json');need(h(path)==rec['sha256'],'RAW_SOURCE_DRIFT')
  raw=read(path);need(raw['code']==0,'SOURCE_CODE');days=[];quarantine=[]
  for row in raw['data']:
   ts=int(row['time'])
   if ts%engine.DAY or ts<source.START-370*engine.DAY or ts+engine.DAY>source.START:
    quarantine.append(dict(open_ts=ts,close_ts=ts+engine.DAY));continue
   days.append(dict(open_ts=ts,**{k:float(row[k]) for k in ('open','high','low','close','volume')}))
  days.sort(key=lambda x:x['open_ts']);engine.f.validate([engine.f.Bar(**x) for x in days],engine.DAY)
  put('SOURCE/daily/'+symbol+'.json',days)
  binding['warmup'][symbol]=dict(rows=len(days),sha256=h(OUT/'SOURCE/daily'/(symbol+'.json')),quarantined_boundary_rows=quarantine)
  binding['boundary'][symbol]={'first_eval_open':source.START,'missing_initial_4h_opens':[1734566400000,1734580800000],
   'reset_daily_segment_at':1734652800000,'use_after_reset_only':True,
   'DEV2025_early_dates':'INELIGIBLE_UNTIL_365_CONTIGUOUS_COMPLETED_DAYS','SEEN2026':'EXISTING_PREFIX_SUFFICIENT'}
 contract=OUT/'SOURCE/CONTRACTS_1f0330a65e371ab95aea9c37c1e690f43465339377b714e3fd1c841936eb222f.json'
 need(h(contract)=='1f0330a65e371ab95aea9c37c1e690f43465339377b714e3fd1c841936eb222f','CONTRACT_RAW_BINDING')
 data=read(contract)['data']
 for symbol in source.SYMBOLS:
  match=[x for x in data if x['symbol']==symbol];need(len(match)==1,'UNIQUE_CONTRACT')
  precision=match[0]['pricePrecision'];need(type(precision) is int and 0<=precision<=12,'NATIVE_PRECISION')
  binding['ticks'][symbol]={'price_precision':precision,'increment':10.**-precision,'raw_sha256':h(contract),
   'temporal_limit':'2026-09-07 preserved snapshot; fixed research precision assumption, NOT historical exchange-rule evidence'}
 binding['market_GETs']=len(receipts);binding['received_bytes']=sum(x.get('bytes',0) for x in receipts)
 binding['cross_boundary_rows_not_used']=sum(len(x['quarantined_boundary_rows']) for x in binding['warmup'].values())
 put('SOURCE_BINDING.json',binding);return binding


def freeze():
 run=owner();need(not (OUT/'SPEC.json').exists(),'ALREADY_FROZEN')
 binding=prepare_binding();prior=read(ROOT/old.OUT/'BUDGET.json');need((prior['cumulative_actual'],prior['cumulative_actual_evaluations'])==(78,140),'LATEST_HISTORY_CHANGED')
 original=(ROOT/old.OUT/'BUDGET.json').read_bytes();(OUT/'HISTORY_PRIOR.json').write_bytes(original)
 source_budget=read(OUT/'BUDGET.json');budget=dict(prior);budget['jc_lifecycle_allocation']=dict(candidate_cap=1,full_cap=2,reserved=0,started=0,completed=0,failed=0,remaining=2,owner_run=run)
 budget['jc_source_allocation']=source_budget;put('BUDGET.json',budget)
 preserved={str(x.relative_to(ROOT)):h(x) for x in (ROOT/old.OUT).rglob('*') if x.is_file()}
 put('PRESERVATION.json',preserved)
 spec=dict(scope=SCOPE,candidate=engine.RULE_ID,owner_run=run,source_commit=old.git('rev-parse','HEAD'),code_sha256=code_hashes(),source_files_sha256=sources(),
   source_binding_sha256=h(OUT/'SOURCE_BINDING.json'),design_sha256=h(OUT/'IMPLEMENTATION_CHOICES.md'),history_sha256=h(OUT/'HISTORY_PRIOR.json'),
   periods=CAL,input_sha256=INPUT_HASH,cost_sha256={per:p.sha(packet(per)['costs']) for per in PERIODS},
   policy_sha256={per:p.sha(packet(per)['policy']) for per in PERIODS},parent_sha256={per:p.sha(old.baseline('C63',per)) for per in PERIODS},
   judgment='m1_er14_study_v1.checks WR/net/cost2/DD strict for each period; no exception for zero trades',
   historical_candidates=78,historical_evaluations=140,candidate_ordinal=None,evaluation_ordinals=[],max_FULL=2,retry=False,
   independent=False,formal_credit=0,paid_ai=0,orders=0,deploy=0,new_OOS=0,parent_replay=0,FIXED=0,freeze_ns=time.time_ns())
 put('SPEC.json',spec);put('STATUS.json',dict(scope=SCOPE,status='PREPARED',owner_run=run));source.persist('JC rule code source cost input judgment frozen before outcomes')

def check():
 spec=read(OUT/'SPEC.json');need(spec['scope']==SCOPE,'SCOPE_MISMATCH');need(spec['code_sha256']==code_hashes(),'CODE_DRIFT');need(spec['source_files_sha256']==sources(),'SOURCE_DRIFT')
 for name,digest in read(OUT/'PRESERVATION.json').items():need(h(ROOT/name)==digest,'PR1249_HISTORY_DRIFT:'+name)
 need(h(ROOT/old.OUT/'BUDGET.json')==spec['history_sha256'],'LATEST_INHERITED_BUDGET_DRIFT')
 need(h(OUT/'SOURCE_BINDING.json')==spec['source_binding_sha256'] and h(OUT/'IMPLEMENTATION_CHOICES.md')==spec['design_sha256'],'DESIGN_DRIFT')
 for per in PERIODS:
  data=packet(per);need(p.sha(data['costs'])==spec['cost_sha256'][per] and p.sha(data['policy'])==spec['policy_sha256'][per],'COST_POLICY_DRIFT')
 return spec

def execute(per):
 spec=check();run=owner();j=PERIODS.index(per);budget=read(OUT/'BUDGET.json');q=budget['jc_lifecycle_allocation']
 need(q['owner_run']==run and q['reserved']==q['started']==q['completed']==j and not q['failed'],'NO_DUPLICATE_RETRY')
 state=read(OUT/'STATUS.json');need(state['scope']==SCOPE and state['status'] in ('PREPARED','RUNNING'),'SCOPE_CLOSED')
 attempt=dict(scope=SCOPE,period=per,status='RESERVED_NOT_STARTED',owner_run=run,candidate_ordinal=None,evaluation_ordinal=None,spec_sha256=h(OUT/'SPEC.json'))
 put(per+'/ATTEMPT.json',attempt);q['reserved']+=1;q['remaining']-=1;put('BUDGET.json',budget);source.persist('JC FULL reserved '+per)
 claim=old.git('rev-parse','HEAD');need(old.git('ls-remote','origin','refs/heads/'+BRANCH).split()[0]==claim,'REMOTE_READBACK')
 need(budget['cumulative_actual_evaluations']==140+j and budget['cumulative_actual']==78+(j>0),'ORDINAL_CHANGED')
 if j==0:
  budget['cumulative_actual']+=1;budget['new_candidate_runs']+=1;budget['candidate_trials'].append(dict(candidate=engine.RULE_ID,ordinal=79,scope=SCOPE,first_evaluation=141))
 budget['cumulative_actual_evaluations']+=1;q['started']+=1
 budget['trials'].append(dict(candidate=engine.RULE_ID,period=per,scope=SCOPE,ordinal=141+j,status='STARTED'))
 attempt.update(status='STARTED',candidate_ordinal=79,evaluation_ordinal=141+j,claim_commit=claim,started_ns=time.time_ns())
 put(per+'/EXECUTION_STARTED.json',attempt);put('BUDGET.json',budget);put('STATUS.json',dict(scope=SCOPE,status='RUNNING',owner_run=run));source.persist('JC FULL actual start '+per)
 started=old.git('rev-parse','HEAD')
 try:
  data=packet(per);binding=read(OUT/'SOURCE_BINDING.json');cal=CAL[per];raw={}
  for symbol,rows in sorted(data['rows_by'].items()):
   warm=[engine.f.Bar(**x) for x in read(OUT/'SOURCE/daily'/(symbol+'.json'))] if per=='DEV2025' else []
   raw[symbol]=engine.replay(rows,eval_start_ms=cal['start_ms'],eval_end_ms=cal['runoff_end_ms'],warmup_days=warm,tick=binding['ticks'][symbol]['increment'],cost_model=data['costs'][symbol])
  folder=OUT/per;folder.mkdir(exist_ok=True)
  (folder/'RAW.json.gz').write_bytes(gzip.compress(p.canonical(raw),mtime=0))
  result=account.charge(raw,data,cal);account.verify_money(result)
  (folder/'RESULT.json.gz').write_bytes(gzip.compress(p.canonical(result),mtime=0))
  attribution=json.loads(p.canonical(a.compare(old.baseline('C63',per),result)));attribution['comparison_type']='DISTINCT_LIFECYCLE_LANES_NO_FORCED_DATE_MATCH'
  put(per+'/ACCOUNTING_C63.json',attribution)
  put(per+'/RECEIPT.json',dict(status='COMPLETED',owner_run=run,started_commit=started,candidate_ordinal=79,evaluation_ordinal=141+j,raw_sha256=h(folder/'RAW.json.gz'),result_sha256=h(folder/'RESULT.json.gz'),metrics=a.snapshot(result)))
  q['completed']+=1;budget['trials'][-1]['status']='COMPLETED';put('BUDGET.json',budget);source.persist('JC first FULL saved '+per)
 except BaseException as exc:
  q['failed']+=1;budget['trials'][-1]['status']='FAILED_CONSUMED';put('BUDGET.json',budget)
  put(per+'/FAILURE.json',dict(error=str(exc),traceback=traceback.format_exc(),retry=False,started_commit=started));put('STATUS.json',dict(scope=SCOPE,status='CHECKPOINTED_BLOCKED',owner_run=run));source.persist('JC failed attempt retained no retry '+per);raise


def summarize():
 datasets={per:{'C63':old.baseline('C63',per),'JC':gz(OUT/per/'RESULT.json.gz')} for per in PERIODS};periods={}
 for per,rows in datasets.items():
  snapshots={k:a.snapshot(v) for k,v in rows.items()};snapshots['JC'].update(protective_SL='2_ATR21_FROZEN_THEN_RATCHET',TP='THREE_LEVEL_PARTIAL_LADDER')
  accountings=json.loads(p.canonical(a.compare(rows['C63'],rows['JC'])));accountings['comparison_type']='DISTINCT_LIFECYCLE_LANES_NO_FORCED_DATE_MATCH'
  periods[per]=dict(snapshots=snapshots,checks=old.prior.prior.d.prior.previous.checks(snapshots['C63'],snapshots['JC']),
   accounting=accountings,risk={k:old.closed_risk(v) for k,v in rows.items()},
   winner_coverage=old.risk_and_winners(rows['C63'],rows['JC'],accountings),
   candidate_audit=rows['JC']['audit'],candidate_metrics=rows['JC']['metrics'])
 checks=[v for per in periods.values() for v in per['checks'].values()]
 return dict(scope=SCOPE,decision='DEVELOPMENT_GOAL_MET' if all(checks) else 'REJECT_KEEP_C63',objectives_passed=sum(checks),objectives_total=8,
  periods=periods,disjoint_arithmetic={k:old.aggregate([datasets[per][k] for per in PERIODS]) for k in ('C63','JC')},
  new_candidates=1,new_FULL=2,candidates=79,evaluations=142,formal_credit=0,independent=False,
  source_fidelity='CRYPTO_ADAPTATION_NOT_EXACT_OPTIONS_OR_TRADER_ACCOUNT',coverage_limitation='DEV2025 early dates ineligible: initial partial UTC day resets rolling365 history',
  paid_ai=0,orders=0,deploy=0,parent_replay=0,FIXED=0,new_OOS=0)

def render(s):
 lines=['# C63 / JC lifecycle first FULL results','',
  'USED_DEV; fixed reference-notional trade-bps. Open positions include hypothetical remaining costs. Model costs and 2026-09-07 precision snapshot are not historical execution proof. Daily drawdown is not account drawdown.','',
  '|Period|Rule|Closed/open|WR %|Avg win|Avg loss|Payoff|PF|Terminal net|Cost2|Daily DD|','|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
 fmt=lambda x:'—' if x is None else f'{x:.2f}'
 for per,v in s['periods'].items():
  for name,m in v['snapshots'].items():
   vals=[None if m['win_rate'] is None else m['win_rate']*100,m['average_win_bps'],m['average_loss_bps'],m['realized_payoff'],m['PF'],m['terminal_net_bps'],m['terminal_cost2x_net_bps'],m['marked_DD_trade_sum_bps']]
   lines.append('|'+per+'|'+name+'|'+str(m['closed'])+'/'+str(m['open'])+'|'+'|'.join(fmt(x) for x in vals)+'|')
 lines+=['',s['decision']+f"; {s['objectives_passed']}/8 strict objectives.",'',
  'DEV2025 has no complete first UTC day (08:00 start). No interpolation or crossing-day source was used; the 365-day preparation rule therefore excludes most of this window. SEEN2026 uses its already-seen continuous prefix. This is not a complete-history 2025 benchmark.','',
  'Carter sequence: daily high/squeeze/cup preparation; fixed pullback/breakout allocation; ATR stop; 72-hour cost-aware progress; three partial targets and daily runner trail. Cup geometry, rolling365/20 recency, squeeze substitute, Fib anchors, UTC72h, no-chase and conservative two-path OHLC execution are disclosed ZEL choices. Options, discretionary decisions and actual trader account returns are not reproduced.','',
  'C68 remains a historical partial-entry experiment. This candidate generates independent daily setups; it does not replay C68 or copy C63 entries. Exact lane identities remain distinct, even on coincident dates. Losing/winning trades removed from C63 are descriptive opportunity costs, not isolated causal effects.','']
 for per,v in s['periods'].items():
  lines += [f"## {per}", '', 'Checks: '+json.dumps(v['checks']), '', 'Four-way terminal reconciliation: '+json.dumps(v['accounting']['four_way_terminal_delta']), '', 'Closed risk: '+json.dumps(v['risk']), '', 'Winner coverage: '+json.dumps(v['winner_coverage']), '', 'Candidate exposure/ambiguity: '+json.dumps({k:v['candidate_metrics'][k] for k in ('reference_notional_symbol_days','ambiguity_count','ambiguity_local_mark_impact_bps','ambiguity_reference_allocations')}), '']
 return '\n'.join(lines)+'\n'

def verify():
 check()
 for per in PERIODS:
  data=packet(per);raw=gz(OUT/per/'RAW.json.gz');saved=gz(OUT/per/'RESULT.json.gz')
  recomputed=account.charge(raw,data,CAL[per]);need(p.sha(recomputed)==p.sha(saved),'RAW_COST_METRICS_PARITY');account.verify_money(saved)
  attr=json.loads(p.canonical(a.compare(old.baseline('C63',per),saved)));attr['comparison_type']='DISTINCT_LIFECYCLE_LANES_NO_FORCED_DATE_MATCH'
  need(attr==read(OUT/per/'ACCOUNTING_C63.json'),'ATTRIBUTION_PARITY')
 summary=summarize();need(p.sha(summary)==p.sha(read(OUT/'SUMMARY.json')),'SUMMARY_PARITY');need((OUT/'REPORT.md').read_text()==render(read(OUT/'SUMMARY.json')),'REPORT_PARITY')
 print('SAVED_RAW_TO_COST_TO_METRICS_AND_ATTRIBUTION_PASS; ECONOMIC_REPLAYS=0')

def run():
 freeze()
 for per in PERIODS:execute(per)
 summary=summarize();put('SUMMARY.json',summary);(OUT/'REPORT.md').write_text(render(read(OUT/'SUMMARY.json')))
 put('STATUS.json',dict(scope=SCOPE,status='REPORT_ONLY',owner_run=owner(),remaining_executions=[],economic_dispatch_closed=True))
 source.persist('JC both first FULLs complete and report only');verify()

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true');args=parser.parse_args()
 run() if args.execute else verify()
