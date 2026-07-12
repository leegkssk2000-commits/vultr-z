from __future__ import annotations
from .generic_legendary_templates import legendary_liquidity_reclaim as _impl

def strategy(df=None, state=None, risk_action='hold', config=None, market_context=None, **kwargs):
    return _impl('pivot_reversal_legendary', df=df, state=state, risk_action=risk_action, config=config, market_context=market_context, **kwargs)
