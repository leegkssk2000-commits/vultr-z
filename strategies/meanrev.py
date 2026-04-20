import pandas as pd, numpy as np
from engine.registry import register

@register("meanrev")
def meanrev(ohlc: pd.DataFrame=None, win=14, z=1.0, **kw):
    if ohlc is None or len(ohlc) < win+1:
        return {"side": None, "confidence": 0.0, "source": "meanrev"}
    c = ohlc["close"]
    ma = c.rolling(win).mean()
    sd = c.rolling(win).std().replace(0, np.nan)
    zscore = (c - ma) / sd
    zlast = zscore.iloc[-1]
    side = "buy" if zlast < -z else ("sell" if zlast > z else None)
    conf = float(abs(zlast) / (z+1e-6)) if side else 0.0
    return {"side": side, "confidence": conf, "ttl": 300, "source": "meanrev"}