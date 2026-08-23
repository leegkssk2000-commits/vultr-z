#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as exact

ROOT=Path(__file__).resolve().parents[3]
INVENTORY=ROOT/'backend/research/rebuild/strategy25_structural_inventory_v2.json'
POLICY=ROOT/'backend/research/rebuild/keltner_trend_volatility_cool_child_policy_v1.py'
PREREG=ROOT/'backend/research/rebuild/a1_keltner_volatility_cool_loss_repair_prereg_v1.json'
MIN_TRADES=25


def read(p:Path)->dict[str,Any]:
    x=json.loads(p.read_text(encoding='utf-8'))
    if not isinstance(x,dict): raise RuntimeError(f'OBJECT_REQUIRED:{p}')
    return x


def ms(s:str)->int:
    return int(datetime.fromisoformat(s.replace('Z','+00:00')).astimezone(timezone.utc).timestamp()*1000)


def metrics(ts:list[dict[str,Any]])->dict[str,Any]:
    gross=[float(x['gross_bps']) for x in ts]; net=[float(x['net_bps']) for x in ts]
    wins=[x for x in net if x>0]; losses=[-x for x in net if x<0]; gp=sum(wins); gl=sum(losses)
    aw=gp/len(wins) if wins else None; al=gl/len(losses) if losses else None
    return {'trade_count':len(ts),'gross_pnl_bps':sum(gross),'gross_expectancy_bps':sum(gross)/len(gross) if gross else None,
            'net_pnl_bps':sum(net),'net_expectancy_bps':sum(net)/len(net) if net else None,
            'net_profit_factor':ev.profit_factor(gp,gl),'net_payoff':aw/al if aw is not None and al not in (None,0) else None,
            'win_rate':len(wins)/len(net) if net else None,'max_drawdown_bps':ev.max_drawdown(net)}


def run_shadow(out:Path)->dict[str,Any]:
    inv=read(INVENTORY); inv['strategies']['keltner_trend']['policy_owner']=str(POLICY.relative_to(ROOT))
    with tempfile.TemporaryDirectory(prefix='keltner_cool_shadow_') as td:
        ip=Path(td)/'inventory.json'; ip.write_text(json.dumps(inv,sort_keys=True,indent=2)+'\n',encoding='utf-8')
        old=exact.v1.INVENTORY_PATH; argv=sys.argv[:]
        try:
            exact.v1.INVENTORY_PATH=ip
            sys.argv=[argv[0],'--strategy-id','keltner_trend','--out',str(out),'--terminal-replay']
            exact.main()
        finally:
            exact.v1.INVENTORY_PATH=old; sys.argv=argv
    return read(out)


def run(out:Path)->dict[str,Any]:
    prereg=read(PREREG); boundary=str(prereg['fresh_boundary_utc']); bms=ms(boundary)
    with tempfile.TemporaryDirectory(prefix='keltner_cool_forward_') as td:
        base=run_shadow(Path(td)/'all.json')
    if str(base.get('policy_path') or '')!=str(POLICY.relative_to(ROOT)): raise RuntimeError('KELTNER_COOL_POLICY_MISMATCH')
    if list(base.get('integrity_defects') or []): raise RuntimeError('KELTNER_COOL_INTEGRITY_DEFECT')
    if int(base.get('leakage_lookahead') or 0)!=0: raise RuntimeError('KELTNER_COOL_LOOKAHEAD_DEFECT')
    if (base.get('terminal_replay') or {}).get('canonical_ledger_mutated') is not False: raise RuntimeError('CANONICAL_LEDGER_MUTATION_GUARD')
    fresh=[dict(x) for x in (base.get('trades') or []) if int(x.get('signal_ts') or 0)>=bms]
    fresh.sort(key=lambda x:(int(x.get('entry_ts') or 0),str(x.get('symbol') or '')))
    row=dict(base); row.update({
        'schema_version':'zel.a1.keltner.volatility_cool_loss_repair.forward.v1','candidate_id':prereg['candidate_id'],
        'changed_axis':prereg['changed_axis'],'fresh_boundary_utc':boundary,'completed_trades':len(fresh),'trades':fresh,'metrics':metrics(fresh),
        'sample_gap_to_25':max(0,MIN_TRADES-len(fresh)),'minimum_fresh_trades':MIN_TRADES,'preboundary_outcomes_counted':False,
        'preboundary_data_feature_warmup_only':True,'canonical_exact25_ledger_mutation':False,'strategy_parameters_changed':False,
        'thresholds_changed':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED',
        'live_trade_authority':'BLOCKED','exchange_order_submitted':False,'protected_mutations':0,
        'state':'WAIT_FRESH_25' if len(fresh)<MIN_TRADES else 'FRESH_25_READY_FOR_EXISTING_H4_H5',
        'next':'CONTINUE_HOURLY_FRESH_COLLECTION' if len(fresh)<MIN_TRADES else 'RUN_EXISTING_H4_H5_WITHOUT_RETUNING'
    })
    row['receipt_sha256']=ev.stable_sha({k:v for k,v in row.items() if k!='receipt_sha256'})
    out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(row,sort_keys=True,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return row


def self_test()->int:
    p=read(PREREG); assert p['fresh_boundary_utc']=='2026-08-23T07:15:00Z'; assert p['numeric_threshold_sweep'] is False
    print('PASS_A1_KELTNER_VOLATILITY_COOL_LOSS_REPAIR_FORWARD_V1_SELF_TEST'); return 0


def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--out',type=Path,default=Path('out/a1_keltner_volatility_cool_loss_repair_forward_latest.json')); ap.add_argument('--self-test',action='store_true'); a=ap.parse_args()
    if a.self_test:return self_test()
    r=run(a.out); print(json.dumps({k:r.get(k) for k in ['state','completed_trades','sample_gap_to_25','next']},sort_keys=True)); return 0

if __name__=='__main__': raise SystemExit(main())
