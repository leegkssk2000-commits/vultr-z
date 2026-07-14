#!/usr/bin/env python3
from __future__ import annotations
import argparse, ast, hashlib, json, math, os, re, shlex, statistics, subprocess
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

UTC=timezone.utc

def now(): return datetime.now(UTC).isoformat()
def sha(path:Path)->str:
 d=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): d.update(b)
 return d.hexdigest()
def atom(path:Path,obj:Any,jsonl=False):
 path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+'.tmp')
 if jsonl: tmp.write_text(''.join(json.dumps(x,ensure_ascii=False,sort_keys=True)+'\n' for x in obj),encoding='utf-8')
 else: tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
 tmp.replace(path)
def load(path:Path): return json.loads(path.read_text(encoding='utf-8'))
def jsonl(path:Path):
 rows=[]; errs=[]
 for n,line in enumerate(path.read_text(encoding='utf-8').splitlines(),1):
  if not line.strip(): continue
  try: x=json.loads(line)
  except Exception as e: errs.append({'line':n,'error':f'{type(e).__name__}:{e}'}); continue
  if isinstance(x,dict): rows.append(x)
  else: errs.append({'line':n,'error':'ROW_NOT_OBJECT'})
 return rows,errs
def walk(x):
 if isinstance(x,dict):
  yield x
  for v in x.values(): yield from walk(v)
 elif isinstance(x,list):
  for v in x: yield from walk(v)
def val(d:Mapping[str,Any],names:Sequence[str]):
 for k in names:
  x=d.get(k)
  if isinstance(x,str): x=x.strip() or None
  if x is not None: return x
 return None
def txt(x):
 if x is None:return None
 if isinstance(x,(dict,list)):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
 return str(x).strip() or None
def num(x):
 try:
  y=float(x); return y if math.isfinite(y) else None
 except Exception:return None
def rel(path:Path,root:Path):
 try:return path.resolve().relative_to(root.resolve()).as_posix()
 except Exception:return str(path)
def issue(code,sev,detail,source):return {'code':code,'severity':sev,'detail':detail,'source':source}

def source_inventory(root:Path,s:Mapping[str,Any]):
 toks=[str(x).lower() for x in s['discovery_tokens']]; suffix=set(s['source_suffixes']); excl=set(s['excluded_path_parts']); maxb=int(s['max_source_file_bytes']); out=[]
 roots=[root/str(x) for x in s['scan_roots'] if (root/str(x)).exists()] or [root/'backend']
 for base in roots:
  if not base.exists():continue
  for p in base.rglob('*'):
   if not p.is_file() or p.suffix.lower() not in suffix:continue
   rp=rel(p,root)
   if any(x in excl for x in Path(rp).parts):continue
   try:
    if p.stat().st_size>maxb:continue
    body=p.read_text(encoding='utf-8',errors='replace'); low=body.lower()
   except OSError:continue
   hit=sorted(t for t in toks if t in low or t in rp.lower())
   if not hit and not re.search(r'(trade|execution)[_-]?method|scalp|method[_-]?hint',rp,re.I):continue
   funcs=[]; classes=[]; imports=[]
   if p.suffix=='.py':
    try:
     tree=ast.parse(body)
     for n in ast.walk(tree):
      if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):funcs.append(n.name)
      elif isinstance(n,ast.ClassDef):classes.append(n.name)
      elif isinstance(n,ast.Import):imports += [a.name for a in n.names]
      elif isinstance(n,ast.ImportFrom) and n.module:imports.append(n.module)
    except SyntaxError:pass
   role='resolver' if 'resolver' in p.name.lower() or ('def resolve' in low and 'method' in low) else 'registry_or_mapping' if 'registry' in p.name.lower() or 'method_hint' in low else 'profile_or_policy' if 'profile' in p.name.lower() or 'scalp_first' in low or 'tactical_swing' in low else 'consumer_candidate'
   out.append({'path':rp,'sha256':sha(p),'size_bytes':p.stat().st_size,'role':role,'tokens':hit,'functions':sorted(set(funcs)),'classes':sorted(set(classes)),'imports':sorted(set(imports))})
 return sorted(out,key=lambda x:x['path'])

