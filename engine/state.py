from datetime import datetime, timezone
FORCE_MODE = None # "paper" | "live" | None
PAPER_DAYS = 90

def _now(): return datetime.now(timezone.utc)
_started = _now()
_mode = "paper"

def load_state(): return _mode, _started
def update_mode(m): # 간단 상태 저장
    global _mode; _mode = m

def ok_performance(): return False # 기준 확정 전까지 False