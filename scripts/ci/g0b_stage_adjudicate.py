#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def stable_sha(value: Any) -> str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--raw',type=Path,required=True)
    ap.add_argument('--policy',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    raw=json.loads(args.raw.read_text())
    policy=json.loads(args.policy.read_text())
    rules=policy['rules']

    dup=int(raw.get('duplicate_active_owner_count',0))
    unresolved=int(raw.get('unresolved_active_reference_count',0))
    global_safe=(dup==0 and unresolved==0 and raw.get('execution_authority')=='NONE' and raw.get('order_authority')=='BLOCKED')

    rows=[]
    strategy_rows=raw.get('strategy25_rows',[])
    strategy_all_l0=all(r.get('L0_PRESENT')=='PASS' for r in strategy_rows) and len(strategy_rows)==25
    strategy_all_registry=all(r.get('registry_bound') is True for r in strategy_rows) and len(strategy_rows)==25

    for r in raw.get('module_rows',[]):
        comp=r['component']
        l0=r.get('L0_PRESENT')=='PASS'
        active=int(r.get('active_bound_source_count',0))>0
        rule=rules.get(comp,{})
        if not l0:
            status='HOLD_REQUIRED_BINDING_GAP'
            reason='L0 canonical source incomplete'
        elif comp=='STRATEGY_SIGNAL':
            if strategy_all_l0 and strategy_all_registry and global_safe:
                status='PASS_REGISTRY_BOUND_LIBRARY'
                reason='25/25 legacy strategies canonical-present and registry-bound; runtime activation intentionally not required at G0'
            else:
                status='HOLD_REQUIRED_BINDING_GAP'
                reason='strategy25 library/registry binding incomplete'
        elif comp=='ZICO' and active:
            if global_safe:
                status='PASS_ACTIVE_BOUND'
                reason='existing active owner allowed under execution=NONE/order=BLOCKED advisory boundary'
            else:
                status='HOLD_UNAUTHORIZED_ACTIVE_OWNER'
                reason='active owner exists without fail-closed global authority boundary'
        elif not rule.get('required_now',False):
            if active:
                status='HOLD_UNAUTHORIZED_ACTIVE_OWNER'
                reason='deferred component unexpectedly active without explicit G0 allowance'
            elif rule.get('deferred_until'):
                status='PASS_DEFERRED_BY_DESIGN'
                reason=f"L0 complete; activation deferred until {rule['deferred_until']}"
            else:
                status='HOLD_REQUIRED_BINDING_GAP'
                reason='no declared activation stage'
        else:
            status='PASS_ACTIVE_BOUND' if active and global_safe else 'HOLD_REQUIRED_BINDING_GAP'
            reason='required-now module active-bound' if status.startswith('PASS') else 'required-now binding not proven'
        rows.append({
            'component':comp,
            'raw_L0_PRESENT':r.get('L0_PRESENT'),
            'raw_L1_BOUND':r.get('L1_BOUND'),
            'active_bound_source_count':r.get('active_bound_source_count',0),
            'stage_required_now':bool(rule.get('required_now',False)),
            'deferred_until':rule.get('deferred_until'),
            'stage_aware_L1':status,
            'reason':reason,
        })

    legacy_rows=[]
    for r in strategy_rows:
        ok=(r.get('L0_PRESENT')=='PASS' and r.get('registry_bound') is True and global_safe)
        legacy_rows.append({
            'strategy':r['strategy'],
            'stage_aware_L1':'PASS_REGISTRY_BOUND_LIBRARY' if ok else 'HOLD_REQUIRED_BINDING_GAP',
            'runtime_activation_required':False,
            'migration_target':'VARIANT|ABSORB|OVERLAY|QUARANTINE|KILL',
        })

    alpha_rows=[]
    for r in raw.get('alpha_family_rows',[]):
        fam=r['family']; l0=r.get('L0_PRESENT')=='PASS'
        key={'trend_momentum':'TREND_MOMENTUM','carry_flow':'CARRY_FLOW','relative_value_psa':'RELATIVE_VALUE_PSA'}[fam]
        rule=rules[key]
        if not l0:
            status='HOLD_REQUIRED_BINDING_GAP'; reason='alpha family contract not present'
        elif fam=='trend_momentum':
            status='PASS_STAGE_DECLARED'; reason='P2 next-stage BASE contract declared; runtime/economic validation belongs to P2'
        else:
            status='PASS_DEFERRED_BY_DESIGN'; reason=f"source/economic binding deferred until {rule['deferred_until']}"
        alpha_rows.append({
            'family':fam,
            'contract_status':r.get('contract_status'),
            'stage_aware_L1':status,
            'deferred_until':rule.get('deferred_until'),
            'reason':reason,
        })

    statuses=[r['stage_aware_L1'] for r in rows+legacy_rows+alpha_rows]
    pass_count=sum(s.startswith('PASS_') for s in statuses)
    blockers=[r for r in rows+legacy_rows+alpha_rows if not r['stage_aware_L1'].startswith('PASS_')]
    state='PASS_G0B_STAGE_AWARE_L0_L1' if not blockers and len(statuses)==40 else 'HOLD_G0B_STAGE_AWARE_BINDING_GAPS'
    receipt={
        'schema_version':'zel.g0b.stage_aware_adjudication.v1',
        'state':state,
        'current_stage':policy['current_stage'],
        'raw_diagnostic_state':raw.get('state'),
        'raw_l0':f"{raw.get('l0_pass_total')}/{raw.get('l0_total')}",
        'raw_active_binding_l1':f"{raw.get('l1_pass_total')}/{raw.get('l1_total')}",
        'stage_aware_l1_pass_count':pass_count,
        'stage_aware_l1_total':len(statuses),
        'module_rows':rows,
        'strategy25_rows':legacy_rows,
        'alpha_family_rows':alpha_rows,
        'blockers':blockers,
        'interpretation':'raw active-binding L1 remains diagnostic; G0 installation PASS does not activate downstream modules blocked by ALPHA_FIRST_LOCK',
        'destructive_cleanup_authority':False,
        'runtime_mutated':False,
        'service_state_mutated':False,
        'selection_authority':False,
        'promotion_authority':False,
        'execution_authority':'NONE',
        'order_authority':'BLOCKED',
        'action':'hold',
    }
    receipt['receipt_sha256']=stable_sha(receipt)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'state':state,'stage_aware_L1':f'{pass_count}/{len(statuses)}','blocker_count':len(blockers)},sort_keys=True))
    return 0 if state.startswith('PASS_') else 2

if __name__=='__main__':
    raise SystemExit(main())
