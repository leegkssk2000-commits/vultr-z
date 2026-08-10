#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json
from pathlib import Path
from typing import Any

EXPECTED = {('premium_index','BTC-USDT'),('premium_index','ETH-USDT'),('open_interest','BTC-USDT'),('open_interest','ETH-USDT')}


def stable_sha(v: Any) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--snapshot',type=Path,required=True); ap.add_argument('--history-dir',type=Path,required=True); ap.add_argument('--receipt',type=Path,required=True); ns=ap.parse_args()
    snap=load_json(ns.snapshot)
    if snap.get('state')!='PASS_P3_PROSPECTIVE_NATIVE_BASIS_OI_SNAPSHOT': raise RuntimeError('SNAPSHOT_STATE')
    recs=snap.get('records') or []
    keys={(r.get('feature'),r.get('symbol')) for r in recs}
    if keys!=EXPECTED or len(recs)!=4: raise RuntimeError(f'RECORD_PARITY:{sorted(keys)}')
    ns.history_dir.mkdir(parents=True,exist_ok=True)
    results=[]; total_added=0
    for r in recs:
        feature=str(r['feature']); symbol=str(r['symbol']); key=f'{feature}__{symbol.replace("-","")}'
        path=ns.history_dir/f'{key}.ndjson'
        prior=[]
        if path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                if line.strip(): prior.append(json.loads(line))
        seen={(int(x['source_timestamp_ms']),str(x['source_payload_sha256'])) for x in prior}
        ident=(int(r['source_timestamp_ms']),str(r['source_payload_sha256']))
        added=0
        if ident not in seen:
            prior.append(r); added=1; total_added+=1
        prior.sort(key=lambda x:(int(x['source_timestamp_ms']),int(x['collected_at_ms']),str(x['source_payload_sha256'])))
        identities=[(int(x['source_timestamp_ms']),str(x['source_payload_sha256'])) for x in prior]
        if len(identities)!=len(set(identities)): raise RuntimeError(f'DUP_IDENTITY:{key}')
        collected=[int(x['collected_at_ms']) for x in prior]
        if collected!=sorted(collected): raise RuntimeError(f'COLLECTED_TS_NONMONOTONIC:{key}')
        path.write_text(''.join(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n' for x in prior),encoding='utf-8')
        results.append({'feature':feature,'symbol':symbol,'history_file':str(path),'history_record_count':len(prior),'added_record_count':added,'latest_source_timestamp_ms':max(int(x['source_timestamp_ms']) for x in prior),'latest_collected_at_ms':max(int(x['collected_at_ms']) for x in prior)})
    receipt={'schema_version':'zel.p3.prospective_native_persistence.v1','state':'PASS_P3_PROSPECTIVE_NATIVE_APPEND','snapshot_receipt_sha256':snap['receipt_sha256'],'total_added_records':total_added,'results':results,'signal_generation_enabled':False,'replay_allowed':False,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold'}
    receipt['receipt_sha256']=stable_sha(receipt); ns.receipt.parent.mkdir(parents=True,exist_ok=True); ns.receipt.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n',encoding='utf-8'); print(json.dumps({'state':receipt['state'],'total_added_records':total_added,'receipt_sha256':receipt['receipt_sha256']},sort_keys=True)); return 0

if __name__=='__main__': raise SystemExit(main())
