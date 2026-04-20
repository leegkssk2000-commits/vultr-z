from engine.registry import register

@register("position_sizer")
def position_sizer(equity=100000.0, risk_per_trade=0.005, stop_distance=0.01, **kw):
    if stop_distance <= 0:
        return {"size": 0, "source": "position_sizer"}
    risk_amt = equity * risk_per_trade
    size = int(risk_amt / (stop_distance * 100)) # 종목 포인트당 100달러 가정 예시
    return {"size": max(size, 0), "source": "position_sizer"}