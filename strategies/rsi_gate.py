import pandas as pd, numpy as np
from engine.registry import register

def _rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = -d.clip(upper=0).rolling(n).mean()
    rs = up / (dn + 1e-9)
    return 100 - (100 / (1 + rs))

@register("rsi_gate")
def rsi_gate(ohlc: pd.DataFrame=None, n=14, lo=30, hi=70, **kw):
    if ohlc is None or len(ohlc) < n+1:
        return {"block": False, "reason": "no_data", "source": "rsi_gate"}
    r = _rsi(ohlc["close"], n=n).iloc[-1]
    block = r > hi or r < lo # 과매수/과매도 시 진입 제한
    return {"block": bool(block), "rsi": float(r), "source": "rsi_gate"}