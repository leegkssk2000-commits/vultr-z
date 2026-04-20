import pandas as pd, numpy as np
from engine.registry import register

@register("atr_trail")
def atr_trail(ohlc: pd.DataFrame=None, n=14, mult=2.0, side="buy", **kw):
    if ohlc is None or len(ohlc) < n+1:
        return {"stop": None, "source": "atr_trail"}
    h,l,c = ohlc["high"], ohlc["low"], ohlc["close"]
    tr = pd.concat([(h-l), (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(n).mean().iloc[-1]
    px = c.iloc[-1]
    stop = px - mult*atr if side=="buy" else px + mult*atr
    return {"stop": float(stop), "atr": float(atr), "source": "atr_trail"}