"""Bind original minute artifacts by exact known derived245-day CSV hashes.
This does not certify a freshly reread complete raw HTTP inventory. It requires
byte-identical derived candle CSVs to the saved successful K run, so no changed
price is admitted. It avoids rereading unrelated raw response bodies.
"""
from pathlib import Path
import hashlib,json,re
import pandas as pd
from backend.research.rebuild import scalp7_source_data_v2 as source
START,END=1768262400000,1789430400000
EXPECTED={
 'BTC-USDT':'ec97e77c70e96eb480092d75a6e9291050b9ba491c27cd066ae0b9d3b7d4015d',
 'DOGE-USDT':'17da06e501c43e16802f7473655fe2511fea2c7fcb7ea534a9c6ac24a5fec26b',
 'ETH-USDT':'dcbf70620b28219e8382b8e14394cc495921a543ae46823adade05bcf1e487e2',
 'LINK-USDT':'5e1e52f8e8973c20aab1c2b9287843d2f2334f8c7444a1366d18094c095eb578',
 'SOL-USDT':'618a85896f739174b9a6535ef7a81478069d0640eab5c55e30beb51f2500becc',
 'XRP-USDT':'d6afbcb2b2537d1d0fe30373f61756854e8b4e03d3ebdf0459aea7d573f71641'}
def load_exact(root):
 root=Path(root);out={};inputs={}
 for symbol,pin in EXPECTED.items():
  paths=[]
  for segment in ('canonical_12m','canonical_postgap_20260213'):
   for p in sorted((root/segment/'1m'/symbol).glob('*.csv.gz')):
    match=re.fullmatch(r'(\d+)_(\d+)\.csv\.gz',p.name)
    if match is None:raise ValueError('UNEXPECTED_SOURCE_FILENAME')
    start,end=map(int,match.groups())
    if end>START and start<END:paths.append(p)
  paths.append(root/'canonical_gapday_prefix'/symbol/'1m.csv.gz')
  parts=[];receipts=[]
  for p in paths:
   frame=pd.read_csv(p,float_precision='round_trip')
   parts.append(frame[(frame.timestamp_ms>=START)&(frame.timestamp_ms<END)])
   receipts.append({'path':str(p.relative_to(root)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
  minutes=pd.concat(parts,ignore_index=True).sort_values('timestamp_ms').reset_index(drop=True)
  bars=source.aggregate_minutes(minutes,30)
  raw=bars.to_csv(index=False).encode();actual=hashlib.sha256(raw).hexdigest()
  if len(bars)!=11759 or actual!=pin:raise ValueError('GOLD_CANDLE_CSV_MISMATCH:'+symbol+':'+actual)
  bars.attrs.update(source_inventory_sha256='53c64616fa98ddd446533cbc7b8e90eb2866ce9b1b0b3243df4211d59f155ba2',
   inventory_role='REFERENCE_FROM_PREVIOUS_VERIFIED_RUN_NOT_A_NEW_FULL_RAW_INVENTORY_AUDIT',
   current_binding='COMPLETE245DAY_CSV_SHA256_PARITY_TO_SUCCESSFUL_CONTROL',symbol=symbol)
  out[symbol]=bars;inputs[symbol]=receipts
  bars.to_csv(Path(__file__).parent/('BOUND_'+symbol+'_30m.csv.gz'),index=False,compression={'method':'gzip','mtime':0})
  print('EXACT_DERIVED_CSV_BOUND',symbol,len(bars),actual,flush=True)
 with (Path(__file__).parent/'BOUND_INPUT_FILES.json').open('x') as f:json.dump(inputs,f,sort_keys=True,indent=2)
 return out
