#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import math
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Mapping

KLINE_API = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
BOUNDARY = "2026-08-16T18:45:01Z"
COST_BPS = 14.0
SYMBOLS = ("BTC-USDT", "ETH-USDT")
PRICE_SOURCES = {"ohlcv", "volume"}
INTERVAL_MAP = {"5m":"5m","15m":"15m","30m":"30m","1h":"1h","4h":"4h","1d":"1d"}


def _cutoff_ms() -> int:
    return int(datetime.fromisoformat(BOUNDARY.replace("Z", "+00:00")).timestamp() * 1000)


def _req(params: Mapping[str, Any]) -> Any:
    url = KLINE_API + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        x = json.loads(r.read().decode())
    if isinstance(x, dict) and x.get("code") not in (None, 0):
        raise RuntimeError(f"BINGX:{x.get('code')}:{x.get('msg')}")
    return x


def _decode_rows(x: Any) -> list[dict[str, float]]:
    rows = x.get("data", x if isinstance(x, list) else []) if isinstance(x, (dict, list)) else []
    out: list[dict[str, float]] = []
    for r in rows:
        try:
            if isinstance(r, dict):
                ts = int(r.get("time") or r.get("openTime") or r.get("timestamp"))
                out.append({"ts":ts,"open":float(r["open"]),"high":float(r["high"]),"low":float(r["low"]),"close":float(r["close"]),"volume":float(r.get("volume") or r.get("vol") or 0.0)})
            else:
                out.append({"ts":int(r[0]),"open":float(r[1]),"high":float(r[2]),"low":float(r[3]),"close":float(r[4]),"volume":float(r[5] if len(r)>5 else 0.0)})
        except Exception:
            continue
    return out


def bars(symbol: str, interval: str) -> list[dict[str, float]]:
    cutoff = _cutoff_ms()
    all_rows: dict[int, dict[str, float]] = {}
    end = cutoff - 1
    for _ in range(3):
        x = _req({"symbol":symbol,"interval":INTERVAL_MAP[interval],"limit":1000,"endTime":end})
        page = sorted(_decode_rows(x), key=lambda z:z["ts"])
        page = [r for r in page if r["ts"] < cutoff]
        if not page:
            break
        for r in page: all_rows[int(r["ts"])] = r
        oldest = int(page[0]["ts"])
        if oldest >= end: break
        end = oldest - 1
        if len(page) < 900: break
    return [all_rows[k] for k in sorted(all_rows)]


