import os
LIVE_MIN_TRADES = int(os.getenv("LIVE_MIN_TRADES", "60"))
LIVE_MIN_DAYS = int(os.getenv("LIVE_MIN_DAYS", "90"))
TRACKING_ERR_MAX = float(os.getenv("TRACKING_ERR_MAX", "0.006"))
SLIPPAGE_P95_MAX = float(os.getenv("SLIPPAGE_P95_MAX", "0.0035"))
MISSED_FILL_RATE_MAX= float(os.getenv("MISSED_FILL_RATE_MAX", "0.02"))

LOOP_LAG_P95_MAX = int(os.getenv("LOOP_LAG_P95_MAX","80")) # ms
QUEUE_DEPTH_MAX = int(os.getenv("QUEUE_DEPTH_MAX","200"))
DATA_STALE_SEC = int(os.getenv("DATA_STALE_SEC", "90"))
ON_STALE = os.getenv("ON_STALE", "halt") # halt|noop

FEE_BPS = int(os.getenv("FEE_BPS", "8"))
SPREAD_A = float(os.getenv("SPREAD_A", "0.6"))
SLIP_B_VOL = float(os.getenv("SLIP_B_VOL", "0.15"))
FUNDING_COST_RATIO = float(os.getenv("FUNDING_COST_RATIO", "0.08"))
