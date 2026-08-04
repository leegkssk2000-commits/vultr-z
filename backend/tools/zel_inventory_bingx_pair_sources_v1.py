from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOTS = (Path('/home/z'), Path('/opt'), Path('/etc'))
PRUNE = {'.git','.cache','.venv','venv','node_modules','__pycache__','dist','build','artifacts','checkpoints','logs','tmp'}
HINTS = ('.env','env','secret','cred','config','bingx','exchange','key','.json','.yaml','.yml','.toml','.ini','.service','.py')
MAX = 1_048_576
ASSIGN = re.compile(r'^\s*(?:export\s+|Environment=)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*?)\s*$')
KEY = {'bingxapikey','bingxkey','bingxaccesskey','bingxapiaccesskey','bingxkeyid','bingxapi'}
SECRET = {'bingxsecretkey','bingxapisecret','bingxsecret','bingxapisecretkey'}
BASE='https://open-api.bingx.com'


def norm(v:str)->str:
    return re.sub(r'[^a-z0-9]','',v.lower())


def classify(name:str, context:str='')->str|None:
    n,c=norm(name),norm(context)
    if n in KEY:return 'key'
    if n in SECRET:return 'secret'
    if 'bingx' in c:
        if n in {'apikey','accesskey','key','keyid','api'}:return 'key'
        if n in {'secret','secretkey','apisecret','apisecretkey'}:return 'secret'
    return None


def uq(v:str)->str:
    x=v.strip()
    if len(x)>=2 and x[0]==x[-1] and x[0] in {'\"',"'"}:x=x[1:-1]
    else:x=x.split(' #',1)[0].strip()
    return '' if any(ch in x for ch in ('\x00','\n','\r')) else x


def parse(text:str, context:str)->tuple[dict[str,str],set[str]]:
    vals:dict[str,str]={}; aliases:set[str]=set()
    for line in text.splitlines():
        m=ASSIGN.match(line)
        if not m:continue
        t=classify(m.group('name'),context)
        v=uq(m.group('value'))
        if t and len(v)>=8:
            vals[t]=v; aliases.add(m.group('name'))
    return vals,aliases


def files()->list[Path]:
    out:set[Path]=set()
    for root in ROOTS:
        if not root.exists():continue
        for cur,dirs,names in os.walk(root,topdown=True,followlinks=False):
            dirs[:]=[d for d in dirs if d not in PRUNE and not d.startswith('.')]
            for name in names:
                low=name.lower()
                if not any(h in low for h in HINTS):continue
                p=Path(cur)/name
                try:
                    if p.is_symlink() or not p.is_file():continue
                    if 0<p.stat().st_size<=MAX:out.add(p)
                except (OSError,PermissionError):pass
    return sorted(out)


def validate(key:str,secret:str)->dict[str,Any]:
    params={'recvWindow':5000,'timestamp':int(time.time()*1000)}
    qs='&'.join(f'{k}={params[k]}' for k in sorted(params))
    sig=hmac.new(secret.encode(),qs.encode(),hashlib.sha256).hexdigest()
    req=urllib.request.Request(f'{BASE}/openApi/swap/v2/user/commissionRate?{qs}&signature={sig}',headers={'X-BX-APIKEY':key,'X-SOURCE-KEY':'BX-AI-SKILL','User-Agent':'ZEL_BINGX_PAIR_INVENTORY_V1'})
    try:
        with urllib.request.urlopen(req,timeout=12) as r: payload=json.loads(r.read())
        return {'http':'OK','bingx_code':payload.get('code'),'pass':int(payload.get('code',-1))==0}
    except urllib.error.HTTPError as exc:
        try:
            payload=json.loads(exc.read())
            return {'http':exc.code,'bingx_code':payload.get('code'),'pass':False}
        except Exception:
            return {'http':exc.code,'bingx_code':None,'pass':False}
    except Exception as exc:
        return {'http':type(exc).__name__,'bingx_code':None,'pass':False}


def main()->int:
    grouped:dict[str,dict[str,Any]]={}
    for p in files():
        try:text=p.read_text(encoding='utf-8',errors='ignore')
        except (OSError,PermissionError):continue
        vals,aliases=parse(text,p.name)
        if not {'key','secret'}<=vals.keys():continue
        fp=hashlib.sha256((vals['key']+'\0'+vals['secret']).encode()).hexdigest()
        row=grouped.setdefault(fp,{'values':vals,'sources':[],'aliases':set()})
        row['sources'].append(str(p));row['aliases'].update(aliases)
    rows=[]
    for i,(_,row) in enumerate(sorted(grouped.items(),key=lambda kv:sorted(kv[1]['sources'])),1):
        result=validate(row['values']['key'],row['values']['secret'])
        rows.append({'pair_id':f'pair{i}','source_paths':sorted(row['sources']),'alias_names':sorted(row['aliases']),'read_only_validation':result})
    receipt={'schema_version':'zel.bingx.pair_source_inventory.v1','pair_count':len(rows),'pairs':rows,'secret_values_logged':False,'secret_values_artifacted':False,'order_authority':'BLOCKED','execution_authority':'NONE','action':'hold'}
    material=json.dumps(receipt,sort_keys=True,separators=(',',':'),allow_nan=False).encode();receipt['receipt_sha256']=hashlib.sha256(material).hexdigest()
    Path('/tmp/zel_bingx_pair_source_inventory.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'pair_count':len(rows),'receipt_sha256':receipt['receipt_sha256']}))
    return 0

if __name__=='__main__':raise SystemExit(main())
