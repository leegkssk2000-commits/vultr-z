#!/usr/bin/env python3
"""G5 Supertrend high-vol 4h native EMA as-of evidence gate. NO strategy policy/PnL change.
Read only. The 26 reviewed trades are labels, not untouched OOS for a new child.
The native candle/features must be captured by existing authorized source owner,
with immutable payload SHA and independently observed available/received timestamps.
"""
from __future__ import annotations
import argparse, hashlib, json, math, sys, importlib
from pathlib import Path

BAR = 14_400_000
FROZEN_ID = "supertrend_replacement_highvol_mom_long_4h_h12_v2"
SOURCE_BLOB = "70f5f6829d860a67f7df8e4ff1994965218c042c"
CONTRACT_BLOB = "318df316882718d18d98fda51702473f1d092131"
NATIVE_BLOB = "4566931dab335d45884704fe98f6e1c70629f92a"
SYMBOLS = ("1000PEPE-USDT","BCH-USDT","BTC-USDT","ETH-USDT","HYPE-USDT","LINK-USDT","SOL-USDT")

def gitblob(blob: bytes)->str:
    return hashlib.sha1(b"blob "+str(len(blob)).encode()+b"\0"+blob).hexdigest()

def load_pin(p: Path, sha: str):
    b=p.read_bytes()
    if gitblob(b)!=sha: raise ValueError("FROZEN_SOURCE_CHANGED")
    return json.loads(b)

