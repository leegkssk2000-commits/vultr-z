import pandas as pd
from engine.registry import register

@register("calendar_bias")
def calendar_bias(ohlc: pd.DataFrame=None, now=None, **kw):
    # 예: 월말·월초 편향
    if now is None:
        return {"bias": 0.0, "source": "calendar_bias"}
    d = now.day
    bias = 0.3 if d <= 3 or d >= 27 else 0.0
    return {"bias": float(bias), "source": "calendar_bias"}
