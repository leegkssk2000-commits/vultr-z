from __future__ import annotations

import argparse, csv, gzip, hashlib, json, time
import urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

VERSION='ZEL_EDGE_FACTORY_V2_FRESH_18M_1H_COLLECT_V1'
SCHEMA='zel.edge_factory_v2.fresh_18m_1h_collect.v1'
BASE_URL='https://open-api.bingx.com'
ENDPOINT='/openApi/swap/v3/quote/klines'
INTERVAL='1h'
INTERVAL_MS=3_600_000
CHUNK_LIMIT=1000
SAFE_CHUNK_BARS=999
SYMBOLS=('BTC-USDT','ETH-USDT','LINK-USDT','SOL-USDT','XRP-USDT')
START_UTC='2024-07-01T00:00:00+00:00'
END_EXCLUSIVE_UTC='2026-01-01T00:00:00+00:00'
CSV_FIELDS=('timestamp_ms','open','high','low','close','volume')
PARTITIONS={
 'D1_DISCOVERY':('2024-07-01T00:00:00+00:00','2025-01-01T00:00:00+00:00'),
 'V1_VALIDATION':('2025-01-01T00:00:00+00:00','2025-07-01T00:00:00+00:00'),
 'T1_TEST':('2025-07-01T00:00:00+00:00','2026-01-01T00:00:00+00:00'),
}

def stable_sha(v:Any)->str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def file_sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''): h.update(chunk)
    return h.hexdigest()

def utc_ms(v:str)->int:
    d=datetime.fromisoformat(v.replace('Z','+00:00'))
    if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
    return int(d.timestamp()*1000)

def decimal_text(value:Any,field:str)->str:
    try: n=Decimal(str(value))
    except (InvalidOperation,ValueError) as exc: raise RuntimeError(f'INVALID_DECIMAL:{field}:{value}') from exc
    if not n.is_finite(): raise RuntimeError(f'NONFINITE_DECIMAL:{field}:{value}')
    if field!='volume' and n<=0: raise RuntimeError(f'NONPOSITIVE_PRICE:{field}:{value}')
    if field=='volume' and n<0: raise RuntimeError(f'NEGATIVE_VOLUME:{value}')
    return format(n,'f')

def extract_rows(payload:Mapping[str,Any])->list[Any]:
    if int(payload.get('code',-1))!=0: raise RuntimeError(f"BINGX_CODE:{payload.get('code')}:{payload.get('msg')}")
    data=payload.get('data')
    if isinstance(data,list): return data
    if isinstance(data,Mapping):
        for key in ('data','rows','items','list','klines'):
            child=data.get(key)
            if isinstance(child,list): return child
    raise RuntimeError('BINGX_KLINE_ROWS_MISSING')

def normalize_row(raw:Any)->dict[str,Any]:
    if isinstance(raw,Mapping):
        ts=raw.get('openTime',raw.get('time',raw.get('timestamp')))
        vals={'timestamp_ms':ts,'open':raw.get('open'),'high':raw.get('high'),'low':raw.get('low'),'close':raw.get('close'),'volume':raw.get('volume',raw.get('vol',0))}
    elif isinstance(raw,Sequence) and not isinstance(raw,(str,bytes)) and len(raw)>=6:
        vals={'timestamp_ms':raw[0],'open':raw[1],'high':raw[2],'low':raw[3],'close':raw[4],'volume':raw[5]}
    else: raise RuntimeError(f'UNSUPPORTED_KLINE_ROW:{type(raw).__name__}')
    try: ts=int(float(vals['timestamp_ms']))
    except (TypeError,ValueError) as exc: raise RuntimeError(f"INVALID_TIMESTAMP:{vals.get('timestamp_ms')}") from exc
    row={'timestamp_ms':ts,'open':decimal_text(vals['open'],'open'),'high':decimal_text(vals['high'],'high'),'low':decimal_text(vals['low'],'low'),'close':decimal_text(vals['close'],'close'),'volume':decimal_text(vals['volume'],'volume')}
    o,h,l,c=Decimal(row['open']),Decimal(row['high']),Decimal(row['low']),Decimal(row['close'])
    if h<max(o,c,l): raise RuntimeError(f'OHLC_HIGH_INVALID:{ts}')
    if l>min(o,c,h): raise RuntimeError(f'OHLC_LOW_INVALID:{ts}')
    return row

