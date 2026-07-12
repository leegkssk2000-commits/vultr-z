from __future__ import annotations
from .generic_legendary_templates import legendary_trend_continuation as _impl

def strategy(df=None, state=None, risk_action='hold', config=None, market_context=None, **kwargs):
    return _impl('ema_ribbon_scalp_legendary', df=df, state=state, risk_action=risk_action, config=config, market_context=market_context, **kwargs)