class Expr:
    ALLOWED_BIN = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)
    ALLOWED_CMP = (ast.Gt, ast.GtE, ast.Lt, ast.LtE, ast.Eq, ast.NotEq)
    ALLOWED_BOOL = (ast.And, ast.Or)
    ALLOWED_UNARY = (ast.USub, ast.UAdd, ast.Not)
    FUNCS = {"abs","min","max","sma","ema","std","lag","ret","roc","atr","vwap","zscore","highest","lowest","percentile","pct_rank","vol_ratio","range_pct","body_pct","upper_wick_pct","lower_wick_pct","breakout_dist","hour","dow"}
    SERIES_FUNCS = ("sma","ema","std","lag","zscore","highest","lowest","percentile","pct_rank","breakout_dist")

    def __init__(self, rows: list[dict[str, float]], features: dict[str, list[float | None]]):
        self.rows = rows; self.features = features; self.i = 0

    @staticmethod
    def normalize(s: str) -> str:
        s = str(s or "").strip()
        replacements = {
            "rolling_mean":"sma","rolling_sma":"sma","rolling_std":"std","rolling_max":"highest","rolling_min":"lowest","returns":"ret",
            "EMA":"ema","SMA":"sma","STDEV":"std","STD":"std","LOWEST":"lowest","HIGHEST":"highest","VWAP":"vwap","ATR":"atr","ZSCORE":"zscore","LAG":"lag","RET":"ret","ROC":"roc",
            "PERCENTILE":"percentile","PCT_RANK":"pct_rank","VOL_RATIO":"vol_ratio","RANGE_PCT":"range_pct","BODY_PCT":"body_pct",
            "AND":"and","OR":"or","&&":"and","||":"or",
        }
        for a,b in replacements.items(): s=s.replace(a,b)
        return s.replace("^","**")

    def _normalized(self, s: str) -> str:
        s = self.normalize(s)
        names = ["open","high","low","close","volume",*self.features.keys()]
        if not names:
            return s
        alternation = "|".join(sorted((re.escape(x) for x in names), key=len, reverse=True))
        for fn in self.SERIES_FUNCS:
            s = re.sub(
                rf"\b{fn}\(\s*({alternation})\s*,",
                lambda m, fn=fn: f"{fn}({m.group(1)!r},",
                s,
            )
        return s

    def validate(self, s: str) -> ast.Expression:
        tree=ast.parse(self._normalized(s),mode="eval")
        allowed_names={"open","high","low","close","volume",*self.features.keys(),*self.FUNCS}
        for n in ast.walk(tree):
            if isinstance(n,ast.Name):
                if n.id not in allowed_names: raise ValueError(f"UNKNOWN_NAME:{n.id}")
                continue
            if isinstance(n,ast.Expression|ast.Load|ast.Constant): continue
            if isinstance(n,ast.BinOp) and isinstance(n.op,self.ALLOWED_BIN): continue
            if isinstance(n,ast.BoolOp) and isinstance(n.op,self.ALLOWED_BOOL): continue
            if isinstance(n,ast.UnaryOp) and isinstance(n.op,self.ALLOWED_UNARY): continue
            if isinstance(n,ast.Compare) and all(isinstance(op,self.ALLOWED_CMP) for op in n.ops): continue
            if isinstance(n,ast.IfExp): continue
            if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in self.FUNCS: continue
            if isinstance(n,self.ALLOWED_BIN+self.ALLOWED_BOOL+self.ALLOWED_UNARY+self.ALLOWED_CMP): continue
            raise ValueError(f"UNSUPPORTED_AST:{type(n).__name__}")
        return tree

    def _series_value(self,name:str,j:int)->float|None:
        if j<0 or j>=len(self.rows): return None
        if name in {"open","high","low","close","volume"}: return float(self.rows[j][name])
        arr=self.features.get(name); return arr[j] if arr and j<len(arr) else None

    def _window(self,name:str,n:int)->list[float]:
        vals=[]
        for j in range(max(0,self.i-n+1),self.i+1):
            v=self._series_value(name,j)
            if isinstance(v,(int,float)) and math.isfinite(float(v)): vals.append(float(v))
        return vals

    def env(self)->dict[str,Any]:
        i=self.i
        env:dict[str,Any]={k:self._series_value(k,i) for k in {"open","high","low","close","volume",*self.features.keys()}}
        def _name(arg:Any)->str:return str(arg)
        def lag(name:Any,n:Any=1):return self._series_value(_name(name),i-int(n))
        def sma(name:Any,n:Any):
            x=self._window(_name(name),int(n)); return sum(x)/len(x) if x else None
        def ema(name:Any,n:Any):
            n=max(1,int(n)); vals=[]
            for j in range(max(0,i-max(n*4,n)+1),i+1):
                v=self._series_value(_name(name),j)
                if isinstance(v,(int,float)) and math.isfinite(float(v)): vals.append(float(v))
            if not vals:return None
            a=2.0/(n+1.0); out=vals[0]
            for v in vals[1:]: out=a*v+(1-a)*out
            return out
        def std(name:Any,n:Any):
            x=self._window(_name(name),int(n))
            if len(x)<2:return 0.0
            m=sum(x)/len(x); return math.sqrt(sum((v-m)**2 for v in x)/len(x))
        def ret(n:Any=1):
            p=self._series_value("close",i-int(n)); c=self._series_value("close",i); return None if not p else c/p-1.0
        def roc(n:Any=1): return ret(n)
        def atr(n:Any=14):
            vals=[]
            for j in range(max(1,i-int(n)+1),i+1):
                h=self.rows[j]["high"]; l=self.rows[j]["low"]; pc=self.rows[j-1]["close"]; vals.append(max(h-l,abs(h-pc),abs(l-pc)))
            return sum(vals)/len(vals) if vals else None
        def vwap(n:Any=96):
            start=max(0,i-int(n)+1); num=den=0.0
            for j in range(start,i+1):
                tp=(self.rows[j]["high"]+self.rows[j]["low"]+self.rows[j]["close"])/3.0; vol=self.rows[j]["volume"]; num+=tp*vol; den+=vol
            return num/den if den else self.rows[i]["close"]
        def zscore(name:Any,n:Any):
            x=self._window(_name(name),int(n)); cur=self._series_value(_name(name),i)
            if not x or cur is None:return None
            m=sum(x)/len(x); sd=(sum((v-m)**2 for v in x)/len(x))**0.5; return 0.0 if sd==0 else (cur-m)/sd
        def highest(name:Any,n:Any):
            x=self._window(_name(name),int(n)); return max(x) if x else None
        def lowest(name:Any,n:Any):
            x=self._window(_name(name),int(n)); return min(x) if x else None
        def percentile(name:Any,n:Any,p:Any):
            x=sorted(self._window(_name(name),int(n)))
            if not x:return None
            q=max(0.0,min(100.0,float(p)))/100.0; idx=q*(len(x)-1); lo=int(math.floor(idx)); hi=int(math.ceil(idx))
            return x[lo] if lo==hi else x[lo]+(x[hi]-x[lo])*(idx-lo)
        def pct_rank(name:Any,n:Any):
            x=self._window(_name(name),int(n)); cur=self._series_value(_name(name),i)
            if not x or cur is None:return None
            return sum(1 for v in x if v<=cur)/len(x)
        def vol_ratio(n:Any=20):
            m=sma("volume",n); v=self._series_value("volume",i); return None if not m else v/m
        def range_pct():
            c=self.rows[i]["close"]; return 0.0 if not c else (self.rows[i]["high"]-self.rows[i]["low"])/c
        def body_pct():
            c=self.rows[i]["close"]; return 0.0 if not c else abs(self.rows[i]["close"]-self.rows[i]["open"])/c
        def upper_wick_pct():
            c=self.rows[i]["close"]; return 0.0 if not c else (self.rows[i]["high"]-max(self.rows[i]["open"],self.rows[i]["close"]))/c
        def lower_wick_pct():
            c=self.rows[i]["close"]; return 0.0 if not c else (min(self.rows[i]["open"],self.rows[i]["close"])-self.rows[i]["low"])/c
        def breakout_dist(name:Any="high",n:Any=20):
            cur=self._series_value("close",i); ref=(highest if _name(name)=="high" else lowest)(_name(name),int(n))
            return None if not cur or ref is None else cur/ref-1.0
        def hour(): return datetime.fromtimestamp(self.rows[i]["ts"]/1000,tz=timezone.utc).hour
        def dow(): return datetime.fromtimestamp(self.rows[i]["ts"]/1000,tz=timezone.utc).weekday()
        env.update({"lag":lag,"sma":sma,"ema":ema,"std":std,"ret":ret,"roc":roc,"atr":atr,"vwap":vwap,"zscore":zscore,"highest":highest,"lowest":lowest,"percentile":percentile,"pct_rank":pct_rank,"vol_ratio":vol_ratio,"range_pct":range_pct,"body_pct":body_pct,"upper_wick_pct":upper_wick_pct,"lower_wick_pct":lower_wick_pct,"breakout_dist":breakout_dist,"hour":hour,"dow":dow,"abs":abs,"min":min,"max":max})
        return env

    def eval(self,s:str,i:int)->Any:
        self.i=i; tree=self.validate(s); return eval(compile(tree,"<expr>","eval"),{"__builtins__":{}},self.env())


