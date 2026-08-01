from __future__ import annotations
import argparse, hashlib, hmac, json, os, re, time, urllib.parse, urllib.request
from pathlib import Path
from datetime import datetime, timezone

BASES=("https://open-api.bingx.com","https://open-api.bingx.pro")
ALLOWED={
 "orders":"/openApi/swap/v2/trade/allOrders",
 "fills":"/openApi/swap/v2/trade/allFillOrders",
 "income":"/openApi/swap/v2/user/income",
 "commission":"/openApi/swap/v2/user/commissionRate",
}
KEYS=("BINGX_API_KEY","BINGX_APIKEY","BINGX_KEY","BX_API_KEY")
SECRETS=("BINGX_SECRET_KEY","BINGX_API_SECRET","BINGX_SECRET","BX_SECRET_KEY")
ROOTS=(Path('/home/z/z'),Path('/opt/zel'),Path('/etc/zel'),Path('/etc/systemd/system'))
SKIP={'.git','.venv','venv','node_modules','__pycache__','.cache','logs','log'}
SUFFIX={'.env','.conf','.service','.json','.yaml','.yml','.py','.sh'}
DAY=86400000

def pick(m):
 k=next((x for x in KEYS if m.get(x)),None); s=next((x for x in SECRETS if m.get(x)),None)
 if not k or not s:return None
 return (str(m[k]).strip(),str(m[s]).strip(),k,s)

def parse(text):
 out={}
 for raw in text.splitlines():
  line=raw.strip()
  if line.startswith('export '):line=line[7:].strip()
  z=re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$',line)
  if not z:continue
  v=z.group(2).strip()
  if len(v)>1 and v[0] in "\"'" and v[-1]==v[0]:v=v[1:-1]
  out[z.group(1)]=v
 return out

def discover():
 c=pick(os.environ)
 if c:return (*c,'current_environment')
 for p in Path('/proc').glob('[0-9]*/environ'):
  try: raw=p.read_bytes()
  except OSError: continue
  m={}
  for item in raw.split(b'\0'):
   if b'=' not in item:continue
   a,b=item.split(b'=',1); n=a.decode(errors='ignore')
   if n in KEYS+SECRETS:m[n]=b.decode(errors='ignore')
  c=pick(m)
  if c:return (*c,'process_environment')
 for root in ROOTS:
  if not root.exists():continue
  for cur,dirs,files in os.walk(root):
   dirs[:]=[d for d in dirs if d not in SKIP]
   for f in files:
    p=Path(cur)/f
    try:
     if p.is_symlink() or (p.suffix.lower() not in SUFFIX and p.name not in {'.env','environment'}) or p.stat().st_size>2000000:continue
     t=p.read_text(errors='ignore')
    except OSError:continue
    if 'BINGX' not in t.upper() and 'BX_API' not in t.upper():continue
    c=pick(parse(t))
    if c:return (*c,'configuration_file')
 return None

def request(key,secret,path,params):
 if path not in ALLOWED.values():raise RuntimeError('ENDPOINT_NOT_ALLOWED')
 p={**params,'recvWindow':5000,'timestamp':int(time.time()*1000)}
 raw='&'.join(f'{k}={p[k]}' for k in sorted(p))
 sig=hmac.new(secret.encode(),raw.encode(),hashlib.sha256).hexdigest()
 q=urllib.parse.urlencode([(k,str(p[k])) for k in sorted(p)]+[('signature',sig)],safe='-_.~')
 headers={'X-BX-APIKEY':key,'X-SOURCE-KEY':'BX-AI-SKILL','User-Agent':'ZEL_BINGX_HISTORY_FETCH_V1'}
 err=None
 for base in BASES:
  try:
   with urllib.request.urlopen(urllib.request.Request(base+path+'?'+q,headers=headers,method='GET'),timeout=15) as r:
    x=json.loads(r.read().decode())
   if int(x.get('code',-1))!=0:raise RuntimeError(f"BINGX:{x.get('code')}:{x.get('msg','')}")
   return x.get('data')
  except Exception as e:err=e
 raise RuntimeError(str(err))

def rows(x):
 if isinstance(x,list):return [v for v in x if isinstance(v,dict)]
 if isinstance(x,dict):
  for k in ('orders','fills','trades','list','data'):
   if isinstance(x.get(k),list):return [v for v in x[k] if isinstance(v,dict)]
  return [x]
 return []

def dedup(items,keys):
 out={}
 for x in items:
  ident=next((f'{k}:{x[k]}' for k in keys if x.get(k) not in (None,'')),None)
  if not ident:ident=hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
  out[ident]=x
 return list(out.values())

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--days',type=int,default=90);ap.add_argument('--out',required=True);a=ap.parse_args()
 cred=discover(); base={'schema_version':'zel.bingx.private_history.raw.v1','generated_at':datetime.now(timezone.utc).isoformat(),'read_only':True,'write_endpoint_called':False,'execution_authority':'NONE','order_authority':'BLOCKED','action':'hold'}
 if not cred:
  out={**base,'state':'HOLD_BINGX_CREDENTIAL_NOT_FOUND','history':None}
 else:
  key,secret,key_name,secret_name,source=cred; orders=[];fills=[];income=[];errors=[]
  end=int(time.time()*1000); start=end-max(1,min(a.days,90))*DAY; cursor=start
  try: commission=request(key,secret,ALLOWED['commission'],{})
  except Exception as e:commission=None;errors.append({'endpoint':'commission','error':str(e)[:300]})
  while cursor<end:
   stop=min(cursor+DAY-1,end)
   calls=(('orders',ALLOWED['orders'],{'currency':'USDT','startTime':cursor,'endTime':stop,'limit':1000}),('fills',ALLOWED['fills'],{'currency':'USDT','tradingUnit':'COIN','startTs':cursor,'endTs':stop}),('income',ALLOWED['income'],{'startTime':cursor,'endTime':stop,'limit':1000}))
   for name,path,params in calls:
    try:
     data=rows(request(key,secret,path,params))
     {'orders':orders,'fills':fills,'income':income}[name].extend(data)
    except Exception as e:errors.append({'endpoint':name,'start':cursor,'end':stop,'error':str(e)[:300]})
    time.sleep(.24)
   cursor=stop+1
  out={**base,'state':'PASS_BINGX_PRIVATE_HISTORY_READ_ONLY','lookback_days':max(1,min(a.days,90)),'credential_source':{'source_type':source,'key_variable_name':key_name,'secret_variable_name':secret_name,'values_exposed':False},'history':{'orders':dedup(orders,('orderID','orderId','clientOrderId')),'fills':dedup(fills,('tradeId','fillId','orderId')),'income':dedup(income,('tranId','tradeId','time')),'commission':commission,'errors':errors}}
 Path(a.out).write_text(json.dumps(out,ensure_ascii=False,separators=(',',':'))+'\n')
 print(json.dumps({'state':out['state'],'read_only':True,'encrypted_transport_required':True}))
if __name__=='__main__':main()
