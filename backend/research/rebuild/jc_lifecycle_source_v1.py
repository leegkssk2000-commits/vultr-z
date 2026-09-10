"""One bounded pre-DEV daily warmup batch. Never collects evaluation prices."""
import hashlib,json,os,subprocess,time,urllib.request,urllib.parse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'research/development_evidence/TRADER_LIFECYCLE_BENCHMARK_AFTER_PR1249_V1'
SYMBOLS=['1000PEPE-USDT','BCH-USDT','BTC-USDT','ETH-USDT','HYPE-USDT','LINK-USDT','SOL-USDT']
DAY=86400000; START=1734595200000

def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);data=(json.dumps(v,indent=2,sort_keys=True)+'\n').encode()
 with p.open('wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
def persist(message):
 subprocess.run(['git','add',str(OUT.relative_to(ROOT))],check=True)
 subprocess.run(['git','commit','-m',message+' [skip ci]'],check=True)
 subprocess.run(['git','push','origin','HEAD:research/trader-lifecycle-after-pr1249-v1'],check=True)
 local=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
 remote=subprocess.check_output(['git','ls-remote','origin','refs/heads/research/trader-lifecycle-after-pr1249-v1'],text=True).split()[0]
 if remote!=local:raise RuntimeError('PERSIST_READBACK_FAILED')
def run():
 budget=json.loads((OUT/'BUDGET.json').read_text())
 if budget['source_status']!='RESERVED_NOT_STARTED':raise RuntimeError('NO_RETRY')
 budget['source_status']='STARTED';budget['source_run_id']=os.environ['GITHUB_RUN_ID'];save(OUT/'BUDGET.json',budget);persist('JC source batch started with seven GET reservation')
 receipts=[];total=0
 for symbol in SYMBOLS:
  query=urllib.parse.urlencode(dict(symbol=symbol,interval='1d',startTime=START-370*DAY,endTime=START-1,limit=500))
  url='https://open-api.bingx.com/openApi/swap/v3/quote/klines?'+query
  receipt=dict(symbol=symbol,url=url,status='STARTED',ordinal=len(receipts)+1,requested_at_ms=int(time.time()*1000));receipts.append(receipt)
  save(OUT/'SOURCE/REQUESTS.json',receipts);persist('JC warmup request reserved '+symbol)
  try:
   with urllib.request.urlopen(url,timeout=25) as response:raw=response.read(1048577);receipt['http_status']=response.status
   if len(raw)>1048576:raise RuntimeError('PER_RESPONSE_CAP')
   total+=len(raw);receipt.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
   p=OUT/'SOURCE/raw'/f'{symbol}.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
   data=json.loads(raw)
   if data.get('code')!=0:raise RuntimeError('API_ERROR_'+str(data.get('code')))
   rows=data.get('data'); assert isinstance(rows,list)
   normalized=[]
   for r in rows:
    if not isinstance(r,dict):raise RuntimeError('UNSUPPORTED_OBJECT_SCHEMA')
    ts=int(r['time'])
    if ts%DAY or not START-370*DAY<=ts or ts+DAY>START:raise RuntimeError('WARMUP_BOUNDARY_VIOLATION')
    normalized.append(dict(open_ts=ts,**{k:float(r[k]) for k in ['open','high','low','close','volume']}))
   normalized.sort(key=lambda r:r['open_ts'])
   if any(b['open_ts']-a['open_ts']!=DAY for a,b in zip(normalized,normalized[1:])):raise RuntimeError('DAILY_GAP')
   save(OUT/'SOURCE/daily'/f'{symbol}.json',normalized)
   receipt.update(status='STORED',rows=len(normalized),first_open=normalized[0]['open_ts'] if normalized else None,last_close=normalized[-1]['open_ts']+DAY if normalized else None)
  except Exception as e:receipt.update(status='FAILED_NO_RETRY',error=type(e).__name__+':'+str(e))
  save(OUT/'SOURCE/REQUESTS.json',receipts);persist('JC warmup response stored '+symbol)
 budget.update(source_status='STOPPED',source_get_actual=len(receipts),source_bytes_actual=total,source_get_reserved=0,source_bytes_reserved=0);save(OUT/'BUDGET.json',budget);persist('JC bounded warmup batch stopped')
if __name__=='__main__':run()