def _feature_formula(s:str)->str:
    s=Expr.normalize(s)
    if "==" not in s and "!=" not in s and ">=" not in s and "<=" not in s: s=re.sub(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*","",s)
    for fn in ("sma","ema","std","lag","zscore","highest","lowest","percentile","pct_rank"):
        s=re.sub(rf"\b{fn}\(\s*(open|high|low|close|volume|[A-Za-z_][A-Za-z0-9_]*)\s*,",rf"{fn}('\1',",s)
    return s


def _side(rule:str,engine:Expr,i:int)->str|None:
    text=str(rule or "").strip().lower()
    if text in {"long","long_only","always_long"}:return "long"
    if text in {"short","short_only","always_short"}:return "short"
    m=re.fullmatch(r"long\s+if\s+(.+)\s+else\s+short",text)
    if m:return "long" if bool(engine.eval(m.group(1),i)) else "short"
    m=re.fullmatch(r"short\s+if\s+(.+)\s+else\s+long",text)
    if m:return "short" if bool(engine.eval(m.group(1),i)) else "long"
    return None


def _validate_side(rule:str,engine:Expr)->None:
    text=str(rule or "").strip().lower()
    if text in {"long","long_only","always_long","short","short_only","always_short"}:return
    for pat in (r"long\s+if\s+(.+)\s+else\s+short",r"short\s+if\s+(.+)\s+else\s+long"):
        m=re.fullmatch(pat,text)
        if m:engine.validate(m.group(1));return
    raise ValueError("SIDE_RULE_UNSUPPORTED")


def _pf(xs:list[float])->float|None:
    gp=sum(x for x in xs if x>0); gl=-sum(x for x in xs if x<0); return None if gl<=0 else gp/gl

def _payoff(xs:list[float])->float|None:
    w=[x for x in xs if x>0]; l=[-x for x in xs if x<0]; return None if not w or not l else (sum(w)/len(w))/(sum(l)/len(l))

def _dd(xs:list[float])->float:
    eq=peak=mx=0.0
    for x in xs: eq+=x; peak=max(peak,eq); mx=max(mx,peak-eq)
    return mx


def evaluate_development_events(
    rows, signals, *, split_start_ms, split_end_ms, interval_ms,
    hold_bars, entry_delay_bars=0, side="long",
):
    """Model fixed-horizon events from an already isolated development partition.

    A signal is observable at its bar close. Entry is the following bar open,
    plus an explicitly supplied whole-bar delay; exit is the close of the last
    of ``hold_bars`` held bars. These prices are modelled fills, never evidence
    of exchange executions. Exit must precede the partition's exclusive end.

    The shared evaluator's no-overlap convention is retained: a signal on or
    before an accepted trade's exit bar is excluded, including delayed-entry
    waiting bars. Every supplied input is validated before calculating any
    outcome. This helper performs no acquisition, costs, gate decisions,
    persistence, or authority changes; existing evaluator entrypoints retain
    their behavior.
    """
    integer_inputs = {
        "split_start_ms": split_start_ms, "split_end_ms": split_end_ms,
        "interval_ms": interval_ms, "hold_bars": hold_bars,
        "entry_delay_bars": entry_delay_bars,
    }
    if any(type(value) is not int for value in integer_inputs.values()):
        raise RuntimeError("DEVELOPMENT_INTEGER_INPUT_REQUIRED")
    if interval_ms != 14_400_000:
        raise RuntimeError("DEVELOPMENT_FOUR_HOUR_INTERVAL_REQUIRED")
    if split_start_ms < 0 or split_end_ms <= split_start_ms:
        raise RuntimeError("DEVELOPMENT_SPLIT_BOUNDS_INVALID")
    if split_start_ms % interval_ms or split_end_ms % interval_ms:
        raise RuntimeError("DEVELOPMENT_SPLIT_CLOCK_ALIGNMENT")
    if hold_bars <= 0 or entry_delay_bars < 0:
        raise RuntimeError("DEVELOPMENT_HOLD_OR_DELAY_INVALID")
    if side not in {"long", "short"}:
        raise RuntimeError("DEVELOPMENT_SIDE_UNSUPPORTED")
    if not isinstance(rows, (list, tuple)) or not rows:
        raise RuntimeError("DEVELOPMENT_ROWS_REQUIRED")
    if not isinstance(signals, (list, tuple)):
        raise RuntimeError("DEVELOPMENT_SIGNAL_SEQUENCE_REQUIRED")

    previous_open = None
    for row in rows:
        if not isinstance(row, Mapping):
            raise RuntimeError("DEVELOPMENT_BAR_OBJECT_REQUIRED")
        opened, closed = row.get("bar_open_ts"), row.get("bar_close_ts")
        if type(opened) is not int or type(closed) is not int:
            raise RuntimeError("DEVELOPMENT_BAR_INTEGER_CLOCK_REQUIRED")
        if opened % interval_ms or closed != opened + interval_ms:
            raise RuntimeError("DEVELOPMENT_BAR_CLOCK_INVALID")
        if opened < split_start_ms or closed > split_end_ms:
            raise RuntimeError("DEVELOPMENT_PARTITION_ROW_FORBIDDEN")
        if previous_open is not None and opened != previous_open + interval_ms:
            raise RuntimeError("DEVELOPMENT_GAP_DUPLICATE_OR_ORDER")
        previous_open = opened
        for name in ("open", "high", "low", "close", "volume"):
            value = row.get(name)
            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not math.isfinite(value)):
                raise RuntimeError("DEVELOPMENT_NONFINITE_BAR_VALUE:" + name)
            if value < 0 or (name != "volume" and value == 0):
                raise RuntimeError("DEVELOPMENT_BAR_VALUE_RANGE:" + name)
        if not (row["low"] <= min(row["open"], row["close"])
                <= max(row["open"], row["close"]) <= row["high"]):
            raise RuntimeError("DEVELOPMENT_OHLC_BOUNDS_INVALID")

    previous_signal = -1
    for index in signals:
        if type(index) is not int or not 0 <= index < len(rows):
            raise RuntimeError("DEVELOPMENT_SIGNAL_INDEX_INVALID")
        if index <= previous_signal:
            raise RuntimeError("DEVELOPMENT_SIGNAL_DUPLICATE_OR_ORDER")
        previous_signal = index

    trades, exclusions = [], []
    last_exit_index = -1
    sign = 1.0 if side == "long" else -1.0
    for index in signals:
        identity = {"signal_index": index, "signal_ts": rows[index]["bar_close_ts"]}
        if index <= last_exit_index:
            exclusions.append({**identity, "reason": "SIGNAL_DURING_OPEN"})
            continue
        entry_index = index + 1 + entry_delay_bars
        exit_index = entry_index + hold_bars - 1
        if (exit_index >= len(rows)
                or rows[exit_index]["bar_close_ts"] >= split_end_ms):
            exclusions.append({**identity, "reason": "SPLIT_END_INCOMPLETE_HOLD"})
            continue
        entry = float(rows[entry_index]["open"])
        exit_price = float(rows[exit_index]["close"])
        path = rows[entry_index:exit_index + 1]
        high = max(float(row["high"]) for row in path)
        low = min(float(row["low"]) for row in path)
        favorable = (high / entry - 1.0) if side == "long" else (1.0 - low / entry)
        adverse = (low / entry - 1.0) if side == "long" else (1.0 - high / entry)
        entry_ts = rows[entry_index]["bar_open_ts"]
        exit_ts = rows[exit_index]["bar_close_ts"]
        trades.append({
            **identity, "entry_index": entry_index, "exit_index": exit_index,
            "entry_ts": entry_ts, "exit_ts": exit_ts, "side": side,
            "entry_price": entry, "exit_price": exit_price,
            "gross_bps": sign * (exit_price / entry - 1.0) * 10_000.0,
            "mfe_bps": max(0.0, favorable * 10_000.0),
            "mae_bps": min(0.0, adverse * 10_000.0),
            "hold_ms": exit_ts - entry_ts,
        })
        last_exit_index = exit_index
    return {"trades": trades, "exclusions": exclusions}


