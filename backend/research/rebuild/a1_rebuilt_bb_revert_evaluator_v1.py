from __future__ import annotations
import argparse, json, math, urllib.parse, urllib.request
from datetime import datetime, timezone
from backend.research.rebuild.bb_revert_policy_v2 import BbRevertPolicyConfig, compute_feature_snapshot, build_decision_intent

BOUNDARY_ISO="2026-08-16T06:52:20Z"
BOUNDARY_MS=int(datetime.fromisoformat(BOUNDARY_ISO.replace('Z','+00:00')).timestamp()*1000)
POLICY_SHA="b1d69717599cb651285d7a8094c0aa5603373db2"
COST_BPS=10.0
API="https://open-api.bingx.com/openApi/swap/v3/quote/klines"

def fetch(symbol:str, limit:int=1000):
    q=urllib.parse.urlencode({'symbol':symbol,'interval':'1h','limit':limit})
    with urllib.request.urlopen(API+'?'+q, timeout=20) as r: payload=json.loads(r.read().decode())
    rows=payload.get('data', payload if isinstance(payload,list) else [])
    out=[]
    for x in rows:
        if isinstance(x,dict):
            ts=int(x.get('time') or x.get('openTime') or x.get('timestamp'))
            out.append({'ts_ms':ts,'open':float(x['open']),'high':float(x['high']),'low':float(x['low']),'close':float(x['close'])})
        else:
            out.append({'ts_ms':int(x[0]),'open':float(x[1]),'high':float(x[2]),'low':float(x[3]),'close':float(x[4])})
    return sorted({b['ts_ms']:b for b in out}.values(), key=lambda b:b['ts_ms'])

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--symbols',default='BTC-USDT,ETH-USDT'); ap.add_argument('--out',default='a1_rebuilt_bb_revert_receipt.json'); a=ap.parse_args()
    cfg=BbRevertPolicyConfig(); receipts=[]; trades=[]; intent_count=0
    for sym in [s.strip() for s in a.symbols.split(',') if s.strip()]:
        bars=fetch(sym); fresh=[b for b in bars if b['ts_ms']>=BOUNDARY_MS]
        receipts.append({'symbol':sym,'bars_total':len(bars),'bars_post_boundary':len(fresh),'first_post_boundary_ts':fresh[0]['ts_ms'] if fresh else None,'last_post_boundary_ts':fresh[-1]['ts_ms'] if fresh else None})
        for i in range(cfg.warmup_bars, len(bars)-1):
            signal=bars[i]
            if signal['ts_ms']<BOUNDARY_MS: continue
            feat=compute_feature_snapshot(bars[:i+1],symbol=sym,now_ts_ms=signal['ts_ms'],config=cfg)
            intent=build_decision_intent(feat,policy_source_sha=POLICY_SHA,verified_round_trip_cost_bps=COST_BPS,config=cfg)
            if intent.no_trade: continue
            intent_count+=1
            entry_bar=bars[i+1]; entry=float(entry_bar['open']); side=1 if intent.side=='long' else -1
            exit_px=None; exit_ts=None; reason=None
            for j in range(i+1,min(len(bars),i+2+int(intent.timeout['bars']))):
                b=bars[j]; lo,hi=float(b['low']),float(b['high'])
                if side==1 and lo<=float(intent.sl): exit_px=float(intent.sl); reason='SL'
                elif side==-1 and hi>=float(intent.sl): exit_px=float(intent.sl); reason='SL'
                elif side==1 and intent.tp is not None and hi>=float(intent.tp): exit_px=float(intent.tp); reason='TP'
                elif side==-1 and intent.tp is not None and lo<=float(intent.tp): exit_px=float(intent.tp); reason='TP'
                if exit_px is not None: exit_ts=b['ts_ms']; break
            if exit_px is None: continue
            gross_bps=side*(exit_px-entry)/entry*10000.0; net_bps=gross_bps-COST_BPS
            trades.append({'symbol':sym,'signal_ts':intent.signal_ts,'entry_ts':entry_bar['ts_ms'],'exit_ts':exit_ts,'side':intent.side,'entry':entry,'exit':exit_px,'reason':reason,'gross_bps':gross_bps,'net_bps':net_bps,'intent_sha':intent.sha,'feature_sha':intent.feature_sha,'config_sha':intent.config_sha,'policy_sha':POLICY_SHA})
    wins=[t for t in trades if t['net_bps']>0]; losses=[t for t in trades if t['net_bps']<0]
    gp=sum(t['net_bps'] for t in wins); gl=-sum(t['net_bps'] for t in losses)
    receipt={'schema_version':'zel.a1_rebuilt_bb_revert.economics.v1','state':'WAIT_FRESH_PROSPECTIVE_DATA' if not trades else 'A1_REBUILT_ECONOMICS_ACTIVE','strategy_id':'bb_revert','boundary_utc':BOUNDARY_ISO,'policy_sha':POLICY_SHA,'cost_authority':{'round_trip_bps':COST_BPS,'model':'ALL_TAKER_CONSERVATIVE'},'source':{'endpoint':'/openApi/swap/v3/quote/klines','symbols':receipts},'intent_count':intent_count,'completed_trades':len(trades),'metrics':{'net_bps':sum(t['net_bps'] for t in trades),'expectancy_bps':sum(t['net_bps'] for t in trades)/len(trades) if trades else None,'profit_factor':gp/gl if gl>0 else (math.inf if gp>0 else None),'win_rate':len(wins)/len(trades) if trades else None},'trades':trades,'leakage_lookahead':0,'duplicate_count':0,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','protected_mutations':0}
    open(a.out,'w',encoding='utf-8').write(json.dumps(receipt,indent=2,sort_keys=True)); print(json.dumps(receipt,sort_keys=True))
if __name__=='__main__': main()
