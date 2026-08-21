#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
from pathlib import Path

from backend.research.rebuild.a1_exact25_survivor_gate_v1 import attach_survivor_gate

ROOT=Path(__file__).resolve().parents[3]
LEDGER=ROOT/'backend/research/rebuild/a1_exact25_disposition_ledger_v1.json'


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--receipt',required=True); ap.add_argument('--evidence',required=True); args=ap.parse_args()
    r=json.loads(Path(args.receipt).read_text()); e=json.loads(Path(args.evidence).read_text())
    if r.get('strategy_id')!='trend_rider' or e.get('strategy_id')!='trend_rider': raise RuntimeError('TREND_RIDER_ID_REQUIRED')
    if e.get('state')!='PASS_HARDENING_EVIDENCE': raise RuntimeError('PASS_HARDENING_EVIDENCE_REQUIRED')
    integrity=e.get('candidate_integrity') if isinstance(e.get('candidate_integrity'),dict) else {}
    if integrity.get('state')!='PASS' or integrity.get('source_quality_state')!='PASS':
        raise RuntimeError('PASS_CANDIDATE_INTEGRITY_REQUIRED')
    if list(integrity.get('integrity_defects') or []) or int(integrity.get('leakage_lookahead') or 0)!=0:
        raise RuntimeError('CANDIDATE_INTEGRITY_DEFECT')
    hardened=attach_survivor_gate(r,hardening_evidence=e)
    gate=hardened.get('survivor_gate') or {}
    if gate.get('state')!='PASS' or gate.get('passed') is not True: raise RuntimeError('SURVIVOR_GATE_NOT_PASS:'+json.dumps(gate,sort_keys=True))
    ledger=json.loads(LEDGER.read_text())
    row=ledger['strategies']['trend_rider']
    row.update({
      'status':'A1_SURVIVOR',
      'terminal_reason':'PROSPECTIVE_COST_ADJUSTED_SSOT_SURVIVOR_GATE_PASS',
      'receipt_sha':hardened.get('receipt_sha256'),
      'negative_control_state':'PASS_H4_NEGATIVE_CONTROL_SUPERIORITY',
      'hardening_evidence_sha':e.get('receipt_sha256'),
      'completed_trades':int(hardened.get('completed_trades') or 0),
      'net_expectancy_bps':(hardened.get('metrics') or {}).get('net_expectancy_bps'),
      'net_pnl_bps':(hardened.get('metrics') or {}).get('net_pnl_bps'),
      'profit_factor':(hardened.get('metrics') or {}).get('net_profit_factor'),
      'payoff':(hardened.get('metrics') or {}).get('net_payoff'),
      'win_rate':(hardened.get('metrics') or {}).get('win_rate'),
      'drawdown_bps':(hardened.get('metrics') or {}).get('max_drawdown_bps'),
    })
    if 'trend_rider' not in ledger['survivors']: ledger['survivors'].append('trend_rider')
    ledger['survivor_count']=len(ledger['survivors'])
    ledger['done_count']=sum(1 for x in ledger['strategies'].values() if isinstance(x,dict) and str(x.get('status','')).startswith('A1_') and x.get('status')!='ACTIVE')
    # Do not disturb another active heavy slot. If trend_rider itself was active, route later via controller.
    if ledger.get('active_strategy_id')=='trend_rider': ledger['active_strategy_id']=None
    LEDGER.write_text(json.dumps(ledger,indent=2,sort_keys=True,allow_nan=False))
    print(json.dumps({'state':'A1_SURVIVOR','strategy_id':'trend_rider','survivor_count':ledger['survivor_count'],'receipt_sha256':hardened.get('receipt_sha256'),'hardening_evidence_sha':e.get('receipt_sha256')},sort_keys=True))

if __name__=='__main__': main()
