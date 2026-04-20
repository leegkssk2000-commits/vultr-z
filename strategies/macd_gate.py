import pandas as pd
from engine.registry import register

@register("macd_gate")
def macd_gate(ohlc: pd.DataFrame=None, fast=12, slow=26, sig=9, **kw):
    if ohlc is None or len(ohlc) < slow+sig+1:
        return {"block": False, "reason": "no_data", "source": "macd_gate"}
    c = ohlc["close"]
    ema_f = c.ewm(span=fast, adjust=False).mean()
    ema_s = c.ewm(span=slow, adjust=False).mean()
    macd = ema_f - ema_s
    signal = macd.ewm(span=sig, adjust=False).mean()
    hist = macd - signal
    block = hist.iloc[-1] * hist.iloc[-2] < 0 # 신호 교차 직후엔 진입 보류
    return {"block": bool(block), "source": "macd_gate"}
