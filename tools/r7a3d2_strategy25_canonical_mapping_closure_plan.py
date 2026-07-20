#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, tempfile
from collections import defaultdict
from pathlib import Path


def load(p):
    try:
        v=json.loads(Path(p).read_text()); return v if isinstance(v,dict) else {}
    except Exception: return {}

def sha(p):
    p=Path(p)
    if not p.is_file(): return None
    h=hashlib.sha256(); h.update(p.read_bytes()); return h.hexdigest()

def atomic(p,v):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    fd,t=tempfile.mkstemp(dir=str(p.parent),prefix='.'+p.name)
    with os.fdopen(fd,'w') as f: json.dump(v,f,ensure_ascii=False,indent=2,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
    os.replace(t,p)

def identity(r):
    k=str(r.get('kind') or ''); s=str(r.get('source_path') or ''); t=str(r.get('target_path') or '')
    c=str(r.get('callable') or r.get('target_callable') or ''); cfg=r.get('config_keys') if isinstance(r.get('config_keys'),list) else []
    if k=='DIRECT_STRATEGY_MODULE' and s.endswith('.py') and c: return s,c,'direct'
    if r.get('target_path_exists_in_git') is True and t.endswith('.py'): return t,c,'git_path'
    if c and s.endswith('.py') and (r.get('registry_like_path') is True or len(cfg)>=2): return s,c,'registry_or_shared'
    return None

def score(r, runtime, tests):
    n=0; why=[]; k=str(r.get('kind') or ''); s=str(r.get('source_path') or ''); t=str(r.get('target_path') or '')
    c=str(r.get('callable') or r.get('target_callable') or ''); cfg=r.get('config_keys') if isinstance(r.get('config_keys'),list) else []
    for ok,pts,label in ((k=='DIRECT_STRATEGY_MODULE',120,'direct'),(r.get('target_path_exists_in_git') is True and t.endswith('.py'),110,'git_path'),(r.get('registry_like_path') is True,20,'registry'),(bool(c),20,'callable'),(bool(r.get('source_blob_sha')),10,'blob'),(len(cfg)>=2,10,'config'),(bool(runtime),10,'runtime'),(bool(tests),10,'tests'),(any(x in k for x in ('FACTORY','REGISTRY')),10,'factory')):
        if ok: n+=pts; why.append(f'{label}:+{pts}')
    low=(t or s).lower()
    if low.startswith(('tests/','test/','docs/')) or '/tests/' in low: n-=100; why.append('nonprod:-100')
    if low.startswith('tools/') and not t: n-=35; why.append('tool:-35')
    if any(x in low for x in ('audit','smoke','display','bootstrap','readiness','probe')) and not t: n-=35; why.append('diagnostic:-35')
    return n,why

def plan_one(m,min_score,min_margin,maxn):
    runtime=[str(x) for x in m.get('runtime_owner_refs',[])]; tests=[str(x) for x in m.get('test_refs',[])]
    groups=defaultdict(list); rejected=0
    for r in m.get('evidence',[]):
        if not isinstance(r,dict): continue
        i=identity(r)
        if i is None: rejected+=1
        else: groups[i].append(r)
    cs=[]
    for i,rows in groups.items():
        b=max(rows,key=lambda r:score(r,runtime,tests)[0]); sc,why=score(b,runtime,tests)
        cs.append({'implementation_path':i[0],'callable':i[1],'binding_kind':i[2],'score':sc,'score_reasons':why,'evidence_occurrences':len(rows),'source_blob_sha':b.get('source_blob_sha')})
    cs.sort(key=lambda x:(x['score'],x['evidence_occurrences'],x['implementation_path']),reverse=True)
    top=cs[0] if cs else None; second=cs[1] if len(cs)>1 else None
    margin=(top['score']-(second['score'] if second else 0)) if top else 0
    auto=bool(top and top['score']>=min_score and margin>=min_margin)
    return {'strategy_id':m.get('strategy_id'),'prior_lineage_status':m.get('lineage_status'),'raw_evidence_count':m.get('evidence_count',0),'dedup_candidate_count':len(cs),'rejected_noncanonical_evidence_count':rejected,'top_score':top['score'] if top else None,'score_margin':margin,'resolution':'AUTO_NARROWED_PLAN' if auto else 'EXPLICIT_MAPPING_REQUIRED','proposed_canonical_mapping':top if auto else None,'top_candidates':cs[:maxn]}

def main():
    a=argparse.ArgumentParser(); a.add_argument('--root',default='/home/z/z'); a.add_argument('--contract',required=True); x=a.parse_args()
    root=Path(x.root); c=load(x.contract); prior=load(root/c['prior_a3d_status_path']); blockers=[]
    expected=int(c.get('expected_strategy_count',25)); maps=prior.get('mappings')
    if not(prior.get('state')=='PASS' and prior.get('blocker_count')==0 and prior.get('strategy_count')==expected and prior.get('false_implementation_ref_model_rejected') is True): blockers.append('PRIOR_A3D_INVALID')
    if not isinstance(maps,list) or len(maps)!=expected: blockers.append('A3D_MAPPING_COUNT_NOT_25'); maps=[]
    before={p:sha(p) for p in c.get('protected_paths',[])}
    plans=[plan_one(m,int(c.get('minimum_auto_select_score',90)),int(c.get('minimum_score_margin',20)),int(c.get('maximum_candidates_per_strategy',5))) for m in maps if isinstance(m,dict)]
    auto=sum(p['resolution']=='AUTO_NARROWED_PLAN' for p in plans); explicit=len(plans)-auto
    plan={'schema':'r7a3d2_strategy25_canonical_mapping_plan_v1','official_stage':'R7.A3D2','read_only':True,'strategy_count':len(plans),'auto_narrowed_plan_count':auto,'explicit_mapping_required_count':explicit,'mappings':plans}
    atomic(root/c['plan_path'],plan)
    after={p:sha(p) for p in c.get('protected_paths',[])}; changed=[p for p in before if before[p]!=after[p]]
    if changed: blockers.append('PROTECTED_PATH_CHANGED')
    state='PASS' if not blockers else 'HOLD'; nxt=c['next_stage_fail'] if blockers else (c['next_stage_explicit_required'] if explicit else c['next_stage_all_narrowed'])
    status={'official_stage':'R7.A3D2','state':state,'blocker_count':len(blockers),'blockers':blockers,'strategy_count':len(plans),'auto_narrowed_plan_count':auto,'explicit_mapping_required_count':explicit,'prior_conflict_lineage_count':prior.get('conflict_lineage_count'),'canonical_mapping_mutation_count':0,'protected_change_count':len(changed),'runtime_mutation_count':0,'performance_s_promoted_count':0,'plan_path':str(root/c['plan_path']),'next_stage':nxt}
    atomic(root/c['status_path'],status)
    for k in ('state','blocker_count','strategy_count','auto_narrowed_plan_count','explicit_mapping_required_count','canonical_mapping_mutation_count','protected_change_count','next_stage'): print(f'{k.upper()}={status[k]}')
    print('EXPLICIT_MAPPING_REQUIRED='+json.dumps([{'strategy_id':p['strategy_id'],'dedup_candidates':p['dedup_candidate_count'],'top_score':p['top_score'],'margin':p['score_margin']} for p in plans if p['resolution']=='EXPLICIT_MAPPING_REQUIRED'],ensure_ascii=False))
    print('PLAN_JSON='+status['plan_path']); print('RC='+str(0 if state=='PASS' else 2)); return 0 if state=='PASS' else 2
if __name__=='__main__': raise SystemExit(main())
