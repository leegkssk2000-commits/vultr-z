from config.settings import FEE_BPS, SPREAD_A, SLIP_B_VOL, FUNDING_COST_RATIO
def est_slippage(spread, vol): # spread in price units, vol in %
    return SPREAD_A*spread + SLIP_B_VOL*vol
def fee_cost(notional): return notional * (FEE_BPS/10000.0)
def funding_cost(notional, hours): return notional * FUNDING_COST_RATIO * (hours/24.0)