import pandas as pd, numpy as np
from engine.registry import register

@register("vol_filter")
def vol_filter(ohlc: pd.DataFrame=None, win=20, min_vol=0.003, **kw):
    if ohlc is None or len(ohlc) < win+1:
        return {"pass": False, "reason": "no_data", "source": "vol_filter"}
    rng = (ohlc["high"] - ohlc["low"]) / ohlc["close"].shift(1)
    vol = rng.rolling(win).mean().iloc[-1]
    ok = float(vol) >= float(min_vol)
    return {"pass": ok, "vol": float(vol), "source": "vol_filter"}