def mappings(root:Path,inv, s):
 sa=s['strategy_key_aliases']; ma=s['method_key_aliases']; ua=s['subtype_key_aliases']; out=[]; seen=set()
 def add(st,me,sub,src,ev):
  st,me,sub=txt(st),txt(me),txt(sub)
  if not st or not me or len(st)>160 or len(me)>120:return
  k=(st,me,sub,src['path'])
  if k in seen:return
  seen.add(k);out.append({'strategy_id':st,'declared_method':me,'declared_method_subtype':sub,'source_path':src['path'],'source_sha256':src['sha256'],'evidence':ev,'applied_proof':False})
 for src in inv:
  p=root/src['path']
  try: body=p.read_text(encoding='utf-8',errors='replace')
  except OSError:continue
  if p.suffix=='.json':
   try:data=json.loads(body)
   except Exception:data=None
   if data is not None:
    for o in walk(data):add(val(o,sa),val(o,ma),val(o,ua),src,'STRUCTURED_OBJECT')
    if isinstance(data,dict):
     for k,v in data.items():
      if isinstance(v,dict):add(k,val(v,ma),val(v,ua),src,'TOP_LEVEL_MAPPING')
 return sorted(out,key=lambda x:(x['strategy_id'],x['source_path'],x['declared_method']))

def manifest_ids(data,s):
 strong=[x for x in s['strategy_key_aliases'] if x in ('strategy_id','strategy','strategy_name','owner_strategy')]; weak=[x for x in s['strategy_key_aliases'] if x in ('name','id')]; ctx={'owner','sha256','path','strategy_file','strategy_path','method_hint','enabled'}; out=set()
 for o in walk(data):
  x=val(o,strong) or (val(o,weak) if any(k in o for k in ctx) else None)
  if isinstance(x,str) and re.fullmatch(r'[A-Za-z0-9_.:-]{2,160}',x):out.add(x)
 return out

def module_path(mod,root):
 parts=mod.split('.')
 for p in (root.joinpath(*parts).with_suffix('.py'),root.joinpath(*parts,'__init__.py'),root/'backend'/Path(*parts).with_suffix('.py'),root/'backend'/Path(*parts)/'__init__.py'):
  if p.is_file():return p.resolve()
 return None
def cmdpaths(cmd,root):
 out=[]; norm=cmd.replace('\\x20',' ')
 try:parts=shlex.split(norm)
 except Exception:parts=norm.split()
 for part in parts:
  raw=part.split('=',1)[-1].strip('{}[];,\"\'')
  p=Path(raw) if raw.startswith('/') else root/raw
  if p.is_file() and p.suffix in ('.py','.sh','.service'):out.append(p.resolve())
 for m in re.finditer(r'(/[^\s;{}\[\],]+\.(?:py|sh))',norm):
  p=Path(m.group(1));
  if p.is_file():out.append(p.resolve())
 return out
def graph(entries,root,limit=250):
 q=deque(entries); seen=set()
 while q and len(seen)<limit:
  p=q.popleft()
  if p in seen or not p.is_file():continue
  seen.add(p)
  if p.suffix!='.py':continue
  try:tree=ast.parse(p.read_text(encoding='utf-8',errors='replace'))
  except Exception:continue
  mods=[]
  for n in ast.walk(tree):
   if isinstance(n,ast.Import):mods += [a.name for a in n.names]
   elif isinstance(n,ast.ImportFrom) and n.module:mods.append(n.module)
  for m in mods:
   x=module_path(m,root)
   if x and x not in seen:q.append(x)
 return sorted(seen)