def request_chunk(symbol:str,start_ms:int,end_ms:int,attempts:int=5)->list[dict[str,Any]]:
    params={'symbol':symbol,'interval':INTERVAL,'startTime':start_ms,'endTime':end_ms,'limit':CHUNK_LIMIT}
    req=urllib.request.Request(f"{BASE_URL}{ENDPOINT}?{urllib.parse.urlencode(params)}",headers={'Accept':'application/json','User-Agent':VERSION,'X-SOURCE-KEY':'BX-AI-SKILL'})
    last=None
    for attempt in range(1,attempts+1):
        try:
            with urllib.request.urlopen(req,timeout=30) as response: payload=json.loads(response.read())
            return sorted((normalize_row(r) for r in extract_rows(payload)),key=lambda x:int(x['timestamp_ms']))
        except (urllib.error.URLError,urllib.error.HTTPError,TimeoutError,json.JSONDecodeError,RuntimeError) as exc:
            last=f'{type(exc).__name__}:{exc}'
            if attempt==attempts: break
            time.sleep(min(2**attempt,20))
    raise RuntimeError(f'BINGX_REQUEST_FAILED:{symbol}:{start_ms}:{end_ms}:{last}')

def expected_timestamps(start_ms:int,end_ms:int)->Iterable[int]: return range(start_ms,end_ms,INTERVAL_MS)

