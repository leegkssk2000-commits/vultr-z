import pandas as pd, numpy as np
from engine.registry import register

@register("breakout")
def breakout(ohlc: pd.DataFrame=None, win=20, **kw):
    if ohlc is None or len(ohlc) < win+1:
        return {"side": None, "confidence": 0.0, "source": "breakout"}
    hi = ohlc["high"].rolling(win).max().iloc[-2]
    lo = ohlc["low"].rolling(win).min().iloc[-2]
    px = ohlc["close"].iloc[-1]
    if px > hi: side, conf = "buy", float((px-hi)/max(1e-6, hi))
    elif px < lo: side, conf = "sell", float((lo-px)/max(1e-6, lo))
    else: side, conf = None, 0.0
    return {"side": side, "confidence": conf, "ttl": 300, "source": "breakout"}