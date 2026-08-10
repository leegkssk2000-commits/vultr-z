from __future__ import annotations

import argparse,csv,gzip,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

from edge_factory_v2_xsec_ls_funding2026_source import END,START,SYMBOLS,get,stable

STEP=8*60*60*1000
WINDOW=60*60*1000
EXPECTED_PER_SYMBOL=(END-START)//STEP


def fsha(p:Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda:f.read(1<<20),b''):
            h.update(c)
    return h.hexdigest()


def read_rows(path:Path)->dict[int,dict[str,Any]]:
    out={}
    with gzip.open(path,'rt',encoding='utf-8',newline='') as f:
        for r in csv.DictReader(f):
            t=int(r['fundingTime'])
            row={'fundingTime':t,'fundingRate':str(r['fundingRate'])}
            if t in out and out[t]!=row:
                raise RuntimeError(f'CONFLICTING_INPUT_DUPLICATE:{path.name}:{t}')
            out[t]=row
    return out


def write_rows(path:Path,rows:dict[int,dict[str,Any]])->None:
    with gzip.open(path,'wt',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=('fundingTime','fundingRate'))
        w.writeheader()
        for t in sorted(rows):
            w.writerow(rows[t])


def probe_symbol(symbol:str,source_path:Path,out_dir:Path)->dict[str,Any]:
    current=read_rows(source_path)
    source_row_count=len(current)
    expected=list(range(START,END,STEP))
    missing_before=[t for t in expected if t not in current]
    responses=[]
    recovered=[]
    for t in missing_before:
        rs=get(symbol,t-WINDOW,t+WINDOW+1)
        exact=[r for r in rs if int(r['fundingTime'])==t]
        if len(exact)>1:
            raise RuntimeError(f'EXACT_DUPLICATE:{symbol}:{t}:{len(exact)}')
        if exact:
            row=exact[0]
            prior=current.get(t)
            if prior is not None and prior!=row:
                raise RuntimeError(f'EXACT_CONFLICT:{symbol}:{t}')
            current[t]=row
            recovered.append(t)
        responses.append({'expected_funding_time_ms':t,'returned_row_count':len(rs),'exact_match_count':len(exact)})
    missing_after=[t for t in expected if t not in current]
    unexpected=[t for t in current if t<START or t>=END or (t-START)%STEP!=0]
    sorted_ts=sorted(current)
    duplicate_count=len(sorted_ts)-len(set(sorted_ts))
    strict=all(b>a for a,b in zip(sorted_ts,sorted_ts[1:]))
    maxgap=max((b-a for a,b in zip(sorted_ts,sorted_ts[1:])),default=0)/3600000 if sorted_ts else None
    ok=(not missing_after and not unexpected and duplicate_count==0 and strict and len(sorted_ts)==EXPECTED_PER_SYMBOL)
    out_path=out_dir/f"{symbol.replace('-','')}_funding2026_exact_repaired.csv.gz"
    write_rows(out_path,current)
    return {
        'symbol':symbol,
        'state':'PASS_EXACT_NATIVE_FUNDING_SCHEDULE' if ok else 'HOLD_EXACT_NATIVE_FUNDING_MISSING',
        'expected_schedule_rows':EXPECTED_PER_SYMBOL,
        'source_row_count':source_row_count,
        'missing_before_count':len(missing_before),
        'exact_probe_request_count':len(missing_before),
        'recovered_exact_count':len(recovered),
        'missing_after_count':len(missing_after),
        'missing_after_ms':missing_after,
        'unexpected_schedule_timestamp_count':len(unexpected),
        'duplicate_timestamp_count':duplicate_count,
        'strict_monotonic':strict,
        'maximum_interarrival_hours':maxgap,
        'probe_receipts':responses,
        'file':out_path.name,
        'file_sha256':fsha(out_path),
    }


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--source-dir',type=Path,required=True)
    ap.add_argument('--source-manifest',type=Path,required=True)
    ap.add_argument('--out-dir',type=Path,required=True)
    ap.add_argument('--manifest',type=Path,required=True)
    args=ap.parse_args()
    parent=json.loads(args.source_manifest.read_text(encoding='utf-8'))
    if parent.get('schema_version')!='zel.edge_factory_v2.xsec_ls_funding2026_source.v1':
        raise RuntimeError('PARENT_SCHEMA')
    parent_rows={r['symbol']:r for r in parent['results']}
    if set(parent_rows)!=set(SYMBOLS):
        raise RuntimeError('PARENT_SYMBOL_SET')
    args.out_dir.mkdir(parents=True,exist_ok=True)
    results=[]
    for symbol in SYMBOLS:
        source_path=args.source_dir/parent_rows[symbol]['file']
        if not source_path.exists():
            raise RuntimeError(f'PARENT_FILE_MISSING:{symbol}')
        if fsha(source_path)!=parent_rows[symbol]['file_sha256']:
            raise RuntimeError(f'PARENT_FILE_SHA:{symbol}')
        results.append(probe_symbol(symbol,source_path,args.out_dir))
    total_missing_before=sum(r['missing_before_count'] for r in results)
    total_recovered=sum(r['recovered_exact_count'] for r in results)
    total_missing_after=sum(r['missing_after_count'] for r in results)
    all20=all(r['state']=='PASS_EXACT_NATIVE_FUNDING_SCHEDULE' for r in results)
    manifest={
        'schema_version':'zel.edge_factory_v2.xsec_ls_funding2026_exact_probe.v1',
        'generated_at':datetime.now(timezone.utc).isoformat(),
        'state':'PASS_FUNDING2026_EXACT_PROBE_ALL20' if all20 else 'HOLD_FUNDING2026_EXACT_NATIVE_MISSING',
        'parent_receipt_sha256':parent.get('receipt_sha256'),
        'parent_funding_dataset_sha256':parent.get('funding_dataset_sha256'),
        'source_endpoint':'/openApi/swap/v2/quote/fundingRate',
        'schedule_interval_hours':8,
        'exact_probe_half_window_minutes':60,
        'expected_rows_per_symbol':EXPECTED_PER_SYMBOL,
        'total_missing_before':total_missing_before,
        'total_exact_probe_requests':total_missing_before,
        'total_recovered_exact':total_recovered,
        'total_missing_after':total_missing_after,
        'all20_pass':all20,
        'results':results,
        'economics_inspected':False,
        'candidate_entries_replayed':False,
        'signal_rule_changes':0,
        'ai_used':False,
        'selection_authority':False,
        'promotion_authority':False,
        'survivor_declared':False,
        'execution_authority':'NONE',
        'order_authority':'BLOCKED',
        'action':'hold',
        'next':'FINAL_REPRICE_UNCHANGED_1264_BATCHES' if all20 else 'HOLD_FINAL_SURVIVOR_SOURCE_GAP',
    }
    manifest['funding_dataset_sha256']=stable([{'symbol':r['symbol'],'file_sha256':r['file_sha256']} for r in results])
    manifest['receipt_sha256']=stable(manifest)
    args.manifest.parent.mkdir(parents=True,exist_ok=True)
    args.manifest.write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps({
        'state':manifest['state'],
        'total_missing_before':total_missing_before,
        'total_recovered_exact':total_recovered,
        'total_missing_after':total_missing_after,
        'all20_pass':all20,
        'funding_dataset_sha256':manifest['funding_dataset_sha256'],
        'receipt_sha256':manifest['receipt_sha256'],
        'failures':[{'symbol':r['symbol'],'missing_before':r['missing_before_count'],'recovered':r['recovered_exact_count'],'missing_after':r['missing_after_count']} for r in results if r['missing_before_count'] or r['missing_after_count']],
    },sort_keys=True))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
