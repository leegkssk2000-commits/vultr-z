"""Read original approved packets; independently reconstruct known price pivots.
No strategy imports, entry/exit engine or alternative PnL."""
import json,gzip,hashlib,pathlib,argparse
q=argparse.ArgumentParser();q.add_argument('--inputs',required=True);args=q.parse_args()
B=pathlib.Path(__file__).resolve().parent;R=B.parents[2];INPUTS=pathlib.Path(args.inputs)
read=lambda p:json.loads(pathlib.Path(p).read_bytes())
gz=lambda p:json.loads(gzip.decompress(pathlib.Path(p).read_bytes()))
sha=lambda p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
canon=lambda x:json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
spec=read(B/'SPEC.json');proof={}
for per in ('DEV2025','SEEN2026'):
 pp=INPUTS/f'{per}.json.gz';assert sha(pp)==spec['input_packet_sha256'][per];packet=gz(pp)
 parent=gz(R/'research/development_evidence/KR3_C51_ENTRY_CONTEXT_AB_AFTER_PR1225_V1/B'/per/'RESULT.json.gz')
 piv={}
 for symbol,rows in packet['rows_by'].items():
  found=[]
  for j in range(2,len(rows)-2):
   peers=rows[j-2:j]+rows[j+1:j+3]
   for kind,field,cmp in [('LOW','low',lambda a,b:a<b),('HIGH','high',lambda a,b:a>b)]:
    if all(cmp(rows[j][field],k[field]) for k in peers):found.append(dict(kind=kind,index=j,price=rows[j][field],known_index=j+2,available_at=rows[j+2]['bar_close_ts']))
  piv[symbol]=found
 expected={m:[] for m in ('FIB','SHIFTED')}
 for e in parent['events']:
  symbol=e['symbol'];i=e['signal_index'];q=e['entry_context']['trend_index'];r=packet['rows_by'][symbol]
  a=None;depth=None;level=None;loindex=None;hiindex=None
  if q is not None:
   hs=[v for v in piv[symbol] if v['kind']=='HIGH' and v['known_index']<i and v['index']<=q]
   if hs:
    high=max(hs,key=lambda v:v['index']);ls=[v for v in piv[symbol] if v['kind']=='LOW' and v['known_index']<i and v['index']<high['index']]
    if ls:
     low=max(ls,key=lambda v:v['index'])
     if high['price']>low['price']:
      a=dict(low=low,high=high,known_at=max(low['available_at'],high['available_at']));level=min(x['low'] for x in r[q+1:i]);depth=(high['price']-level)/(high['price']-low['price']);loindex=q+1;hiindex=i-1
  for m,(lower,upper) in [('FIB',(.382,.618)),('SHIFTED',(.350,.586))]:
   allowed=depth is not None and lower<=depth<=upper
   obj=dict(mode=m,signal_index=i,available_at=e['signal_ts'],eligible=allowed,reason='NO_CONFIRMED_PRICE_ANCHOR' if a is None else None if allowed else 'PRICE_RETRACEMENT_ZONE_VETO',anchor=a,depth=depth,pullback_low=level,pullback_start=loindex,pullback_end=hiindex,volume_used=False,avwap_used=False)
   expected[m].append([symbol,i,obj])
 for m in expected:
  exp=sorted(expected[m],key=lambda z:(z[0],z[1]));actual=gz(B/m/per/'RESULT.json.gz');proj=sorted([[e['symbol'],e['signal_index'],e['entry_context']['price_context']] for e in actual['events']],key=lambda z:(z[0],z[1]))
  assert exp==proj,(per,m)
  proof[m+'/'+per]=dict(input_packet_sha256=sha(pp),source_projection_sha256=hashlib.sha256(canon(exp)).hexdigest(),raw_signals=len(exp),independent_price_reconstruction=True,new_economic_replay=0)
assert proof==read(B/'PRICE_SOURCE_PROOF.json'),'PRICE_SOURCE_PROOF_MISMATCH'
print(json.dumps(proof,indent=2))
