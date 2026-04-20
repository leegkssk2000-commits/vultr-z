import pandas as pd, numpy as np
from engine.registry import register

@register("momentum")
def momentum(ohlc: pd.DataFrame=None, short=12, long=26, **kw):
    if ohlc is None or len(ohlc) < long+1:
        return {"side": None, "confidence": 0.0, "source": "momentum"}
    c = ohlc["close"]
    ema_s = c.ewm(span=short, adjust=False).mean()
    ema_l = c.ewm(span=long, adjust=False).mean()
    diff = ema_s - ema_l
    side = "buy" if diff.iloc[-1] > 0 else ("sell" if diff.iloc[-1] < 0 else None)
    conf = float(abs(diff.iloc[-1]) / (abs(c.iloc[-1]) + 1e-6)) if side else 0.0
    return {"side": side, "confidence": conf, "ttl": 300, "source": "momentum"}