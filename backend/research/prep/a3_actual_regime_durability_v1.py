from __future__ import annotations

import argparse,json
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[3]
TAXONOMY=ROOT/'backend/research/prep/a3_regime_taxonomy_v1.json'
LEDGER=ROOT/'backend/research/rebuild/a1_exact25_disposition_ledger_v1.json'
HARDENING=ROOT/'backend/research/rebuild/diagnostics/trend_rider_hardening_latest.json'
REQUIRED=['trend_strength','realized_vol_pct','spread_bps','depth_usdt','funding_8h_pct','oi_change_pct']
AUTH={'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','protected_mutations':0,'action':'hold'}

def read(p): return json.loads(Path(p).read_text())

def evaluate(a2:dict[str,Any])->dict[str,Any]:
    if a2.get('state')!='PASS_A2_COST_TURNOVER': raise RuntimeError('A2_PASS_REQUIRED')
    tax=read(TAXONOMY); ledger=read(LEDGER); h=read(HARDENING)
    row=ledger['strategies']['trend_rider']
    if row.get('status')!='A1_FINALIST_PARKED': raise RuntimeError('A1_LINEAGE_INVALID')
    # Current A1/A2 receipts predate A3 entry-context capture. Never infer missing
    # entry-time liquidity/funding/OI from current snapshots or outcome PnL.
    available=['symbol','signal_ts','entry_ts','side','gross_expectancy_bps','net_expectancy_bps']
    missing=list(REQUIRED)
    h5=h.get('h5_receipt') or {}
    result={
      'schema_version':'zel.a3.actual_regime_durability.v1','stage':'A3','candidate_id':'trend_rider',
      'state':'HOLD_A3_ENTRY_CONTEXT_INCOMPLETE','a2_receipt_sha256':a2.get('receipt_sha256'),
      'taxonomy_sha_source':'backend/research/prep/a3_regime_taxonomy_v1.json',
      'taxonomy_required_inputs':list((tax.get('input_contract') or {}).get('required') or []),
      'available_historical_trade_fields':available,'missing_entry_time_fields':missing,
      'outcome_defined_regime':False,'historical_backfill_from_current_snapshot_forbidden':True,
      'existing_h5_diagnostics':{'state':h5.get('state'),'dimensions':h5.get('dimensions'),'maximum_profit_share_by_dimension':h5.get('maximum_profit_share_by_dimension'),'failed_leave_one_group_out':h5.get('failed_leave_one_group_out')},
      'entry_time_regime_owner':None,'owned_regime_net_positive':None,'fail_closed_outside_owned_regime':True,
      'global_durability_pass':False,'next_required_action':'FORWARD_A3_ENTRY_CONTEXT_CAPTURE',
      'note':'A3 entered. Existing H5 is diagnostic only; it cannot substitute for the sealed A3 taxonomy because historical spread/depth/funding/OI were not captured at entry.',
      **AUTH}
    import hashlib
    result['receipt_sha256']=hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--a2',type=Path,required=True);p.add_argument('--output',type=Path,default=Path('out/a3_actual_regime_durability_v1.json'));a=p.parse_args()
    r=evaluate(read(a.a2));a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'state':r['state'],'candidate_id':r['candidate_id'],'missing':r['missing_entry_time_fields'],'next':r['next_required_action'],'receipt_sha256':r['receipt_sha256']},sort_keys=True));return 0
if __name__=='__main__': raise SystemExit(main())
