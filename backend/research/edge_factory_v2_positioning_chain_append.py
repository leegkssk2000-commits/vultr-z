#!/usr/bin/env python3
from __future__ import annotations

import argparse,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

from edge_factory_v2_positioning_burst_collector import ENDPOINTS,SYMBOLS,get,record


def stable(v:Any)->str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def line_sha(records:list[dict[str,Any]])->str:
    h=hashlib.sha256()
    for r in records:
        h.update((json.dumps(r,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode())
    return h.hexdigest()


def load_parent(parent:Path)->tuple[list[dict[str,Any]],dict[str,Any],str]:
    chain=parent/'records.jsonl'
    manifest=parent/'chain_manifest.json'
    if chain.exists() and manifest.exists():
        records=[json.loads(x) for x in chain.read_text(encoding='utf-8').splitlines() if x.strip()]
        m=json.loads(manifest.read_text(encoding='utf-8'))
        if line_sha(records)!=m['records_sha256']:
            raise RuntimeError('PARENT_CHAIN_RECORDS_SHA')
        if len(records)!=m['total_record_count']:
            raise RuntimeError('PARENT_CHAIN_RECORD_COUNT')
        return records,m,'chain'
    snapshots=sorted(parent.glob('snapshot_*.json'))
    seed_manifest=parent/'manifest.json'
    if not snapshots or not seed_manifest.exists():
        raise RuntimeError('PARENT_FORMAT_UNKNOWN')
    sm=json.loads(seed_manifest.read_text(encoding='utf-8'))
    if sm.get('state')!='PASS_POSITIONING_BURST_SOURCE':
        raise RuntimeError('SEED_BURST_NOT_PASS')
    records=[]
    for p in snapshots:
        s=json.loads(p.read_text(encoding='utf-8'))
        records.extend(s['records'])
    if len(records)!=sm['record_count']:
        raise RuntimeError('SEED_RECORD_COUNT')
    pseudo={
        'schema_version':'zel.edge_factory_v2.positioning_chain_seed.v1',
        'state':'PASS_SEED_BURST_PARENT',
        'generation':0,
        'snapshot_count':sm['sample_count'],
        'total_record_count':len(records),
        'records_sha256':line_sha(records),
        'receipt_sha256':sm['receipt_sha256'],
    }
    return records,pseudo,'seed_burst'


def collect_one()->tuple[list[dict[str,Any]],int]:
    collected=int(datetime.now(timezone.utc).timestamp()*1000)
    rows=[]
    for feature in ('premium_index','open_interest'):
        for symbol in SYMBOLS:
            payload,base,lat=get(ENDPOINTS[feature],symbol)
            rows.append(record(feature,symbol,payload,base,lat,collected))
    keys={(r['feature'],r['symbol']) for r in rows}
    expected={(f,s) for f in ENDPOINTS for s in SYMBOLS}
    if keys!=expected:
        raise RuntimeError('NEW_SNAPSHOT_PARITY')
    return rows,collected


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--parent-dir',type=Path,required=True)
    ap.add_argument('--out-dir',type=Path,required=True)
    args=ap.parse_args()
    prior,parent_meta,parent_mode=load_parent(args.parent_dir)
    parent_count=len(prior)
    parent_sha=line_sha(prior)
    new_rows,collected=collect_one()
    old_keys={(r['feature'],r['symbol'],r['source_timestamp_ms'],r['collected_at_ms'],r['source_payload_sha256']) for r in prior}
    new_keys=[(r['feature'],r['symbol'],r['source_timestamp_ms'],r['collected_at_ms'],r['source_payload_sha256']) for r in new_rows]
    if len(set(new_keys))!=len(new_keys):
        raise RuntimeError('NEW_SNAPSHOT_DUPLICATE')
    if any(k in old_keys for k in new_keys):
        raise RuntimeError('APPEND_DUPLICATE_WITH_PARENT')
    records=prior+new_rows
    if line_sha(records[:parent_count])!=parent_sha:
        raise RuntimeError('PARENT_PREFIX_MUTATED')
    pairs={}
    for r in records:
        pairs.setdefault((r['feature'],r['symbol']),[]).append(r)
    pair_summary={}
    for (f,s),rs in sorted(pairs.items()):
        rs=sorted(rs,key=lambda x:x['collected_at_ms'])
        pair_summary[f'{f}:{s}']={
            'samples':len(rs),
            'distinct_collection_timestamps':len({r['collected_at_ms'] for r in rs}),
            'distinct_source_timestamps':len({r['source_timestamp_ms'] for r in rs}),
            'distinct_payload_hashes':len({r['source_payload_sha256'] for r in rs}),
            'source_timestamp_non_decreasing':all(b['source_timestamp_ms']>=a['source_timestamp_ms'] for a,b in zip(rs,rs[1:])),
            'collection_timestamp_strict':all(b['collected_at_ms']>a['collected_at_ms'] for a,b in zip(rs,rs[1:])),
        }
    expected_pairs={(f,s) for f in ENDPOINTS for s in SYMBOLS}
    if set(pairs)!=expected_pairs:
        raise RuntimeError('CHAIN_PAIR_PARITY')
    expected_samples=parent_count//len(expected_pairs)+1
    integrity=all(v['samples']==expected_samples and v['source_timestamp_non_decreasing'] and v['collection_timestamp_strict'] for v in pair_summary.values())
    args.out_dir.mkdir(parents=True,exist_ok=True)
    chain_path=args.out_dir/'records.jsonl'
    chain_path.write_text(''.join(json.dumps(r,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n' for r in records),encoding='utf-8')
    manifest={
        'schema_version':'zel.edge_factory_v2.positioning_chain.v1',
        'state':'PASS_POSITIONING_CHAIN_APPEND' if integrity else 'HOLD_POSITIONING_CHAIN_INTEGRITY',
        'generated_at':datetime.now(timezone.utc).isoformat(),
        'generation':int(parent_meta.get('generation',0))+1,
        'parent_mode':parent_mode,
        'parent_receipt_sha256':parent_meta['receipt_sha256'],
        'parent_records_sha256':parent_sha,
        'parent_record_count':parent_count,
        'appended_snapshot_collected_at_ms':collected,
        'new_record_count':len(new_rows),
        'snapshot_count':expected_samples,
        'total_record_count':len(records),
        'records_sha256':line_sha(records),
        'parent_prefix_preserved':line_sha(records[:parent_count])==parent_sha,
        'pair_summary':pair_summary,
        'symbols':list(SYMBOLS),
        'features':list(ENDPOINTS),
        'append_only':True,
        'economics_inspected':False,
        'derived_basis_emitted':False,
        'signal_generation_enabled':False,
        'replay_allowed':False,
        'AI_used':False,
        'selection_authority':False,
        'promotion_authority':False,
        'survivor_declared':False,
        'execution_authority':'NONE',
        'order_authority':'BLOCKED',
        'action':'hold',
        'next':'CONTINUE_HOURLY_APPEND' if integrity else 'SOURCE_HOLD',
    }
    manifest['receipt_sha256']=stable(manifest)
    (args.out_dir/'chain_manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({
        'state':manifest['state'],'generation':manifest['generation'],'parent_mode':parent_mode,
        'parent_record_count':parent_count,'new_record_count':len(new_rows),'total_record_count':len(records),
        'snapshot_count':manifest['snapshot_count'],'records_sha256':manifest['records_sha256'],'receipt_sha256':manifest['receipt_sha256']
    },sort_keys=True))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