def collect_symbol(symbol:str,out_dir:Path,start_ms:int,end_ms:int)->dict[str,Any]:
    rows_by_ts={}; requests=0; cursor=start_ms
    while cursor<end_ms:
        chunk_end=min(cursor+SAFE_CHUNK_BARS*INTERVAL_MS,end_ms)
        rows=request_chunk(symbol,cursor,chunk_end); requests+=1
        for row in rows:
            ts=int(row['timestamp_ms'])
            if cursor<=ts<chunk_end:
                prior=rows_by_ts.get(ts)
                if prior is not None and prior!=row: raise RuntimeError(f'CONFLICTING_DUPLICATE:{symbol}:{ts}')
                rows_by_ts[ts]=row
        cursor=chunk_end
        time.sleep(0.08)
    expected=list(expected_timestamps(start_ms,end_ms))
    missing=[ts for ts in expected if ts not in rows_by_ts]
    unexpected=sorted(ts for ts in rows_by_ts if ts<start_ms or ts>=end_ms)
    if missing or unexpected: raise RuntimeError(f'COVERAGE_FAIL:{symbol}:missing={len(missing)}:unexpected={len(unexpected)}:first_missing={missing[:10]}')
    ordered=[rows_by_ts[ts] for ts in expected]
    output=out_dir/f"{symbol.replace('-','')}_1h_{start_ms}_{end_ms}.csv.gz"
    with gzip.open(output,'wt',encoding='utf-8',newline='') as handle:
        w=csv.DictWriter(handle,fieldnames=CSV_FIELDS); w.writeheader(); w.writerows(ordered)
    partition_counts={}
    for name,(a,b) in PARTITIONS.items():
        am,bm=utc_ms(a),utc_ms(b)
        partition_counts[name]=sum(am<=int(r['timestamp_ms'])<bm for r in ordered)
    return {'symbol':symbol,'interval':INTERVAL,'start_ms':start_ms,'end_exclusive_ms':end_ms,'expected_row_count':len(expected),'row_count':len(ordered),'request_count':requests,'duplicate_timestamp_count':0,'missing_interval_count':0,'unexpected_timestamp_count':0,'first_timestamp_ms':int(ordered[0]['timestamp_ms']),'last_timestamp_ms':int(ordered[-1]['timestamp_ms']),'partition_row_counts':partition_counts,'file':output.name,'file_bytes':output.stat().st_size,'file_sha256':file_sha(output)}

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--out-dir',type=Path,required=True); ap.add_argument('--manifest',type=Path,required=True); ap.add_argument('--self-test',action='store_true'); a=ap.parse_args()
    if a.self_test:
        r=normalize_row([1_700_000_000_000,'10','12','9','11','3']); assert r['high']=='12'; assert len(list(expected_timestamps(0,3*INTERVAL_MS)))==3; assert SAFE_CHUNK_BARS==999; print('PASS'); return 0
    start,end=utc_ms(START_UTC),utc_ms(END_EXCLUSIVE_UTC)
    expected_per=(end-start)//INTERVAL_MS
    if expected_per!=13176: raise RuntimeError(f'EXPECTED_ROW_CONTRACT:{expected_per}')
    a.out_dir.mkdir(parents=True,exist_ok=True)
    results=[collect_symbol(s,a.out_dir,start,end) for s in SYMBOLS]
    expected_parts={'D1_DISCOVERY':4416,'V1_VALIDATION':4344,'T1_TEST':4416}
    for row in results:
        if row['partition_row_counts']!=expected_parts: raise RuntimeError(f"PARTITION_COUNTS:{row['symbol']}:{row['partition_row_counts']}")
    manifest={'schema_version':SCHEMA,'version':VERSION,'generated_at':datetime.now(timezone.utc).isoformat(),'state':'PASS_FRESH_18M_1H_DATA_STAGED','source':{'base_url':BASE_URL,'endpoint':ENDPOINT,'auth_required':False,'interval':INTERVAL,'chunk_limit':CHUNK_LIMIT,'safe_chunk_bars':SAFE_CHUNK_BARS},'frozen_boundaries':{'start_utc':START_UTC,'end_exclusive_utc':END_EXCLUSIVE_UTC,'start_ms':start,'end_exclusive_ms':end},'partitions':{k:{'start_ms':utc_ms(v[0]),'end_exclusive_ms':utc_ms(v[1]),'rows_per_symbol':expected_parts[k]} for k,v in PARTITIONS.items()},'symbols':list(SYMBOLS),'expected_rows_per_symbol':expected_per,'expected_total_rows':expected_per*len(SYMBOLS),'actual_total_rows':sum(int(r['row_count']) for r in results),'results':results,'economics_inspected':False,'holdout_metrics_inspected':False,'strategy_rules_mutated':False,'ai_used':False,'canonical_mutated':False,'registry_mutated':False,'runtime_mutated':False,'formal_ledger_mutated':False,'shadow_mutated':False,'paper_mutated':False,'live_mutated':False,'protected_mutations':0,'selection_authority':False,'promotion_authority':False,'survivor_declared':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold','next':'FREEZE_D1_ECONOMIC_PRIMITIVES_BEFORE_ANY_D1_SCORE'}
    if manifest['actual_total_rows']!=manifest['expected_total_rows']: raise RuntimeError('TOTAL_ROW_COUNT_MISMATCH')
    manifest['dataset_sha256']=stable_sha([{'symbol':r['symbol'],'file_sha256':r['file_sha256']} for r in results])
    manifest['receipt_sha256']=stable_sha(manifest)
    a.manifest.parent.mkdir(parents=True,exist_ok=True); a.manifest.write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'state':manifest['state'],'actual_total_rows':manifest['actual_total_rows'],'dataset_sha256':manifest['dataset_sha256'],'receipt_sha256':manifest['receipt_sha256']},sort_keys=True)); return 0

if __name__=='__main__': raise SystemExit(main())
