"""One already-used-2026 evaluation of the exact PR1213 D; no strategy edits.

No IO on import. Existing D2025, KR3, B and E outcomes are reused. Formal
admission, OOS access, market requests and new parameter hypotheses stay zero.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from dataclasses import asdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from backend.research.rebuild import step7_kr3_mechanism_separation_v1 as p
from backend.research.rebuild import step7_kr3_winner_accounting_v1 as acct

ROOT = p.ROOT
SCOPE = 'KR3_D_EXACT_SEEN2026_AFTER_PR1215_V1'
OUT = p.CAMPAIGN + '/D_PARENT_2026'
MODE_ID = 'W6_RECHECK_SHIFTED_EXIT_ANCHOR'
CALENDAR = [1778198400000, 1788566400000]
BINDINGS = {'rows_by': '406e72401bec107c31ac17fd9742489f5980ca411b0f848613692fd2d00d29af',
            'costs': 'e7b29de0b1810d14e02847917e951301f4d9a30da190ed7c6fc4cafbca581020',
            'policy': 'dc08e55afdb1fbf2b952bf9baed3a25a2ebcf7c1b3abed4e0b97f73e5d8ce031'}
CANONICAL_MODE = {'id': MODE_ID, 'delay': 6, 'recheck': True,
                  'reference_anchor': 'SHIFTED', 'exit_anchor': 'SHIFTED',
                  'require_origin_half': True}
canonical, sha, write_new = p.canonical, p.sha, p.write_new

def require(condition, message):
    if not condition:
        raise ValueError(message)

def mode():
    value = next(m for m in p.MODES if m.id == MODE_ID)
    require(asdict(value) == CANONICAL_MODE, 'ORIGINAL_D_MODE_DRIFT')
    return value

def dependencies():
    value = p.dependencies()
    for name in ('kr3_d_seen2026_v1.py', 'step7_kr3_winner_accounting_v1.py',
                 'break_channel_q1_metrics_v1.py'):
        path = 'backend/research/rebuild/' + name
        value[path] = hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
    return value

def validate_packet(packet):
    require(set(packet['rows_by']) == set(p.native.SYMBOLS), 'SEVEN_ORIGINAL_SYMBOLS')
    require(all(len(rows) == 3748 for rows in packet['rows_by'].values()), 'EXACT_USED_PREFIX')
    require(packet['policy']['development_interval_ms'] == CALENDAR, 'ORIGINAL_2026_CALENDAR')
    for key, digest in BINDINGS.items():
        require(sha(packet[key]) == digest, 'EXACT_INPUT_HASH:' + key)
    for rows in packet['rows_by'].values():
        require(rows[0]['bar_open_ts'] == 1734595200000 and rows[-1]['bar_close_ts'] == CALENDAR[1], 'PREFIX_ENDPOINTS')
    require(asdict(mode()) == CANONICAL_MODE, 'MODE_DRIFT')

def freeze(packet):
    validate_packet(packet)
    oldspec = json.loads((ROOT/p.OUTPUT/'SPEC.json').read_bytes())
    current = p.dependencies()
    require(p.native.contracts.check_seal(oldspec), 'PR1213_SPEC_SEAL')
    for path, digest in oldspec['files_sha256'].items():
        require(current.get(path) == digest, 'PR1213_ORIGINAL_CODE_CHANGED:' + path)
    budget_raw = (ROOT/p.BUDGET).read_bytes()
    budget = json.loads(budget_raw)
    require((budget['cumulative_actual'], budget['cumulative_actual_evaluations']) == (45,63), 'INHERITED_BUDGET_MOVED')
    require('kr3_d_seen2026_allocation' not in budget, 'EXISTING_D_ALLOCATION_REQUIRES_RECOVERY')
    return p.native.contracts.seal({'scope': SCOPE, 'exact_parent_mode': CANONICAL_MODE,
      'run': 'D-SEEN2026', 'max_economic_runs': 1, 'new_hypotheses': 0,
      'evaluation_ordinal':64, 'prior_candidates':45, 'prior_evaluations':63,
      'inheritance_budget_sha256':hashlib.sha256(budget_raw).hexdigest(),
      'original_d_spec_sha256':oldspec['receipt_sha256'],
      'files_sha256':dependencies(), 'input_hashes':BINDINGS,
      'start_ms':CALENDAR[0], 'runoff_end_ms':CALENDAR[1],
      'cost_semantics':p.old.COST_SEMANTICS, 'seed':'NO_RANDOM',
      'selection':'User selected existing tested D as development parent; no retroactive candidate count or formal promotion',
      'accounting':'reuse stored origin-state accounting and capped parent-winner profit; descriptive only',
      'comparison':'D vs saved KR3 in each period; saved B/E/C as named diagnostics, no cross-period total ranking',
      'formal_credit':0, 'independent':False, 'economic_pass_claimed':False,
      'market_requests':0, 'unused_OOS_reads':0, 'provider_calls':0, 'orders':0})

def verify(spec, packet=None):
    require(p.native.contracts.check_seal(spec) and spec['scope']==SCOPE, 'SPEC_SEAL_SCOPE')
    require(spec['exact_parent_mode']==asdict(mode()) and spec['input_hashes']==BINDINGS, 'EXACT_D_OR_INPUT_IDENTITY')
    require(spec['files_sha256']==dependencies(), 'FROZEN_CODE_DRIFT')
    require((spec['start_ms'],spec['runoff_end_ms'],spec['evaluation_ordinal'])==(*CALENDAR,64), 'FIXED_PERIOD_ORDINAL')
    if packet is not None: validate_packet(packet)

def claim_budget(budget, spec, attempt):
    value=deepcopy(budget)
    require((value['cumulative_actual'],value['cumulative_actual_evaluations'])==(45,63), 'BUDGET_ALREADY_USED_OR_MOVED')
    require('kr3_d_seen2026_allocation' not in value, 'D_SCOPE_ALREADY_CLAIMED')
    require(not any(t['actual_experiment_ordinal']==64 for t in value['trials']), 'ORDINAL_USED')
    value['kr3_d_seen2026_allocation']={'scope_key':SCOPE,'used':1,'max_executions':1,
        'no_retry':True,'status':'RESERVED_BEFORE_REPLAY','new_hypotheses':0,
        'specification_sha256':spec['receipt_sha256'],'output_path':OUT}
    value['trials'].append(attempt)
    value['cumulative_actual_evaluations']=64
    return value

def run_d(packet,spec):
    verify(spec,packet)
    out={k:[] for k in ('trades','open_observations','events','trace','reference_opportunities','reference_events')}
    out['audit']={}
    with p.native.sensitivity():
        for symbol,rows in sorted(packet['rows_by'].items()):
            bundle=p.d.build_bundle(rows,p.d.PARENT_SPEC,eval_start_ms=CALENDAR[0],eval_end_ms=CALENDAR[1])
            raw=p.replay_symbol(rows,bundle,mode(),start=CALENDAR[0],end=CALENDAR[1])
            charged=p.account.charge_result(raw,symbol,'keltner_trend_main',MODE_ID,packet['policy'],packet['costs'],rows)
            for kind in ('trades','open_observations','events','trace'):
                for row in charged[kind]:
                    index=row.get('original_signal_index',row.get('signal_index'))
                    row.update(mechanism_origin_id=f'{symbol}:{rows[index]["bar_close_ts"]}',
                               d_expansion_spec_sha256=spec['receipt_sha256'])
                    key='trade_sha256' if kind=='trades' else 'observation_sha256' if kind=='open_observations' else None
                    if key:
                        row.pop(key,None); row[key]=p.account.old.digest(row)
                out[kind].extend(charged[kind])
            for kind in ('reference_opportunities','reference_events'):
                out[kind].extend(dict(x,symbol=symbol) for x in raw[kind])
            out['audit'][symbol]=raw['audit']
    out.update(mode=CANONICAL_MODE,scope=SCOPE,run='D-SEEN2026',
               specification_sha256=spec['receipt_sha256'],independent=False,formal_credit=0)
    out['metrics']=p.old.metrics(out['trades'],out['open_observations'],spec,packet['rows_by'],packet['costs'])
    out['economic_digest']=sha({k:out[k] for k in ('trades','open_observations','events','trace','reference_opportunities','reference_events','audit')})
    return out

def execute(packet,spec):
    verify(spec,packet)
    root=ROOT/OUT; budgetpath=ROOT/p.BUDGET
    original=budgetpath.read_bytes()
    require(hashlib.sha256(original).hexdigest()==spec['inheritance_budget_sha256'], 'SHARED_BUDGET_BASE_DRIFT')
    attempt={'scope':SCOPE,'run':'D-SEEN2026','actual_experiment_ordinal':64,
       'classification':'EXISTING_PR1213_D_SAME_RULE_SEEN_PERIOD_EXPANSION',
       'new_candidate':False,'status':'RESERVED_BEFORE_REPLAY',
       'specification_sha256':spec['receipt_sha256'],'started_unix_ns':time.time_ns(),
       'pid':os.getpid(),'retry_allowed':False}
    updated=claim_budget(json.loads(original),spec,attempt)
    # Exclusive creation is fail-closed on retries. The remote freeze/claim is
    # persisted before this sole-owner call; CI only verifies saved results.
    write_new(root/'ATTEMPT.json',canonical(attempt))
    pending=budgetpath.with_suffix('.d2026.pending')
    write_new(pending,(json.dumps(updated,sort_keys=True,indent=2)+'\n').encode());os.replace(pending,budgetpath)
    try:
        result=run_d(packet,spec)
        digest=write_new(root/'RESULT.json.gz',gzip.compress(canonical(result),mtime=0))
        receipt={'scope':SCOPE,'run':'D-SEEN2026','status':'COMPLETED',
            'ordinal':64,'specification_sha256':spec['receipt_sha256'],
            'result_sha256':digest,'economic_digest':result['economic_digest'],
            'metrics':{k:v for k,v in result['metrics'].items() if k!='daily'},
            'runtime':sys.version,'new_hypotheses':0,'formal_credit':0,'independent':False}
        write_new(root/'RECEIPT.json',canonical(receipt))
        updated['kr3_d_seen2026_allocation'].update(status='COMPLETED',completed=1)
        write_new(pending,(json.dumps(updated,sort_keys=True,indent=2)+'\n').encode());os.replace(pending,budgetpath)
        return result
    except BaseException as exc:
        write_new(root/'FAILURE.json',canonical({'scope':SCOPE,'status':'FAILED_OR_UNKNOWN_CONSUMED','error_type':type(exc).__name__,'error':str(exc),'retry_allowed':False}))
        raise

def verify_saved():
    root=ROOT/OUT;spec=json.loads((root/'SPEC.json').read_bytes());verify(spec)
    if not (root/'RECEIPT.json').exists():
        require(not (root/'ATTEMPT.json').exists(),'ATTEMPT_WITHOUT_RESULT_NOT_COMPLETE')
        return {'state':'FROZEN_NOT_EXECUTED','economic_complete':False}
    receipt=json.loads((root/'RECEIPT.json').read_bytes());raw=(root/'RESULT.json.gz').read_bytes()
    require(receipt['result_sha256']==hashlib.sha256(raw).hexdigest(),'RESULT_BYTES_DRIFT')
    result=json.loads(gzip.decompress(raw))
    require(result['specification_sha256']==spec['receipt_sha256'],'RESULT_SPEC_DRIFT')
    require(result['economic_digest']==sha({k:result[k] for k in ('trades','open_observations','events','trace','reference_opportunities','reference_events','audit')}),'ECONOMIC_DIGEST_DRIFT')
    budget=json.loads((ROOT/p.BUDGET).read_bytes())
    require(budget['cumulative_actual']==45 and budget['cumulative_actual_evaluations']>=64,'COUNTER_DRIFT')
    require(budget['kr3_d_seen2026_allocation']['used']==1,'ALLOCATION_DRIFT')
    return {'state':'STORED_RESULT_VERIFIED_NO_REPLAY','economic_complete':True,'completed':len(result['trades']),'open':len(result['open_observations'])}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path)
    parser.add_argument('--freeze',action='store_true');parser.add_argument('--execute',action='store_true')
    parser.add_argument('--verify-saved',action='store_true');args=parser.parse_args()
    require(sum((args.freeze,args.execute,args.verify_saved))==1,'EXACTLY_ONE_ACTION')
    if args.verify_saved:print(json.dumps(verify_saved()));return
    require(args.input is not None,'EXACT_INPUT_REQUIRED')
    packet=json.loads(gzip.decompress(args.input.read_bytes()))
    if args.freeze:
        value=freeze(packet);write_new(ROOT/OUT/'SPEC.json',canonical(value));print(value['receipt_sha256'])
    else:
        value=execute(packet,json.loads((ROOT/OUT/'SPEC.json').read_bytes()))
        print(json.dumps({k:v for k,v in value['metrics'].items() if k!='daily'},sort_keys=True))

if __name__=='__main__':main()
