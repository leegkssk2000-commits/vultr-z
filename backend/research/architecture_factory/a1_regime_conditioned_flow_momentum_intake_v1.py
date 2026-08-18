from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from backend.tools.zel_economic_hardening_gate_v1 import h2_archetype_intake, stable_sha

POLICY=Path('backend/research/zel_economic_hardening_policy_v1.json')
PREREG=Path('backend/research/architecture_factory/a1_regime_conditioned_flow_momentum_prereg_v1.json')
FACTORY=Path('config/zel_production_alpha_factory_v1.json')


def read(p): return json.loads(Path(p).read_text())
def sha_file(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def registry_snapshot(factory):
    sig=[]
    for name,row in sorted((factory.get('families') or {}).items()):
        mech=str(row.get('mechanism') or row.get('status') or '').strip()
        if mech: sig.append(f"{name} {mech}")
    material={'schema_version':'zel.archetype_registry.snapshot.v1','state':'PASS_ARCHETYPE_REGISTRY_SNAPSHOT','observed_at':datetime.now(timezone.utc).isoformat(),'registry_count':len(sig),'registry_sha256':stable_sha(sig),'verified_empty':False}
    material['receipt_sha256']=stable_sha(material)
    return material,sig

def run(source_receipt_path, out_path):
    prereg=read(PREREG); factory=read(FACTORY); policy=read(POLICY)['h2_new_archetype_intake']; src=read(source_receipt_path)
    if src.get('state')!='PASS_RCFM_SOURCE_READY': raise RuntimeError('RCFM_SOURCE_NOT_READY')
    reg,corpus=registry_snapshot(factory)
    candidate={'archetype_id':prereg['archetype_id'],'economic_mechanism':prereg['economic_mechanism'],'falsification_rule':prereg['falsification_rule'],'structural_signature':prereg['structural_signature'],'entry_time_features':prereg['entry_time_features'],'external_evidence_ids':prereg['external_evidence_ids'],'source_sha256':str(src['source_sha256']),'data_sha256':str(src['data_sha256']),'code_sha256':sha_file(PREREG),'existing_structural_signatures':corpus,'registry_snapshot_receipt':reg,'parameter_variant_of_rejected_family':False}
    h2=h2_archetype_intake(candidate,policy)
    out={'schema_version':'zel.a1.rcfm.intake_receipt.v1','state':'PASS_RCFM_H2_INTAKE_READY' if h2['state']=='PASS_ARCHETYPE_INTAKE' else 'HOLD_RCFM_H2_INTAKE','candidate_id':prereg['candidate_id'],'archetype_id':prereg['archetype_id'],'factory_run':prereg['factory_run'],'source_receipt':src,'h2_receipt':h2,'fresh_boundary_assigned':False,'next_permitted_action':'FREEZE_EVALUATOR_POLICY_THEN_ASSIGN_FRESH_PROSPECTIVE_BOUNDARY' if h2['state']=='PASS_ARCHETYPE_INTAKE' else 'HOLD','selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','exchange_order_submitted':False,'protected_mutations':0}
    out['receipt_sha256']=stable_sha(out)
    Path(out_path).parent.mkdir(parents=True,exist_ok=True); Path(out_path).write_text(json.dumps(out,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'state':out['state'],'h2':h2['state'],'max_similarity':h2['maximum_structural_similarity'],'source_rows':src.get('history_rows')},sort_keys=True))
    return 0 if h2['state']=='PASS_ARCHETYPE_INTAKE' else 2

def self_test():
    p=read(PREREG); assert p['candidate_id']=='NEW_RCFM_001'; assert p['mode']=='NEW_ARCHITECTURE'; assert p['baseline_mutated'] is False; assert p['fresh_prospective_boundary_utc'] is None; assert len(p['external_evidence_ids'])>=1; print('PASS_RCFM_INTAKE_STATIC'); return 0

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--source-receipt'); ap.add_argument('--out',default='out/a1_rcfm_intake.json'); ap.add_argument('--self-test',action='store_true'); a=ap.parse_args()
    if a.self_test:return self_test()
    if not a.source_receipt: raise SystemExit('source receipt required')
    return run(a.source_receipt,a.out)
if __name__=='__main__': raise SystemExit(main())
