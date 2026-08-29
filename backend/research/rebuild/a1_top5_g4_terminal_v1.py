#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

DEFAULT = Path('backend/research/rebuild/a1_top5_g4_terminal_latest.json')
ALLOWED = {
    'G4_PASS_SURVIVOR_READY',
    'WAIT_NEW_T',
    'FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED',
}

def validate(path: Path) -> dict:
    r=json.loads(path.read_text(encoding='utf-8'))
    assert r['schema_version']=='zel.a1.top5.g4_terminal.v1'
    assert r['state']=='G4_TERMINAL_TARGET_SET_COMPLETE'
    ts=r['targets']
    assert len(ts)==5
    assert len({x['strategy'] for x in ts})==5
    assert all(x['terminal_state'] in ALLOWED for x in ts)
    assert r['summary']['terminal_target_count']==5
    assert r['summary']['unresolved']==0
    counts={k:0 for k in ALLOWED}
    for x in ts: counts[x['terminal_state']]+=1
    assert counts['WAIT_NEW_T']==r['summary']['target_wait_new_t']==1
    assert counts['FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED']==r['summary']['target_architecture_replacement_required']==4
    assert counts['G4_PASS_SURVIVOR_READY']==r['summary']['target_g4_pass_survivor_ready']==0
    broad=r['existing_g4_survivor_reference']
    assert broad['state']=='G4_PASS_SURVIVOR_READY' and broad['T']==30
    assert r['selection_authority'] is False and r['promotion_authority'] is False
    assert r['execution_authority']=='NONE' and r['order_authority']=='BLOCKED' and r['live_trade_authority']=='BLOCKED'
    assert r['protected_mutations']==0 and r['rules']['runtime_mutated'] is False and r['rules']['production_strategy_mutated'] is False
    return {'state':r['state'],'targets':len(ts),'unresolved':0,'counts':counts,'broad_survivor_T':broad['T']}

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--receipt',type=Path,default=DEFAULT); ap.add_argument('--self-test',action='store_true'); a=ap.parse_args()
    if a.self_test:
        print(json.dumps(validate(a.receipt),sort_keys=True)); print('PASS_A1_TOP5_G4_TERMINAL_V1_SELF_TEST'); return 0
    print(json.dumps(validate(a.receipt),sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
