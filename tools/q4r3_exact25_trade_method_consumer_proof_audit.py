#!/usr/bin/env python3
from __future__ import annotations
import argparse, ast, hashlib, json, math, os, re, shlex, subprocess
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

UTC=timezone.utc
def now(): return datetime.now(UTC).isoformat()
def rel(p,r):
    try:return p.resolve().relative_to(r.resolve()).as_posix()
    except Exception:return str(p)
def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""):h.update(b)
    return h.hexdigest()
def atom(p,x):
    p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+".tmp")
    t.write_text(json.dumps(x,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8");t.replace(p)
def load(p):return json.loads(p.read_text(encoding="utf-8"))
def walk(x):
    if isinstance(x,dict):
        yield x
        for v in x.values():yield from walk(v)
    elif isinstance(x,list):
        for v in x:yield from walk(v)
def val(d,keys):
    for k in keys:
        x=d.get(k)
        if isinstance(x,str):x=x.strip() or None
        if x is not None:return x
def txt(x):
    if x is None:return None
    return str(x).strip() or None
def problem(c,s,d,src):return {"code":c,"severity":s,"detail":d,"source":src}
def literal(n):
    if isinstance(n,ast.Constant):return n.value
    if isinstance(n,(ast.List,ast.Tuple,ast.Set)):return [literal(x) for x in n.elts]
    if isinstance(n,ast.Dict):
        out={}
        for k,v in zip(n.keys,n.values):
            if k is not None:
                kk=literal(k)
                if isinstance(kk,(str,int,float,bool)):out[str(kk)]=literal(v)
        return out
    return None
def module_paths(mod,current,root,level=0):
    out=[]
    if level:
        try:
            pkg=list(current.resolve().relative_to(root.resolve()).parent.parts)
            parts=pkg[:max(0,len(pkg)-level+1)]+(mod.split(".") if mod else [])
            if parts:out += [root.joinpath(*parts).with_suffix(".py"),root.joinpath(*parts,"__init__.py")]
        except Exception:pass
    elif mod:
        parts=mod.split(".")
        out += [root.joinpath(*parts).with_suffix(".py"),root.joinpath(*parts,"__init__.py"),
                root/"backend"/Path(*parts).with_suffix(".py"),root/"tools"/Path(*parts).with_suffix(".py")]
    return [p.resolve() for p in out if p.is_file()]
def sources(root,s):
    out=[];suf=set(s["source_suffixes"]);exc=set(s["excluded_path_parts"]);maxb=int(s["max_source_file_bytes"])
    for rr in s["scan_roots"]:
        b=root/rr
        if not b.exists():continue
        for p in b.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in suf:continue
            if any(x in exc for x in Path(rel(p,root)).parts):continue
            try:
                if p.stat().st_size<=maxb:out.append(p.resolve())
            except OSError:pass
    return sorted(set(out))
def shell_targets(p,root):
    try:b=p.read_text(encoding="utf-8",errors="replace")
    except OSError:return [],[]
    paths=[];mods=re.findall(r"(?:python3?|/[\w./-]*python)\s+-m\s+([A-Za-z_][\w.]*)",b)
    for m in re.finditer(r"(/[^\s'\";|&<>]+?\.(?:py|sh))|((?:\.{0,2}/)?(?:[\w.-]+/)+[\w.-]+\.(?:py|sh))",b):
        raw=m.group(1) or m.group(2);q=Path(raw) if raw.startswith("/") else p.parent/raw
        if not q.is_file():q=root/raw.lstrip("./")
        if q.is_file():paths.append(q.resolve())
    return sorted(set(paths)),sorted(set(mods))
def unit_meta(unit,root):
    props={}
    try:
        cp=subprocess.run(["systemctl","show",unit,"-p","MainPID","-p","ExecStart","-p","FragmentPath",
                           "-p","ActiveState","-p","SubState","-p","WorkingDirectory"],
                          capture_output=True,text=True,timeout=10)
        props={"returncode":cp.returncode};props.update(dict(x.split("=",1) for x in cp.stdout.splitlines() if "=" in x))
    except Exception as e:props={"error":f"{type(e).__name__}:{e}"}
    pid=int(props.get("MainPID") or 0) if str(props.get("MainPID") or "0").isdigit() else 0
    live={"pid":pid,"cmdline":None,"cwd":None,"exe":None,"pythonpath":None}
    if pid:
        try:live["cmdline"]=Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0",b" ").decode(errors="replace").strip()
        except OSError:pass
        try:live["cwd"]=os.readlink(f"/proc/{pid}/cwd")
        except OSError:pass
        try:live["exe"]=os.readlink(f"/proc/{pid}/exe")
        except OSError:pass
        try:
            for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
                if item.startswith(b"PYTHONPATH="):live["pythonpath"]=item.split(b"=",1)[1].decode(errors="replace")
        except OSError:pass
    props["live_process"]=live;entries=[];mods=[]
    for raw in (str(props.get("ExecStart") or ""),str(live.get("cmdline") or "")):
        norm=raw.replace("\\x20"," ")
        try:parts=shlex.split(norm)
        except Exception:parts=norm.split()
        for i,x in enumerate(parts):
            if x=="-m" and i+1<len(parts):mods.append(parts[i+1].strip("{}[];,\"'"))
            y=x.split("=",1)[-1].strip("{}[];,\"'");q=Path(y) if y.startswith("/") else root/y
            if q.is_file() and q.suffix in (".py",".sh"):entries.append(q.resolve())
    frag=Path(str(props.get("FragmentPath") or ""))
    if frag.is_file():
        entries.append(frag.resolve());pp,mm=shell_targets(frag,root);entries+=pp;mods+=mm
    return props,sorted(set(entries)),sorted(set(mods))
def py_edges(p,root):
    try:t=ast.parse(p.read_text(encoding="utf-8",errors="replace"))
    except Exception:return [],[]
    out=[];events=[]
    for n in ast.walk(t):
        if isinstance(n,ast.Import):
            for a in n.names:out+=module_paths(a.name,p,root);events.append({"kind":"import","module":a.name,"symbol":None,"line":n.lineno})
        elif isinstance(n,ast.ImportFrom):
            out+=module_paths(n.module or "",p,root,n.level)
            for a in n.names:events.append({"kind":"from","module":n.module or "","symbol":a.name,"line":n.lineno})
        elif isinstance(n,ast.Call):
            name=None
            if isinstance(n.func,ast.Name):name=n.func.id
            elif isinstance(n.func,ast.Attribute):
                z=[];q=n.func
                while isinstance(q,ast.Attribute):z.append(q.attr);q=q.value
                if isinstance(q,ast.Name):z.append(q.id)
                name=".".join(reversed(z))
            if name:events.append({"kind":"call","name":name,"line":n.lineno})
            if name in ("importlib.import_module","__import__","runpy.run_module") and n.args:
                m=literal(n.args[0])
                if isinstance(m,str):out+=module_paths(m,p,root);events.append({"kind":"dynamic","module":m,"line":n.lineno})
    return sorted(set(out)),events
def graph(root,entries,mods,limit):
    q=deque(entries)
    for m in mods:q.extend(module_paths(m,root/"__entry__.py",root))
    seen=set();events={}
    while q and len(seen)<limit:
        p=q.popleft().resolve()
        if p in seen or not p.is_file():continue
        seen.add(p)
        if p.suffix in (".sh",".service"):
            pp,mm=shell_targets(p,root);q.extend(pp)
            for m in mm:q.extend(module_paths(m,p,root))
        elif p.suffix==".py":
            pp,ev=py_edges(p,root);q.extend(pp);events[rel(p,root)]=ev
    return sorted(seen),events
def inventory(root,paths,s):
    toks=[x.lower() for x in s["discovery_tokens"]];out=[]
    for p in paths:
        try:b=p.read_text(encoding="utf-8",errors="replace")
        except OSError:continue
        low=b.lower();rp=rel(p,root);hits=sorted(x for x in toks if x in low or x in rp.lower())
        if not hits and not re.search(r"(trade|execution)[_-]?method|scalp|method[_-]?hint",rp,re.I):continue
        fun=[];cls=[];imp=[]
        if p.suffix==".py":
            try:
                t=ast.parse(b)
                for n in ast.walk(t):
                    if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):fun.append(n.name)
                    elif isinstance(n,ast.ClassDef):cls.append(n.name)
                    elif isinstance(n,ast.Import):imp += [a.name for a in n.names]
                    elif isinstance(n,ast.ImportFrom) and n.module:imp.append(n.module)
            except SyntaxError:pass
        syms=sorted({x for x in fun+cls if re.search(r"(resolve|select|choose|build|plan).*(method|trade)|(method|trade).*(resolve|select|plan)",x,re.I)})
        role="resolver" if syms or "resolver" in p.name.lower() else "registry_or_mapping" if "registry" in p.name.lower() or "method_hint" in low else "profile_or_policy" if any(x in low for x in s["known_method_families"]) else "consumer_candidate"
        try:mod=".".join((p.resolve().relative_to(root.resolve()).with_suffix("")).parts)
        except Exception:mod=None
        out.append({"path":rp,"module":mod,"sha256":sha(p),"role":role,"tokens":hits,
                    "functions":sorted(set(fun)),"classes":sorted(set(cls)),"imports":sorted(set(imp)),"resolver_symbols":syms})
    return sorted(out,key=lambda x:x["path"])
def proof(root,g,events,inv):
    relset={rel(p,root) for p in g};res=[x for x in inv if x["role"]=="resolver"];imports=[];calls=[];refs=[]
    syms=defaultdict(list)
    for c in res:
        for s in c["resolver_symbols"]:syms[s].append(c)
    for consumer,evs in events.items():
        for e in evs:
            mod=e.get("module");sym=e.get("symbol")
            for c in res:
                if c.get("module") and mod==c["module"]:imports.append({"consumer_path":consumer,"candidate_path":c["path"],"module":mod,"symbol":sym,"line":e.get("line")})
            if e.get("kind")=="call":
                leaf=str(e.get("name")).split(".")[-1]
                for c in syms.get(leaf,[]):calls.append({"consumer_path":consumer,"candidate_path":c["path"],"call":e["name"],"line":e.get("line")})
    for c in res:
        if c["path"] in relset:imports.append({"consumer_path":c["path"],"candidate_path":c["path"],"evidence":"MODULE_IN_RUNTIME_GRAPH"})
        needles=[c.get("module")]+c["resolver_symbols"]+[Path(c["path"]).stem]
        for p in g:
            rp=rel(p,root)
            if rp==c["path"] or p.suffix not in (".py",".sh",".service"):continue
            try:b=p.read_text(encoding="utf-8",errors="replace")
            except OSError:continue
            hit=sorted({x for x in needles if x and len(x)>3 and x in b})
            if hit:refs.append({"consumer_path":rp,"candidate_path":c["path"],"references":hit})
    uniq=lambda a:sorted({json.dumps(x,sort_keys=True):x for x in a}.values(),key=lambda x:json.dumps(x,sort_keys=True))
    imports,calls,refs=uniq(imports),uniq(calls),uniq(refs)
    state="PROVEN_DIRECT_RESOLVER_CALL" if calls else "PROVEN_RESOLVER_IMPORT_NO_CALL_BOUNDARY" if imports else "STATIC_REFERENCE_ONLY" if refs else "RESOLVER_DISCOVERED_NOT_REACHABLE_FROM_PRODUCER" if res else "NO_RESOLVER_CANDIDATE_DISCOVERED"
    return {"state":state,"resolver_candidate_count":len(res),"runtime_graph_count":len(g),
            "direct_import_evidence":imports,"direct_call_evidence":calls,"static_reference_evidence":refs,
            "applied_method_proven":state=="PROVEN_DIRECT_RESOLVER_CALL"}
def mappings(root,paths,s):
    sk=s["strategy_key_aliases"];mk=s["method_key_aliases"];uk=s["subtype_key_aliases"];out=[];seen=set();notes=[]
    def add(st,me,sub,p,ev,line=None):
        st,me,sub=txt(st),txt(me),txt(sub)
        if not st or not me or len(st)>160 or len(me)>120:return
        k=(st,me,sub,rel(p,root))
        if k in seen:return
        seen.add(k);out.append({"strategy_id":st,"declared_method":me,"declared_method_subtype":sub,
                                "source_path":rel(p,root),"source_sha256":sha(p),"evidence":ev,"line":line,"applied_proof":False})
    def inspect(x,p,ev):
        for o in walk(x):add(val(o,sk),val(o,mk),val(o,uk),p,ev)
        if isinstance(x,dict):
            for k,v in x.items():
                if isinstance(v,dict):add(k,val(v,mk),val(v,uk),p,ev+"_TOP")
    for p in paths:
        try:b=p.read_text(encoding="utf-8",errors="replace")
        except OSError:continue
        if p.suffix==".json":
            try:inspect(json.loads(b),p,"JSON")
            except Exception as e:notes.append({"path":rel(p,root),"error":f"{type(e).__name__}:{e}"})
        elif p.suffix==".py":
            try:t=ast.parse(b)
            except SyntaxError:continue
            for n in ast.walk(t):
                if isinstance(n,(ast.Assign,ast.AnnAssign)) and n.value is not None:
                    x=literal(n.value)
                    if isinstance(x,(dict,list)):inspect(x,p,"PYTHON_LITERAL")
                elif isinstance(n,ast.Call):
                    kw={k.arg:literal(k.value) for k in n.keywords if k.arg}
                    add(val(kw,sk),val(kw,mk),val(kw,uk),p,"PYTHON_CALL",getattr(n,"lineno",None))
        elif p.suffix in (".yaml",".yml",".toml"):
            st=me=sub=None;line0=None
            for n,line in enumerate(b.splitlines(),1):
                m=re.match(r"\s*([A-Za-z_][\w.-]*)\s*[:=]\s*[\"']?([^\"'\s,]+)",line.split("#",1)[0])
                if not m:continue
                k,v=m.groups()
                if k in sk:
                    if st and me:add(st,me,sub,p,"TEXT_BLOCK",line0)
                    st,me,sub,line0=v,None,None,n
                elif k in mk:me=v
                elif k in uk:sub=v
            if st and me:add(st,me,sub,p,"TEXT_BLOCK",line0)
    return sorted(out,key=lambda x:(x["strategy_id"],x["source_path"],x["declared_method"])),notes
def manifest_ids(data,s):
    out=set();aliases=s["strategy_key_aliases"]
    for o in walk(data):
        x=val(o,[k for k in aliases if k not in ("name","id")])
        if not x and any(k in o for k in ("owner","sha256","path","strategy_file","method_hint","enabled")):x=val(o,[k for k in aliases if k in ("name","id")])
        x=txt(x)
        if x and re.fullmatch(r"[A-Za-z0-9_.:-]{2,160}",x):out.add(x)
    return sorted(out)
def formal(p):
    rows=[];errs=[]
    for n,line in enumerate(p.read_text(encoding="utf-8").splitlines(),1):
        if not line.strip():continue
        try:x=json.loads(line)
        except Exception as e:errs.append(problem("FORMAL_LEDGER_PARSE_ERROR","C",f"line={n}:{type(e).__name__}:{e}","formal"));continue
        if isinstance(x,dict):rows.append(x)
        else:errs.append(problem("FORMAL_LEDGER_ROW_NOT_OBJECT","C",f"line={n}","formal"))
    return rows,errs
def runtime_records(root,s,outroot):
    base=root/s["runtime_scan_root"];files=[];rows=[];errs=[];cut=datetime.now(UTC).timestamp()-float(s["runtime_scan_max_age_hours"])*3600
    if not base.exists():return rows,errs
    for pat in ("*.json","*.jsonl"):
        for p in base.rglob(pat):
            try:
                if outroot.resolve() in p.resolve().parents or p.stat().st_mtime<cut:continue
                files.append((p.stat().st_mtime,p))
            except OSError:pass
    a=s["lineage_field_aliases"]
    for _,p in sorted(files,reverse=True)[:int(s["runtime_scan_max_files"])]:
        try:
            data=[json.loads(x) for x in p.read_text(encoding="utf-8",errors="replace").splitlines() if x.strip()] if p.suffix==".jsonl" else load(p);h=sha(p)
        except Exception as e:errs.append(problem("RUNTIME_ARTIFACT_PARSE_ERROR","m",f"{rel(p,root)}:{type(e).__name__}:{e}","runtime"));continue
        for o in walk(data):
            r={k:val(o,v) for k,v in a.items()}
            if (r.get("method") or r.get("method_subtype")) and any(r.get(k) for k in ("event_id","position_id","signal_id","strategy_id")):
                rows.append({**{k:txt(v) for k,v in r.items()},"source_path":rel(p,root),"source_sha256":h})
    return sorted({json.dumps(x,sort_keys=True):x for x in rows}.values(),key=lambda x:json.dumps(x,sort_keys=True)),errs
def linkage(rows,arts,s):
    a=s["lineage_field_aliases"];ix={k:defaultdict(list) for k in ("event_id","position_id","signal_id")}
    for x in arts:
        for k in ix:
            if txt(x.get(k)):ix[k][txt(x[k])].append(x)
    linked=0;conf=[];methods=defaultdict(int);paths=set()
    for n,row in enumerate(rows,1):
        found=[]
        for k in ix:
            key=txt(val(row,a[k]))
            if key:found+=ix[k].get(key,[])
        ms=sorted({txt(x.get("method")) for x in found if txt(x.get("method"))})
        if len(ms)==1:
            linked+=1;methods[ms[0]]+=1;paths.update(x["source_path"] for x in found if x.get("source_path"))
        elif len(ms)>1:conf.append({"row":n,"methods":ms})
    return {"formal_ledger_row_count":len(rows),"method_artifact_record_count":len(arts),
            "exact_identifier_linked_count":linked,"exact_identifier_linked_pct":round(linked*100/len(rows),6) if rows else 0.0,
            "linked_methods":dict(sorted(methods.items())),"linked_source_paths":sorted(paths),"conflicts":conf}
def run(a):
    root=a.root.resolve();s=load(a.ssot);man=load(a.manifest);rows,errs=formal(a.ledger);paths=sources(root,s)
    meta,entries,mods=unit_meta(s["service_units"]["producer"],root);g,events=graph(root,entries,mods,int(s["runtime_graph_max_files"]))
    inv=inventory(root,paths,s);pr=proof(root,g,events,inv);maps,notes=mappings(root,paths,s);strategies=manifest_ids(man,s)
    arts,rerrs=runtime_records(root,s,a.output_root);link=linkage(rows,arts,s);issues=errs+rerrs
    active=meta.get("ActiveState");sub=meta.get("SubState")
    if active!="active" or sub!="running":issues.append(problem("PRODUCER_NOT_RUNNING","C",f"active={active}:sub={sub}","producer"))
    if link["conflicts"]:issues.append(problem("RUNTIME_IDENTIFIER_METHOD_CONFLICT","C",f"count={len(link['conflicts'])}","runtime"))
    sets=defaultdict(set)
    for x in maps:sets[x["strategy_id"]].add(x["declared_method"])
    conflicts={k:sorted(v) for k,v in sets.items() if len(v)>1}
    if conflicts:issues.append(problem("STATIC_STRATEGY_METHOD_MAPPING_CONFLICT","M",json.dumps(conflicts,sort_keys=True),"mapping"))
    mapped=set(sets);missing=sorted(set(strategies)-mapped)
    if missing:issues.append(problem("DECLARED_MAPPING_COVERAGE_GAP","M",f"missing={len(missing)}/{len(strategies)}","mapping"))
    if pr["state"]=="PROVEN_DIRECT_RESOLVER_CALL":nxt="BIND_EXISTING_METHOD_DECISION_OUTPUT_TO_EVENT_LINEAGE_SIDECAR"
    elif pr["state"]=="PROVEN_RESOLVER_IMPORT_NO_CALL_BOUNDARY":nxt="TRACE_RESOLVER_CALL_BOUNDARY_READONLY"
    elif link["exact_identifier_linked_count"]>0:nxt="USE_EXISTING_RUNTIME_METHOD_ARTIFACT_AS_APPLIED_LINEAGE_SOURCE"
    else:nxt="CONFIRM_METHOD_LAYER_DORMANT_OR_SEPARATE_FROM_EXACT25_PRODUCER"
    audit={"schema":"q4r3_exact25_trade_method_consumer_audit_v1","generated_at":now(),"producer":meta,
           "entrypoints":[rel(x,root) for x in entries],"runtime_graph":[rel(x,root) for x in g],
           "candidate_source_count":len(inv),"candidates":inv,"consumer_proof":pr,"runtime_linkage":link,"next_action":nxt,"observer_only":True,"action":"hold"}
    mapping={"schema":"q4r3_exact25_trade_method_mapping_inventory_v2","generated_at":now(),"manifest_strategy_count":len(strategies),
             "manifest_strategies":strategies,"mapping_count":len(maps),"mapped_strategy_count":len(mapped&set(strategies)),
             "missing_strategy_count":len(missing),"missing_strategies":missing,"conflicts":conflicts,"mappings":maps,"parse_notes":notes,
             "declaration_is_not_applied_proof":True,"observer_only":True,"action":"hold"}
    rank={None:0,"m":1,"M":2,"C":3};sev=max((x["severity"] for x in issues),key=lambda x:rank[x],default=None)
    state="VIOLATION" if issues else "CLEAR" if pr["applied_method_proven"] or link["exact_identifier_linked_count"]>0 else "HOLD"
    verdict="TRADE_METHOD_CONSUMPTION_AND_RUNTIME_LINEAGE_PROVEN" if state=="CLEAR" else "TRADE_METHOD_CONSUMER_PROOF_WITH_VIOLATIONS" if state=="VIOLATION" else "TRADE_METHOD_LAYER_NOT_PROVEN_CONSUMED_BY_EXACT25"
    status={"schema":"q4r3_exact25_trade_method_consumer_proof_status_v1","generated_at":now(),"state":state,"verdict":verdict,"next_action":nxt,
            "producer_active":active=="active" and sub=="running","formal_ledger_row_count":len(rows),"manifest_strategy_count":len(strategies),
            "mapped_strategy_count":mapping["mapped_strategy_count"],"resolver_candidate_count":pr["resolver_candidate_count"],
            "consumer_proof_state":pr["state"],"runtime_exact_linked_count":link["exact_identifier_linked_count"],
            "runtime_exact_linked_pct":link["exact_identifier_linked_pct"],"violation_count":len(issues),"violation_severity":sev,
            "strategy_mutation_allowed":False,"trade_method_mutation_allowed":False,"producer_mutation_allowed":False,
            "writer_mutation_allowed":False,"formal_ledger_mutation_allowed":False,"historical_backfill_allowed":False,
            "filter_enabled":False,"comparison_decision_enabled":False,"promotion_enabled":False,"paper_enabled":False,
            "live_enabled":False,"order_enabled":False,"order_authority":"blocked","execution_authority":"none","observer_only":True,"action":"hold"}
    vio={"schema":"q4r3_exact25_trade_method_consumer_proof_violations_v1","generated_at":now(),
         "state":"CLEAR" if not issues else "VIOLATION","count":len(issues),"severity":sev,"notify":sev=="C","violations":issues,"action":"hold"}
    atom(a.consumer_audit,audit);atom(a.mapping_inventory,mapping);atom(a.runtime_linkage,link);atom(a.violations,vio);atom(a.status,status)
    print(json.dumps(status,ensure_ascii=False,sort_keys=True));return 0
def parser():
    p=argparse.ArgumentParser()
    for x in ("root","ledger","manifest","ssot","output_root","consumer_audit","mapping_inventory","runtime_linkage","violations","status"):p.add_argument("--"+x.replace("_","-"),dest=x,type=Path,required=True)
    return p
if __name__=="__main__":raise SystemExit(run(parser().parse_args()))
