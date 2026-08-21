#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
from pathlib import Path
from typing import Any, Mapping

STATIC = Path('backend/research/architecture_factory/a1_free_evidence_sweep_v1.json')
YOUTUBE = Path('backend/research/architecture_factory/a1_youtube_evidence_latest.json')
PREFERRED = 100_000
FALLBACK = 30_000


def read(path: Path) -> dict[str, Any]:
    value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict): raise RuntimeError(f'OBJECT_REQUIRED:{path}')
    return value


def key(row: Mapping[str, Any]) -> str:
    return str(row.get('identifier') or row.get('id') or '').strip().lower()


def normalize_youtube(row: Mapping[str, Any]) -> dict[str, Any]:
    views=int(row.get('view_count_snapshot') or 0)
    if views < FALLBACK or row.get('view_snapshot_verified') is not True or row.get('accepted_for_hypothesis_only') is not True:
        raise ValueError('YOUTUBE_NOT_VERIFIED_ACCEPTED')
    out=dict(row)
    out['tier']='youtube_verified_preferred' if views>=PREFERRED else 'youtube_verified_fallback'
    out['source_type']='YouTube'
    out['selection_authority']=False
    out['promotion_authority']=False
    return out


def sync(static: dict[str, Any], youtube: dict[str, Any]) -> dict[str, Any]:
    sources=[dict(x) for x in static.get('sources') or [] if isinstance(x,Mapping)]
    by={key(x):x for x in sources if key(x)}
    accepted=0
    for raw in youtube.get('sources') or []:
        if not isinstance(raw,Mapping): continue
        try: row=normalize_youtube(raw)
        except ValueError: continue
        by[key(row)]=row; accepted+=1
    merged=list(by.values())
    # Keep deterministic order: literature/community first, then YouTube by views desc.
    nonyt=[x for x in merged if str(x.get('source_type') or '').lower()!='youtube']
    yt=[x for x in merged if str(x.get('source_type') or '').lower()=='youtube']
    yt.sort(key=lambda x:(-int(x.get('view_count_snapshot') or 0),str(x.get('identifier') or '')))
    out=dict(static); out['sources']=nonyt+yt
    cov=dict(out.get('coverage') or {})
    cov['verified_youtube']=len(yt)
    cov['youtube_preferred_100k_plus']=sum(1 for x in yt if int(x.get('view_count_snapshot') or 0)>=PREFERRED)
    cov['youtube_fallback_30k_plus']=sum(1 for x in yt if FALLBACK<=int(x.get('view_count_snapshot') or 0)<PREFERRED)
    out['coverage']=cov
    policy=dict(out.get('policy') or {})
    policy['youtube_verified_items_accepted']=len(yt)
    policy['youtube_preferred_view_floor']=PREFERRED
    policy['youtube_fallback_view_floor']=FALLBACK
    out['policy']=policy
    out['last_youtube_sync_utc']=youtube.get('checked_at_utc')
    out['youtube_source_receipt_sha256']=youtube.get('receipt_sha256')
    out['state']='EVIDENCE_SWEEP_SYNCED'
    out['next_evidence_gap']='Preferred >=100K verified YouTube evidence is present; continue breadth only as hypothesis input while primary literature and local cost-adjusted replay remain authoritative.'
    axes=[dict(x) for x in out.get('priority_axis_map') or [] if isinstance(x,Mapping)]
    # Split funding from basis/OI: funding history is independently bound; basis/OI remain prospective-duration gated.
    axes=[x for x in axes if str(x.get('axis') or '') not in {'funding_dislocation_x_price_volume_regime','log_basis_x_price_volume_x_funding_oi'}]
    for x in axes:
        if str(x.get('axis') or '')=='log_basis_x_price_volume_x_funding':
            x['axis']='log_basis_x_price_volume_x_funding_oi'
            x['blocked_until_history_ready']=True
            x['blocker']='basis/open_interest prospective capture span below frozen 21-day gate; funding is independently historical-ready'
    if not any(str(x.get('axis') or '')=='funding_dislocation_x_price_volume_regime' for x in axes):
        axes.append({'rank':4,'axis':'funding_dislocation_x_price_volume_regime','evidence_ids':['F18','F3','F17'],'ready_sources':['funding','ohlcv','volume'],'source_readiness':'HISTORICAL_W1_W2_BOUND'})
    axes.sort(key=lambda x:(int(x.get('rank') or 999),str(x.get('axis') or '')))
    for i,x in enumerate(axes,1): x['rank']=i
    out['priority_axis_map']=axes
    return out


def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--static',type=Path,default=STATIC); ap.add_argument('--youtube',type=Path,default=YOUTUBE); ap.add_argument('--write',type=Path); a=ap.parse_args()
    result=sync(read(a.static),read(a.youtube)); target=a.write or a.static
    target.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    cov=result['coverage']
    print('A1_EXTERNAL_EVIDENCE_SYNC='+json.dumps({'verified_youtube':cov['verified_youtube'],'preferred_100k_plus':cov['youtube_preferred_100k_plus'],'fallback_30k_plus':cov['youtube_fallback_30k_plus'],'youtube_receipt':result.get('youtube_source_receipt_sha256')},sort_keys=True))
    return 0

if __name__=='__main__': raise SystemExit(main())
