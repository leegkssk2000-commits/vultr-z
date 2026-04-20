from datetime import datetime, timezone
def _utcnow(): return datetime.now(timezone.utc)