def evaluate_candidate(candidate:Mapping[str,Any])->dict[str,Any]:
    cid=str(candidate.get("candidate_id") or ""); req=set(candidate.get("required_sources") or [])
    if not req or not req.issubset(PRICE_SOURCES):return {"candidate_id":cid,"state":"SKIP_HISTORY_SOURCE_NOT_READY","required_sources":sorted(req),"economic_pass":False}
    spec=candidate.get("executable_spec")
    if not isinstance(spec,Mapping):return {"candidate_id":cid,"state":"REJECT_SPEC_MISSING","economic_pass":False}
    interval=str(spec.get("bar_interval") or "")
    if interval not in INTERVAL_MAP:return {"candidate_id":cid,"state":"REJECT_INTERVAL","economic_pass":False}
    entry=str(spec.get("entry_rule") or ""); side_rule=str(spec.get("side_rule") or ""); exit_rule=str(spec.get("exit_rule") or "time_stop")
    try:hold=int(spec.get("max_hold_bars") or 0)
    except Exception:hold=0
    if not 1<=hold<=720:return {"candidate_id":cid,"state":"REJECT_HOLD","economic_pass":False}
    alltr=[]; source={}; first_ts=None; last_ts=None
    try:
        for symbol in SYMBOLS:
            rs=bars(symbol,interval); source[symbol]={"bars":len(rs)}
            if rs:
                first_ts=min(first_ts or int(rs[0]["ts"]),int(rs[0]["ts"])); last_ts=max(last_ts or int(rs[-1]["ts"]),int(rs[-1]["ts"]))
            features:dict[str,list[float|None]]={}; eng=Expr(rs,features)
            for f in spec.get("features") or []:
                name=str(f.get("name") or "").strip(); formula=_feature_formula(str(f.get("formula") or ""))
                if not name or not formula:raise ValueError("FEATURE_EMPTY")
                eng.validate(formula); arr=[]; features[name]=arr
                for i in range(len(rs)):
                    try:
                        v=eng.eval(formula,i); arr.append(float(v) if isinstance(v,(int,float)) and math.isfinite(float(v)) else None)
                    except (TypeError,ZeroDivisionError,ValueError):arr.append(None)
            eng=Expr(rs,features); eng.validate(entry); _validate_side(side_rule,eng)
            time_only=exit_rule.strip().lower() in {"time_stop","time stop","max_hold","max_hold_bars"}
            if not time_only:eng.validate(exit_rule)
            i=max(30,1); entry_eval_errors=0
            while i<len(rs)-1:
                try:fire=bool(eng.eval(entry,i))
                except (TypeError,ZeroDivisionError,ValueError):entry_eval_errors+=1; fire=False
                if not fire:i+=1;continue
                side=_side(side_rule,eng,i)
                if side not in {"long","short"}:raise ValueError("SIDE_RULE_UNSUPPORTED")
                entry_i=i+1; entry_px=rs[entry_i]["open"]; exit_i=min(entry_i+hold-1,len(rs)-1)
                if not time_only:
                    for j in range(entry_i,min(entry_i+hold,len(rs))):
                        try:
                            if bool(eng.eval(exit_rule,j)):exit_i=j;break
                        except (TypeError,ZeroDivisionError,ValueError):raise ValueError("EXIT_RULE_UNSUPPORTED")
                exit_px=rs[exit_i]["close"]; gross=(exit_px/entry_px-1.0)*10000*(1 if side=="long" else -1); net=gross-COST_BPS
                alltr.append({"symbol":symbol,"side":side,"gross_bps":gross,"net_bps":net,"entry_ts":int(rs[entry_i]["ts"]),"exit_ts":int(rs[exit_i]["ts"])})
                i=max(i+1,exit_i+1)
            if entry_eval_errors>max(50,len(rs)//2):raise ValueError(f"ENTRY_RUNTIME_ERRORS:{entry_eval_errors}")
    except Exception as exc:
        return {"candidate_id":cid,"state":"REJECT_UNEXECUTABLE_SPEC","error":f"{type(exc).__name__}:{str(exc)[:240]}","economic_pass":False}
    net=[x["net_bps"] for x in alltr]; gross=[x["gross_bps"] for x in alltr]
    days=max(1e-9,((last_ts or _cutoff_ms())-(first_ts or _cutoff_ms()))/86_400_000)
    metrics={"trades":len(net),"gross_expectancy_bps":sum(gross)/len(gross) if gross else None,"net_expectancy_bps":sum(net)/len(net) if net else None,"net_pnl_bps":sum(net),"profit_factor":_pf(net),"payoff":_payoff(net),"win_rate":sum(1 for x in net if x>0)/len(net) if net else None,"drawdown_bps":_dd(net),"cost_bps_per_trade":COST_BPS,"events_per_day":len(net)/days,"net_bps_per_calendar_day":sum(net)/days,"development_days":days}
    base={"candidate_id":cid,"strategy_id":candidate.get("strategy_id"),"provider":candidate.get("provider"),"metrics":metrics,"source_summary":source,"development_only":True,"prospective":False,"uses_data_strictly_before_gen1_boundary":True,"boundary":BOUNDARY}
    if not net:return {**base,"state":"FAIL_INSUFFICIENT_EVENTS","economic_pass":False}
    passed=bool(len(net)>=12 and (metrics["net_expectancy_bps"] or 0)>0 and (metrics["profit_factor"] or 0)>1.0 and (metrics["net_bps_per_calendar_day"] or 0)>0)
    return {**base,"state":"PASS_DEVELOPMENT_ECONOMICS" if passed else "FAIL_DEVELOPMENT_ECONOMICS","economic_pass":passed}


def evaluate_queue(queue:list[Mapping[str,Any]])->dict[str,Any]:
    rows=[evaluate_candidate(c) for c in queue]; passed=[x for x in rows if x.get("economic_pass")]; failed=[x for x in rows if x.get("state")=="FAIL_DEVELOPMENT_ECONOMICS"]; insufficient=[x for x in rows if x.get("state")=="FAIL_INSUFFICIENT_EVENTS"]; skipped=[x for x in rows if str(x.get("state") or "").startswith("SKIP_")]; rejected=[x for x in rows if str(x.get("state") or "").startswith("REJECT_")]
    return {"schema_version":"zel.a1_gen2_generic_dev_econ.v1","development_only":True,"prospective":False,"cost_bps_per_trade":COST_BPS,"boundary":BOUNDARY,"candidate_count":len(rows),"economic_pass_count":len(passed),"economic_fail_count":len(failed),"insufficient_event_count":len(insufficient),"source_skip_count":len(skipped),"spec_reject_count":len(rejected),"passes":passed,"rows":rows,"selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED","exchange_order_submitted":False,"protected_mutations":0}
