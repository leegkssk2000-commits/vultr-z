#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
POLICY=ROOT/'backend/research/contracts/a1_trend_rider_direct_ab_next_axis_policy_v1.json'


def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--out',default='out/a1_trend_rider_direct_ab_axis_guard_v1.json'); args=ap.parse_args()
    c=json.loads(POLICY.read_text())
    defects=[]
    axes=list(c.get('axis_order') or [])
    if len(axes)!=len(set(axes)) or len(axes)<5: defects.append('AXIS_ORDER_INVALID')
    for k in ('terminal_axis_retest_forbidden','same_axis_parameter_rescue_forbidden','one_axis_per_child','new_entry_or_exit_identity_routes_back_to_A1','A2_cost_revalidation_required_after_A1_pass','A3_fresh_durability_required_after_A2_pass'):
        if c.get(k) is not True: defects.append(f'POLICY_NOT_TRUE:{k}')
    if c.get('baseline_identity')!='ORIGINAL_TREND_RIDER_FRESH_W1_W2_W3': defects.append('BASELINE_DRIFT')
    if c.get('execution_authority')!='NONE' or c.get('order_authority')!='BLOCKED' or c.get('live_trade_authority')!='BLOCKED': defects.append('AUTHORITY_NOT_BLOCKED')
    r={'state':'PASS_DIRECT_AB_AXIS_GUARD' if not defects else 'HOLD_DIRECT_AB_AXIS_GUARD','defects':defects,'axis_order':axes,'action':'hold','execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED'}
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(r,sort_keys=True,indent=2)+'\n')
    print(json.dumps(r,sort_keys=True)); return 0 if not defects else 1

if __name__=='__main__': raise SystemExit(main())
