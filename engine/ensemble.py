import os, math, json, time
COEF_F = "/home/z/z/config/ensemble.json"
DEF = {"bias":{"trendX":0.0,"breakoutLite":0.0,"alpha1":0.0},
       "beta":{"trend":0.9,"breakout":0.8,"momentum":0.6,"vol":0.4,"liquidity":0.2}}

def _load():
    try: return json.loads(open(COEF_F,"r",encoding="utf-8").read())
    except: return DEF

def softmax(x, temp=0.7):
    ex=[math.exp((xi)/max(temp,1e-6)) for xi in x]; s=sum(ex); return [e/max(s,1e-9) for e in ex]

def weights(reg:dict, perf:dict|None=None, topk:int=2, temp:float=0.7)->dict:
    C=_load(); bias=C["bias"]; beta=C["beta"]
    # 로짓 = bias + ∑ beta_k * reg[k] + perf 보정
    names=["trendX","breakoutLite","alpha1"]
    # 간단 매핑
    mapK={"trendX":["trend","momentum"], "breakoutLite":["breakout","vol"], "alpha1":["momentum","liquidity"]}
    logits=[]
    for n in names:
        z = bias.get(n,0.0)
        for k in mapK[n]:
            z += beta.get(k,0.0)*float(reg.get(k,0.0))
        if perf:
            wr=float(perf.get(n,{}).get("wr",0.5)); pf=float(perf.get(n,{}).get("pf",1.0))
            z += 0.5*(wr-0.5) + 0.2*(pf-1.0)
        logits.append(z)
    w = softmax(logits, temp=temp)
    pairs=sorted(list(zip(names,w)), key=lambda x:x[1], reverse=True)[:topk]
    s=sum(p for _,p in pairs); return {n:round(p/max(s,1e-9),4) for n,p in pairs}

STATE={"weights":{}, "ts":0, "reg":{}}

def update(reg:dict, perf:dict|None=None, topk:int=2, temp:float=0.7):
    if os.getenv("META_ON","off")!="on": return STATE
    W = weights(reg, perf, topk=int(os.getenv("ENSEMBLE_TOPK","2")), temp=float(os.getenv("ENSEMBLE_TEMP","0.7")))
    STATE["weights"]=W; STATE["reg"]=reg; STATE["ts"]=int(time.time()); return STATE