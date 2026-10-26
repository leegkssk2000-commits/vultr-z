#!/usr/bin/env python3
"""K117 read-only sealed OHLC seed + prospective B4 bars. No order/signal authority.

Default mode only emits native feature/regime readiness. This cannot replay
historical admissions, bypass the B-original volume UNKNOWN, or claim formal
Shadow, fill, fee/funding, account NAV, or G5 promotion.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

K117_SOURCE_ID = "f6306e27c39c0cb58930d18afbd99fbfabb42aa349a5cb82473389d707a995d0"
TF = 1800000
SYMS=("BTC-USDT","ETH-USDT","SOL-USDT","XRP-USDT","LINK-USDT","DOGE-USDT")
COLS=("open_ts_ms","close_ts_ms","available_ts_ms","open","high","low","close")


def sha(p: bytes) -> str:
    return hashlib.sha256(p).hexdigest()


def seed_read(seed_path: Path) -> tuple[dict, dict]:
    root=seed_path.resolve()
    data=(root/"CONTEXT_OHLC_ONLY.json").read_bytes()
    man=json.loads((root/"MANIFEST.json").read_bytes())
    if sha(data)!=man["content_sha256"]:
        raise ValueError("FROZEN_CONTEXT_SEED_SHA_MISMATCH")
    seed=json.loads(data)
    if (seed.get("source_identity_sha256")!=K117_SOURCE_ID
        or seed.get("source_volume_units")!="UNKNOWN"
        or seed.get("formal_shadow_authority") is not False
        or seed.get("replay_makes_historical_trades") is not False
        or set(seed.get("frames",{}))!=set(SYMS)):
        raise ValueError("K117_SOURCE_SEED_CONTRACT_MISMATCH")
    if set(man.get("bar_count_by_symbol",{}))!=set(SYMS):
        raise ValueError("SEED_SYMBOLS_MISMATCH")
    for sym,rows in seed["frames"].items():
        if len(rows)!=121 or man["bar_count_by_symbol"][sym]!=121:
            raise ValueError("MISSING_SEALED_121_BARS")
        if any(rows[i]["close_ts_ms"]!=rows[i+1]["open_ts_ms"] for i in range(120)):
            raise ValueError("GAP_IN_SEALED_HISTORY")
        if max(row["available_ts_ms"] for row in rows)>seed["captured_at_ms"]:
            raise ValueError("FUTURE_SEED_AVAILABILITY")
    return seed, man


def only_future(prefix: list[dict], observed: list[dict], asof_ms: int, capture_ms: int) -> list[dict]:
    if asof_ms<capture_ms:
        raise ValueError("CLOCK_BEFORE_SEED_FREEZE")
    prev_close=int(prefix[-1]["close_ts_ms"])
    result=[]
    for bar in sorted(observed,key=lambda a:int(a["close_ts_ms"])):
        end=int(bar["close_ts_ms"])
        if end<=prev_close:
            # Original seed already covers this history. Never emit/replay.
            continue
        opened=int(bar["open_ts_ms"])
        if opened!=prev_close or end!=opened+TF:
            raise ValueError("PROSPECTIVE_BAR_GAP_OR_ORDER")
        stamp=int(bar["available_ts_ms"])
        if stamp>end and stamp>asof_ms or end>asof_ms or stamp<end:
            raise ValueError("FUTURE_OR_UNCLOSED_BAR")
        if bar.get("evidence_kind")!="ACTUAL_PUBLIC_CLOSED_30M" or bar.get("formal_fresh_credit") is not False:
            raise ValueError("PROSPECTIVE_BAR_NOT_ORIGINAL_B")
        values=[float(bar[k]) for k in ("open","high","low","close")]
        if min(values)<=0 or values[1]<max(values[0],values[2],values[3]) or values[2]>min(values[0],values[1],values[3]):
            raise ValueError("INVALID_PROSPECTIVE_OHLC")
        result.append({k:bar[k] for k in COLS})
        prev_close=end
    return result


def check(seed_dir: Path,pointer_path: Path, checkout: Path, asof_ms: int) -> dict:
    seed, man=seed_read(seed_dir)
    if seed["captured_at_ms"]>=asof_ms:
        raise ValueError("NO_PROSPECTIVE_DECISION_AFTER_SEED")
    path=checkout.resolve()
    sys.path.insert(0,str(path))
    sys.path.insert(0,str(path/"research/campaigns/scalp7_20261022/parallel_fastfinish_v1/work_e"))
    # Import exact original frozen K117/B read-only snapshot code; NEVER main().
    import k117_development_observer as obs
    import pandas as pd
    from backend.research.rebuild.scalp7_fresh_forward_v2 import bind_frozen_context
    from backend.research.rebuild import scalp7_positive_lanes_v2 as positive
    snap=obs.read_snapshot(pointer_path,asof_ms,check_process=True)
    if snap["source_identity_sha256"]!=K117_SOURCE_ID:
        raise ValueError("B_PRODUCER_SOURCE_IDENTITY_CHANGED")
    observed=snap["state"]["market"]
    fit=json.loads((path/"research/campaigns/scalp7_20260915/broad_rebuild_v2/FRESH_FORWARD_CONFIG_V2.json").read_text())["regime_fit"]
    frames={}
    count={}
    for sym in SYMS:
        old=seed["frames"][sym]
        new=only_future(old,[r for r in observed if r["symbol"]==sym],asof_ms,seed["captured_at_ms"])
        count[sym]=len(new)
        records=old+new
        df=pd.DataFrame(records)
        for c in ("open","high","low","close"):
            df[c]=pd.to_numeric(df[c],errors="raise")
        df["segment_id"]=0
        frames[sym]=df
    if len(set(count.values()))!=1:
        raise ValueError("SIX_SYMBOL_FUTURE_BATCH_INCOMPLETE")
    if not next(iter(count.values())):
        return {"state":"WAIT_ACTUAL_COMPLETE_B4_BAR_AFTER_SEED","per_symbol_future_bars":count,
           "seed_sha256":man["content_sha256"],"original_unit":"UNKNOWN",
           "b_source_pid":snap["producer_pid"],"actual_producer_live":True,
           "new_signal":False,"new_trades":0,"orders":0,"formal_active":False}
    bound=bind_frozen_context({30:frames},fit)[30]
    regimes={}
    for sym in SYMS:
        enriched=positive.enriched_segments(bound[sym])[-1]
        last=enriched.iloc[-1].to_dict()
        regime,regime_avail=positive._regime(last,None)
        if int(regime_avail)>asof_ms or int(last["available_ts_ms"])>asof_ms:
            raise ValueError("NATIVE_CONTEXT_FUTURE_LEAKAGE")
        regimes[sym]={"native_regime":regime,"regime_available_ts_ms":regime_avail,
                      "last_source_close_ts_ms":int(last["close_ts_ms"]),
                      "last_source_available_ts_ms":int(last["available_ts_ms"]),
                      "bars":len(enriched)}
    return {"state":"SOURCE_NATIVE_NEW_B4_BAR_FEATURE_READY_NOT_FORMAL_K117",
        "original_unit":"UNKNOWN","per_symbol_future_bars":count,"native_regimes":regimes,
        "b_source_pid":snap["producer_pid"],"b_state_sha256":snap["state_sha256"],
        "seed_sha256":man["content_sha256"],
        "historical_admissions":0,"new_signals":0,"new_trades":0,"orders":0,
        "next_open_quote_verified":False,"funding_source_verified":False,
        "formal_active":False}


def tests():
    prefix=[{"open_ts_ms":i*TF,"close_ts_ms":(i+1)*TF,"available_ts_ms":(i+1)*TF} for i in range(121)]
    new={"open_ts_ms":121*TF,"close_ts_ms":122*TF,"available_ts_ms":122*TF+20,
         "open":10,"high":13,"low":9,"close":12,
         "evidence_kind":"ACTUAL_PUBLIC_CLOSED_30M","formal_fresh_credit":False}
    assert len(only_future(prefix,[new],122*TF+30,121*TF+1))==1
    assert only_future(prefix,[],122*TF+30,121*TF+1)==[]
    assert only_future(prefix,[dict(new,open_ts_ms=120*TF,close_ts_ms=121*TF)],122*TF+30,121*TF+1)==[]
    bad=[
        (dict(new,open_ts_ms=122*TF,close_ts_ms=123*TF),122*TF+30),
        (dict(new,available_ts_ms=123*TF),122*TF+30),
        (dict(new,evidence_kind="MODELLED_OHLC"),122*TF+30),
        (dict(new,formal_fresh_credit=True),122*TF+30),
        (dict(new,high=9),122*TF+30)
    ]
    for b,clock in bad:
        try:only_future(prefix,[b],clock,121*TF+1)
        except ValueError:pass
        else:raise AssertionError("ACCEPTED_BAD_FUTURE_SOURCE")
    try:only_future(prefix,[new],121*TF,121*TF+1)
    except ValueError:pass
    else:raise AssertionError("ACCEPTED_CLOCK_BEFORE_SEED")
    print(json.dumps({"self_tests":9,"result":"PASS","market_api_requests":0,"orders":0}))


def main():
    a=argparse.ArgumentParser()
    a.add_argument("--seed-dir",type=Path)
    a.add_argument("--b-pointer",type=Path)
    a.add_argument("--checkout",type=Path)
    a.add_argument("--self-test",action="store_true")
    x=a.parse_args()
    if x.self_test:
        tests();return
    if not x.seed_dir or not x.b_pointer or not x.checkout:
        a.error("seed / pointer / pinned checkout required")
    print(json.dumps(check(x.seed_dir,x.b_pointer,x.checkout,int(time.time()*1000)),indent=2,sort_keys=True))


if __name__=="__main__":
    main()
