from config.settings import DATA_STALE_SEC, ON_STALE
def precheck(df=None, data_stale_sec=None, min_rows=120):
    if df is None or len(df) < min_rows:
        return {"action":"noop","why":"warmup"}
    if data_stale_sec and data_stale_sec > DATA_STALE_SEC:
        act = "halt" if ON_STALE=="halt" else "noop"
        return {"action":act,"why":"stale"}
    return None