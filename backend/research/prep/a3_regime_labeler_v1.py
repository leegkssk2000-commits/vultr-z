from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

REQUIRED = ("ts_utc","closed_bar_ts_utc","symbol","trend_strength","realized_vol_pct","spread_bps","depth_usdt","funding_8h_pct","oi_change_pct")

class RegimeInputError(ValueError):
    pass


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def label_regime(row: dict, *, now_utc: str, stale_after_ms: int = 7_200_000) -> dict:
    missing = [k for k in REQUIRED if row.get(k) is None]
    if missing:
        raise RegimeInputError("missing:" + ",".join(missing))
    now = _ts(now_utc)
    event = _ts(str(row["ts_utc"]))
    closed = _ts(str(row["closed_bar_ts_utc"]))
    if closed > event:
        raise RegimeInputError("future_closed_bar")
    age_ms = (now - event).total_seconds() * 1000
    if age_ms < 0 or age_ms > stale_after_ms:
        raise RegimeInputError("stale_or_future_event")

    trend = float(row["trend_strength"])
    vol = float(row["realized_vol_pct"])
    spread = float(row["spread_bps"])
    depth = float(row["depth_usdt"])
    funding = float(row["funding_8h_pct"])
    oi = float(row["oi_change_pct"])
    hour = int(row.get("session_utc_hour", event.hour))
    if not 0 <= hour <= 23:
        raise RegimeInputError("bad_session_hour")

    return {
        "trend_state": "TREND" if abs(trend) >= 0.35 else "RANGE",
        "vol_state": "HIGH_VOL" if vol >= 1.0 else "LOW_VOL",
        "liquidity_state": "THIN" if (spread > 8.0 or depth < 100_000.0) else "NORMAL",
        "session_state": "ASIA" if hour <= 7 else ("EU" if hour <= 15 else "US"),
        "funding_oi_state": "CROWDED" if (abs(funding) >= 0.03 and abs(oi) >= 3.0) else "NEUTRAL",
        "symbol": str(row["symbol"]),
        "source_boundary": str(row["closed_bar_ts_utc"]),
        "outcome_fields_used": [],
    }


def coverage_manifest(rows: list[dict], *, now_utc: str) -> dict:
    labels = [label_regime(r, now_utc=now_utc) for r in rows]
    out = {k: {} for k in ("trend_state","vol_state","liquidity_state","session_state","funding_oi_state")}
    for x in labels:
        for k in out:
            out[k][x[k]] = out[k].get(x[k], 0) + 1
    return {"row_count": len(labels), "coverage": out, "outcome_metrics_inspected": False}