def resolver_audit(root,s,inv,override=None):
 unit=s['service_units']['producer']; props={}
 try:
  cp=subprocess.run(['systemctl','show',unit,'-p','MainPID','-p','ExecStart','-p','FragmentPath','-p','ActiveState','-p','SubState'],capture_output=True,text=True,timeout=10)
  props={'returncode':cp.returncode};props.update(dict(x.split('=',1) for x in cp.stdout.splitlines() if '=' in x))
 except Exception as e:props={'error':f'{type(e).__name__}:{e}'}
 pid=int(props.get('MainPID') or 0) if str(props.get('MainPID') or '0').isdigit() else 0; proc=''
 try:proc=Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace') if pid else ''
 except OSError:pass
 entries=[override.resolve()] if override else []
 entries += cmdpaths(str(props.get('ExecStart','')),root)+cmdpaths(proc,root)
 frag=Path(str(props.get('FragmentPath','')))
 if frag.is_file():entries.append(frag.resolve())
 g=graph(sorted(set(entries)),root); gs=set(g); res=[x for x in inv if x['role']=='resolver']; imp=[x['path'] for x in res if (root/x['path']).resolve() in gs]
 related=[x['path'] for x in inv if x['role'] in ('resolver','profile_or_policy','registry_or_mapping') and (root/x['path']).resolve() in gs]
 refs=[]
 for p in g:
  try:body=p.read_text(encoding='utf-8',errors='replace').lower()
  except OSError:continue
  if any(t.lower() in body for t in s['discovery_tokens']):refs.append(rel(p,root))
 state='PROVEN_RUNTIME_IMPORT' if imp else 'PROVEN_RUNTIME_RELATED_IMPORT_NO_RESOLVER_SYMBOL' if related and refs else 'STATIC_REFERENCE_IN_RUNTIME_GRAPH' if refs else 'RESOLVER_DISCOVERED_NOT_PROVEN_CONSUMED' if res else 'NO_RESOLVER_DISCOVERED'
 return {'schema':'q4r3_exact25_trade_method_resolver_audit_v1','generated_at':now(),'producer_unit':unit,'producer_service':props,'entrypoints':[rel(x,root) for x in sorted(set(entries))],'runtime_import_graph':[rel(x,root) for x in g],'runtime_imported_resolvers':imp,'runtime_imported_related_sources':related,'consumption_state':state,'applied_method_proven_by_static_audit':state=='PROVEN_RUNTIME_IMPORT','observer_only':True,'action':'hold'}

def records(root,out,s):
 base=root/s['runtime_scan_root']; files=[]; limit=int(s['runtime_scan_max_files']); age=float(s['runtime_scan_max_age_hours'])*3600; t=datetime.now(UTC).timestamp(); aliases=s['lineage_field_aliases']; outrows=[]; errs=[]
 if base.exists():
  for p in base.rglob('*.json'):
   try:
    st=p.stat()
    if out.resolve() in p.resolve().parents or t-st.st_mtime>age:continue
    files.append((st.st_mtime,p))
   except OSError:pass
 for _,p in sorted(files,reverse=True)[:limit]:
  try:data=load(p); h=sha(p)
  except Exception as e:errs.append(issue('RUNTIME_ARTIFACT_PARSE_ERROR','m',f'{rel(p,root)}:{type(e).__name__}:{e}','runtime'));continue
  for o in walk(data):
   r={k:val(o,v) for k,v in aliases.items()}
   if (r.get('method') or r.get('method_subtype')) and any(r.get(k) for k in ('event_id','position_id','signal_id','strategy_id')):outrows.append({**r,'source_path':rel(p,root),'source_sha256':h})
 return outrows,errs

