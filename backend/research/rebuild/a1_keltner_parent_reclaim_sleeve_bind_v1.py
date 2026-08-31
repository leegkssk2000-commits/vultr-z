#!/usr/bin/env python3
from __future__ import annotations
import argparse,copy,json
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[3]
SSOT=ROOT/'backend/research/rebuild/a1_top5_latest_only_ssot_v1.json'
FREEZE=ROOT/'backend/research/contracts/a1_keltner_parent_reclaim_sleeve_freeze_v1.json'
FRESH=ROOT/'backend/research/rebuild/a1_keltner_parent_reclaim_sleeve_fresh_latest.json'

def read(p:Path)->dict[str,Any]:
 x=json.loads(p.read_text());
 if not isinstance(x,dict):raise RuntimeError('OBJECT_REQUIRED')
 return x

def run(out:Path)->dict[str,Any]:
 s,f,r=read(SSOT),read(FREEZE),read(FRESH); o=copy.deepcopy(s)
 lane=next(x for x in o['top5'] if x.get('lane_id')=='keltner_trend_main')
 lane['parent_preserving_reclaim_sleeve']={'state':f['state'],'child_id':f['child_id'],'parent_preserved':True,'donor_source_development_T_not_consumed':f['source_validation']['parent_T']*0+97,'historical_intersection':f['source_validation'],'prospective_boundary':f['prospective_boundary'],'fresh':{'state':r['state'],'fresh_T':r['fresh_T'],'minimum_fresh_T':r['minimum_fresh_T'],'metrics':r['metrics'],'fresh_gate_pass':r['fresh_gate_pass'],'receipt_sha256':r['receipt_sha256']},'historical_formal_g4_credit_T':0,'historical_formal_g5_credit_T':0,'roadmap_blocking':False,'parent_terminal_state_unchanged_until_fresh_gate':True,'selection_authority':False,'promotion_authority':False}
 o.setdefault('record_policy',{})['keltner_parent_reclaim_sleeve_does_not_consume_97T_donor_population']=True
 o['selection_authority']=False;o['promotion_authority']=False;o['execution_authority']='NONE';o['order_authority']='BLOCKED';o['live_trade_authority']='BLOCKED'
 out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(o,indent=2,sort_keys=False,allow_nan=False)+'\n');return o

def main():
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();run(a.out)
if __name__=='__main__':main()
