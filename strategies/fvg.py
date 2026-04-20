import numpy as np, pandas as pd
from engine.registry import register

@register("fvg")
def fvg(ohlc: pd.DataFrame=None, lookback=50, **kw):
    if ohlc is None or len(ohlc) < 3:
        return {"side": None, "confidence": 0.0, "source": "fvg"}
    o = ohlc["open"].values; h = ohlc["high"].values; l = ohlc["low"].values; c = ohlc["close"].values
    gap_up = l[-1] > h[-3]
    gap_dn = h[-1] < l[-3]
    side = "buy" if gap_up else ("sell" if gap_dn else None)
    conf = float(min(1.0, np.std(c[-lookback:]) / max(1e-6, np.std(c[-lookback//2:])))) if side else 0.0
    return {"side": side, "confidence": conf, "ttl": 300, "source": "fvg"}