def lineage(rows,runtime,maps,s):
 a=s['lineage_field_aliases']; ix={k:defaultdict(list) for k in ('event_id','position_id','signal_id')}; dm=defaultdict(list); issues=[]
 for r in runtime:
  for k in ix:
   if txt(r.get(k)):ix[k][txt(r[k])].append(r)
 for m in maps:dm[m['strategy_id']].append(m)
 out=[]
 for n,row in enumerate(rows,1):
  f={k:val(row,v) for k,v in a.items()}; st=txt(f.get('strategy_id')) or 'unknown'; sel=None; src='UNKNOWN'; proof=False
  if txt(f.get('method')):sel=f;src='FORMAL_ROW_DIRECT';proof=True
  else:
   for k in ('event_id','position_id','signal_id'):
    key=txt(f.get(k)); matches=ix[k].get(key,[]) if key else []
    methods={txt(x.get('method')) for x in matches if txt(x.get('method'))}
    if len(methods)>1:issues.append(issue('RUNTIME_IDENTIFIER_METHOD_CONFLICT','C',f'row={n}:{k}={key}:methods={sorted(methods)}','lineage'));matches=[]
    if matches:sel=matches[0];src='RUNTIME_EXACT_'+k.upper();proof=True;break
   if sel is None:
    cand=dm.get(st,[]); methods={txt(x.get('declared_method')) for x in cand if txt(x.get('declared_method'))}
    if len(methods)==1 and cand:sel={'method':cand[0]['declared_method'],'method_subtype':cand[0].get('declared_method_subtype'),'source_path':cand[0]['source_path'],'source_sha256':cand[0]['source_sha256']};src='STATIC_MAPPING_ONLY'
    elif len(methods)>1:src='STATIC_MAPPING_CONFLICT';issues.append(issue('STATIC_STRATEGY_METHOD_MAPPING_CONFLICT','M',f'strategy={st}:methods={sorted(methods)}','lineage'))
  sel=sel or {}
  out.append({'row_number':n,'event_id':txt(f.get('event_id')),'position_id':txt(f.get('position_id')),'signal_id':txt(f.get('signal_id')),'strategy_id':st,'symbol':txt(f.get('symbol')),'entry_ts':txt(f.get('entry_ts')),'method':txt(sel.get('method')),'method_subtype':txt(sel.get('method_subtype')),'profile_version':txt(sel.get('profile_version')),'profile_sha256':txt(sel.get('profile_sha256')),'entry_style':txt(sel.get('entry_style')),'hold_horizon':txt(sel.get('hold_horizon')),'risk_mode':txt(sel.get('risk_mode')),'target_r':num(sel.get('target_r')),'size_multiplier':num(sel.get('size_multiplier')),'execution_overlays':sel.get('execution_overlays'),'resolver_trace_id':txt(sel.get('resolver_trace_id')),'realized_r':num(f.get('realized_r')),'lineage_source':src,'lineage_source_path':txt(sel.get('source_path')),'lineage_source_sha256':txt(sel.get('source_sha256')),'applied_proof':proof,'decision_eligible':False,'action':'hold'})
 return out,issues

def matrix(rows,s):
 pre=int(s['coverage_thresholds']['preview_bucket_min']); fin=int(s['coverage_thresholds']['final_bucket_min']); b=defaultdict(list)
 for r in rows:b[(r['strategy_id'],r['method'] or 'unknown',r['method_subtype'] or 'unknown')].append(r)
 out=[]
 for (st,me,sub),rs in sorted(b.items()):
  vals=[r['realized_r'] for r in rs if r['applied_proof'] and r['realized_r'] is not None]; pos=sum(x for x in vals if x>0); neg=abs(sum(x for x in vals if x<0))
  out.append({'strategy_id':st,'method':me,'method_subtype':sub,'row_count':len(rs),'applied_proof_count':sum(bool(r['applied_proof']) for r in rs),'performance_sample_count':len(vals),'mean_realized_r':statistics.fmean(vals) if vals else None,'win_rate_pct':100*sum(x>0 for x in vals)/len(vals) if vals else None,'profit_factor':pos/neg if neg else None,'preview_eligible':len(vals)>=pre,'final_eligible':len(vals)>=fin,'decision_enabled':False,'action':'hold'})
 return {'schema':'q4r3_exact25_trade_method_strategy_matrix_v1','generated_at':now(),'preview_bucket_min':pre,'final_bucket_min':fin,'buckets':out,'comparison_decision_enabled':False,'promotion_enabled':False,'observer_only':True,'action':'hold'}