def asof_bars(pkt:dict, sym:str):
    if pkt.get("symbol")!=sym or pkt.get("timeframe")!="4h":
        raise ValueError("SOURCE_SYMBOL_TF_MISMATCH")
    bars=pkt.get("bars")
    if not isinstance(bars,list) or len(bars)<60:
        raise ValueError("RAW_4H_PREFIX_NOT_BOUND")
    sha=pkt.get("raw_sha256")
    body=json.dumps(bars,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    if sha!=hashlib.sha256(body).hexdigest():
        raise ValueError("RAW_INPUT_SHA_NOT_BOUND")
    prior=None
    for b in bars:
        t=b.get("ts");a=b.get("available_at_ms");r=b.get("received_at_ms")
        if (type(t)!=int or type(a)!=int or type(r)!=int or t%BAR or
            a<t+BAR or r<a or (prior is not None and t-prior!=BAR)):
            raise ValueError("BAR_CLOCK_GAP_OR_RECEIPT_MISSING")
        for f in ("open","high","low","close"):
            if type(b.get(f)) not in (int,float) or not math.isfinite(b[f]) or b[f]<=0:
                raise ValueError("INVALID_OHLC")
        if b["high"]<max(b["open"],b["close"]) or b["low"]>min(b["open"],b["close"]):
            raise ValueError("INVALID_CANDLE_GEOMETRY")
        prior=t
    return bars

def trace(trades:list,bars:list,ema20:list,ema50:list,sym:str):
    tm={b["ts"]:i for i,b in enumerate(bars)}
    if len(tm)!=len(bars) or len(ema20)!=len(bars) or len(ema50)!=len(bars):
        raise ValueError("NATIVE_FEATURE_LENGTH_OR_DUPLICATE")
    output=[]
    for t in trades:
        if t["symbol"]!=sym:continue
        if t.get("child_id")!=FROZEN_ID:raise ValueError("MIXED_CHILD_LINEAGE")
        try:i,j,k=(tm[t[name]] for name in ("signal_ts","entry_ts","exit_ts"))
        except KeyError:raise ValueError("ORIGINAL_TRADE_4H_PATH_MISSING") from None
        if j!=i+1 or k!=j+11 or not math.isclose(bars[k]["close"],t["exit_px"],rel_tol=1e-8):
            raise ValueError("ORIGINAL_NEXT_OPEN_OR_H12_PARITY_FAIL")
        if not math.isclose(bars[j]["open"],t["entry_px"],rel_tol=1e-8):
            raise ValueError("ENTRY_NATIVE_FILL_PARITY_FAIL")
        first=None
        for b in range(j,k+1):
            x,y=ema20[b],ema50[b]
            if x is None or y is None or not math.isfinite(x) or not math.isfinite(y):
                raise ValueError("EMA_NATIVE_FEATURE_NOT_BOUND")
            if first is None and x<=y:
                first={"bar_open_ts":bars[b]["ts"],"received_at_ms":bars[b]["received_at_ms"],
                       "would_require_new_fill_proof":True}
        # Winner-tail study only: observe up to one ORIGINAL 12-bar holding window
        # beyond the frozen time-stop. Never create an extended position/fill/PnL.
        observed_after_exit=[]
        for q in range(k+1,min(len(bars),k+13)):
            u,v=ema20[q],ema50[q]
            if u is None or v is None or not math.isfinite(u) or not math.isfinite(v):
                raise ValueError("RUNNER_NATIVE_EMA_NOT_BOUND")
            observed_after_exit.append({"bar_open_ts":bars[q]["ts"],
                "bar_received_at_ms":bars[q]["received_at_ms"],
                "ema_trend_intact":bool(u>v)})
        output.append({"closed_trade_id":t["closed_trade_id"],
                       "modeled_original_net2_bps":t["gross_bps"]-2*t["cost_bps"],
                       "ema_trend_loss_before_original_exit":first,
                       "continuation_after_time_stop_observation_only":observed_after_exit,
                       "signal_received_before_exact_entry_open":bars[i]["received_at_ms"]<=bars[j]["ts"],
                       "original_exit_unchanged":True})
    return output

def test():
    start=BAR*1234
    bars=[]
    for i in range(80):
        ts=start+i*BAR;v=100+i*.3
        bars.append({"ts":ts,"open":v,"high":v+1,"low":v-1,"close":v,
                     "available_at_ms":ts+BAR+1,"received_at_ms":ts+BAR+2})
    def pkt(z):
        return {"symbol":"BTC-USDT","timeframe":"4h","bars":z,
                "raw_sha256":hashlib.sha256(json.dumps(z,sort_keys=True,separators=(",",":")).encode()).hexdigest()}
    assert len(asof_bars(pkt(bars),"BTC-USDT"))==80
    invalid=[bars[::-1],bars[:4]+bars[3:4]+bars[4:],bars[:9]+bars[10:],
             [{**bars[0],"available_at_ms":0}]+bars[1:],
             [{**bars[0],"received_at_ms":0}]+bars[1:],
             [{**bars[0],"high":0}]+bars[1:]]
    for z in invalid:
        try:asof_bars(pkt(z),"BTC-USDT")
        except ValueError:pass
        else:raise AssertionError("MISSING_COUNTEREXAMPLE_REJECT")
    row={"symbol":"BTC-USDT","child_id":FROZEN_ID,"closed_trade_id":"fixture1",
         "signal_ts":bars[50]["ts"],"entry_ts":bars[51]["ts"],"exit_ts":bars[62]["ts"],
         "entry_px":bars[51]["open"],"exit_px":bars[62]["close"],"cost_bps":20,"gross_bps":200}
    result=trace([row],bars,[10]*80,[9]*80,"BTC-USDT")
    assert len(result)==1 and result[0]["ema_trend_loss_before_original_exit"] is None
    assert len(result[0]["continuation_after_time_stop_observation_only"])==12
    assert not result[0]["signal_received_before_exact_entry_open"]
    bad=[10]*80;bad[55]=8
    assert trace([row],bars,bad,[9]*80,"BTC-USDT")[0]["ema_trend_loss_before_original_exit"] is not None
    try: trace([{**row,"entry_ts":bars[52]["ts"]}],bars,[10]*80,[9]*80,"BTC-USDT")
    except ValueError:pass
    else:raise AssertionError("NEXT_OPEN_NOT_CAUSAL")
    print(json.dumps({"synthetic_checks":11,"result":"PASS","economic_full":0,"orders":0}))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--test",action="store_true")
    ap.add_argument("--original",type=Path)
    ap.add_argument("--contract",type=Path)
    ap.add_argument("--native",type=Path)
    ap.add_argument("--market-asof",type=Path)
    ap.add_argument("--repo-root",type=Path)
    args=ap.parse_args()
    if args.test:return test()
    for name in ("original","contract","native","market_asof"):
        p=getattr(args,name)
        if not p or not p.is_file():
            print(json.dumps({"state":"HOLD_SOURCE_FEATURE_NOT_BOUND","first_field":name,
                 "reason":"IMMUTABLE_ORIGINAL_4H_OHLC_EMA_AND_OBSERVED_AVAILABLE_TS_REQUIRED",
                 "new_child":0,"new_economic_full":0,"orders":0}))
            return
    source=load_pin(args.original,SOURCE_BLOB)
    contract=load_pin(args.contract,CONTRACT_BLOB)
    if gitblob(args.native.read_bytes())!=NATIVE_BLOB:raise ValueError("NATIVE_CODE_CHANGED")
    child=[x for x in contract["children"] if x["child_id"]==FROZEN_ID]
    if len(child)!=1 or child[0]["executable_spec"]["exit_rule"]!="time_stop" or child[0]["executable_spec"]["max_hold_bars"]!=12:
        raise ValueError("ORIGINAL_EXIT_CHANGED")
    bundle=json.loads(args.market_asof.read_text())
    if (bundle.get("schema")!="zel.g5.4h.complete_candles_asof.v1" or
        set(bundle.get("symbols",{}))!=set(SYMBOLS)):
        raise ValueError("ORIGINAL_4H_BUNDLE_INCOMPLETE")
    # Need signed native feature values computed by exact native engine, not caller inventions.
    native=bundle.get("native_code_gitblob")
    if native!=NATIVE_BLOB:raise ValueError("FEATURE_PRODUCER_NOT_NATIVE")
    if not args.repo_root or not args.repo_root.is_dir():raise ValueError("NATIVE_REPO_MISSING")
    sys.path.insert(0,str(args.repo_root))
    native_module=importlib.import_module("backend.research.rebuild.a1_top5_replacement_child_prospective_v1")
    if Path(native_module.__file__).resolve()!=args.native.resolve():
        raise ValueError("NATIVE_FEATURE_MODULE_NOT_PINNED")
    results=[]
    for symbol in SYMBOLS:
        z=bundle["symbols"][symbol];bars=asof_bars(z,symbol)
        features,_=native_module._features(bars,child[0]["executable_spec"])
        if not all(q in features for q in ("ema20","ema50")):raise ValueError("NATIVE_EMA_MISSING")
        results+=trace(source["lanes"]["supertrend_pullback_main"]["closed_trades"],
                       bars,features["ema20"],features["ema50"],symbol)
    print(json.dumps({"state":"OBSERVATIONAL_NATIVE_4H_WITNESS_NO_POLICY_CHANGE","rows":results,
        "original_trade_count":len(results),"new_child":0,"economic_full":0,"orders":0}))

if __name__=="__main__":main()
