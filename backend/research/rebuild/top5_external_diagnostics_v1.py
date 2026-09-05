"""Five preregistered parent questions, prior outcomes only; no child simulation."""
import json,gzip,pathlib
from backend.research.rebuild import top5_development_repair_v1 as old
from backend.research.rebuild.top5_external_features_v1 import Features
from backend.research.rebuild.top5_external_metrics_v1 import diagnostics
from backend.research.architecture_factory.g5a_source_admission_v1 import read,seal,require_development,ROOT

def run(data_dir,verify_only=False):
    root=ROOT/'research/development_evidence/TOP5_EXTERNAL_20260905_V1';p=read(old.POLICY);dev=require_development(read(old.probe.STAGE),ROOT)
    rows4,access=old.probe.load_development(data_dir,read(old.probe.POLICY),dev)
    rows1={s:json.loads(gzip.decompress((ROOT/old.OUTPUT/'native_1h'/(s+'.json.gz')).read_bytes())) for s in p['native_symbols']}
    trades=[json.loads(x) for x in gzip.decompress((ROOT/old.OUTPUT/'baseline/trades.jsonl.gz').read_bytes()).splitlines()]
    axes=json.loads((root/'batch_preregistration.json').read_text())['diagnostic_axes_before_outcomes'];result={}
    for lane in old.LANES:
     ts=[t for t in trades if t['lane_id']==lane];diag,labels=diagnostics(ts,*p['development_interval_ms']);maps={};featuremaps={}
     if lane!=old.LANES[2]:
      data=rows1 if lane in old.LANES[:2] else rows4;interval=3600000 if lane in old.LANES[:2] else 14400000
      fs={s:Features(rs,interval) for s,rs in data.items()}
      featuremaps={t['identity']:fs[t['symbol']].at(t['signal_index'],t['side']) for t in ts}
      for axis in axes:
       maps[axis]={}
       for value in [False,True]:
        subset=[t for t in ts if featuremaps[t['identity']][axis]==value];wins=[t for t in subset if t['net_bps']>0];loss=[t for t in subset if t['net_bps']<0]
        maps[axis][str(value)]={'T':len(subset),'net_bps':sum(t['net_bps'] for t in subset),'E_bps':sum(t['net_bps'] for t in subset)/len(subset) if subset else None,'wins':len(wins),'profit_bps':sum(t['net_bps'] for t in wins),'loss_bps':-sum(t['net_bps'] for t in loss)}
     result[lane]={'diagnostics':diag,'feature_conditions':maps,'entry_feature_by_identity':featuremaps}
    r=seal({'batch':'TOP5_EXTERNAL_20260905_V1','prior_baseline_receipt_sha':read(str(pathlib.Path(old.OUTPUT)/'baseline/receipt.json'))['receipt_sha256'],'lanes':result,'source_access':access,'interpretation':'ADAPTIVE_DEVELOPMENT_DIAGNOSIS_NOT_INDEPENDENT_CONFIRMATION','validation_OOS_read':False})
    old.probe.write_immutable(root/'loss_winner_map.json',old.probe.canonical(r),verify_only=verify_only)
    return r

if __name__ == "__main__":
    import argparse
    a=argparse.ArgumentParser();a.add_argument("--data-dir",type=pathlib.Path,required=True);a.add_argument("--verify-only",action="store_true");v=a.parse_args()
    print(run(v.data_dir,v.verify_only)["receipt_sha256"])