def run(args):
 root=args.root.resolve(); out=args.output_root.resolve(); s=load(args.ssot); rows,perr=jsonl(args.ledger); issues=[issue('FORMAL_LEDGER_PARSE_ERROR','C',f"line={e['line']}:{e['error']}",'ledger') for e in perr]
 try:man=load(args.manifest)
 except Exception as e:man={};issues.append(issue('MANIFEST_PARSE_ERROR','M',f'{type(e).__name__}:{e}','manifest'))
 inv=source_inventory(root,s); maps=mappings(root,inv,s); mids=manifest_ids(man,s); expected=int(s['expected_strategy_count'])
 if mids and len(mids)!=expected:issues.append(issue('MANIFEST_STRATEGY_COUNT_MISMATCH','M',f'expected={expected}:observed={len(mids)}','manifest'))
 if not inv:issues.append(issue('TRADE_METHOD_SOURCE_INVENTORY_EMPTY','M','no source discovered','inventory'))
 if not maps:issues.append(issue('STRATEGY_METHOD_MAPPING_EMPTY','M','no explicit mapping discovered','inventory'))
 audit=resolver_audit(root,s,inv,args.producer_entrypoint)
 if audit['consumption_state'] not in ('PROVEN_RUNTIME_IMPORT','PROVEN_RUNTIME_RELATED_IMPORT_NO_RESOLVER_SYMBOL'):issues.append(issue('TRADE_METHOD_RESOLVER_CONSUMPTION_UNPROVEN','M',audit['consumption_state'],'resolver'))
 rr,ri=records(root,out,s);issues+=ri; lin,li=lineage(rows,rr,maps,s);issues+=li; applied=sum(bool(x['applied_proof']) for x in lin); total=len(lin); pct=100*applied/total if total else 0.0
 if total and applied<total:issues.append(issue('APPLIED_TRADE_METHOD_LINEAGE_INCOMPLETE','M',f'applied={applied}:rows={total}:coverage_pct={pct:.6f}','lineage'))
 inventory={'schema':'q4r3_exact25_trade_method_surface_inventory_v1','generated_at':now(),'expected_strategy_count':expected,'manifest_strategy_count':len(mids),'source_count':len(inv),'sources':inv,'declared_mapping_count':len(maps),'declared_mappings':maps,'observer_only':True,'action':'hold'}
 coverage={'schema':'q4r3_exact25_trade_method_lineage_coverage_v1','generated_at':now(),'formal_ledger_row_count':total,'formal_ledger_sha256':sha(args.ledger),'runtime_method_record_count':len(rr),'direct_formal_lineage_count':sum(x['lineage_source']=='FORMAL_ROW_DIRECT' for x in lin),'runtime_exact_lineage_count':sum(str(x['lineage_source']).startswith('RUNTIME_EXACT_') for x in lin),'applied_proof_count':applied,'applied_proof_coverage_pct':pct,'static_mapping_only_count':sum(x['lineage_source']=='STATIC_MAPPING_ONLY' for x in lin),'unknown_method_count':sum(x['method'] is None for x in lin),'historical_backfill_performed':False,'formal_ledger_modified':False,'observer_only':True,'action':'hold'}
 rank={'m':1,'M':2,'C':3}; sev=max((x['severity'] for x in issues),key=lambda x:rank[x]) if issues else None; state='CLEAR' if not issues else 'HOLD'
 status={'schema':'q4r3_exact25_trade_method_lineage_observer_status_v1','generated_at':now(),'state':state,'verdict':'TRADE_METHOD_LINEAGE_OBSERVER_CLEAR' if state=='CLEAR' else 'TRADE_METHOD_LINEAGE_OBSERVER_ACTIVE_WITH_GAPS','inventory_source_count':len(inv),'declared_mapping_count':len(maps),'resolver_consumption_state':audit['consumption_state'],'formal_ledger_row_count':total,'applied_proof_count':applied,'applied_proof_coverage_pct':pct,'violation_count':len(issues),'violation_severity':sev,'observer_only':True,'strategy_mutation_allowed':False,'trade_method_mutation_allowed':False,'producer_mutation_allowed':False,'writer_mutation_allowed':False,'formal_ledger_mutation_allowed':False,'filter_enabled':False,'comparison_decision_enabled':False,'promotion_enabled':False,'paper_enabled':False,'live_enabled':False,'order_enabled':False,'order_authority':'blocked','execution_authority':'none','action':'hold'}
 violations={'schema':'q4r3_exact25_trade_method_lineage_violations_v1','generated_at':now(),'state':'CLEAR' if not issues else 'VIOLATION','count':len(issues),'severity':sev,'notify':bool(issues),'violations':issues,'action':'hold'}
 for p,o,jl in ((args.inventory,inventory,False),(args.resolver_audit,audit,False),(args.lineage,lin,True),(args.coverage,coverage,False),(args.matrix,matrix(lin,s),False),(args.violations,violations,False),(args.status,status,False)):atom(p,o,jl)
 print(json.dumps(status,ensure_ascii=False,sort_keys=True));return 0

def parser():
 p=argparse.ArgumentParser();
 for x in ('root','ledger','manifest','ssot','output_root','inventory','resolver_audit','lineage','coverage','matrix','violations','status'):p.add_argument('--'+x.replace('_','-'),dest=x,type=Path,required=True)
 p.add_argument('--producer-entrypoint',type=Path);return p
if __name__=='__main__':raise SystemExit(run(parser().parse_args()))
