# ZOPS_DUAL_LEDGER_RECONCILIATION_V1
# Immutable dual ledger for Real/Paper/Shadow + reconciliation gate.
# Safety contract: advisory-only, no exchange mutation, OS final approval required.
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query

try:
    import fcntl  # type: ignore
except Exception:  # pragma: no cover
    fcntl = None

router = APIRouter(prefix="/api/ledger", tags=["zops-ledger"])

ROOT = Path(os.environ.get("ZOPS_ROOT", "/home/z/z"))
DATA_DIR = Path(os.environ.get("ZOPS_LEDGER_DATA_DIR", str(ROOT / "data" / "ledger")))
EVENTS_FILE = DATA_DIR / "events.jsonl"
RECON_FILE = DATA_DIR / "reconciliation.jsonl"
SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"
ALIMI_OUTBOX = Path(os.environ.get("ZOPS_ALIMI_OUTBOX", str(ROOT / "data" / "alimi" / "outbox.jsonl")))
CONTRACT_VERSION = "dual_ledger_reconciliation_v1"
ALLOWED_MODES = {"real", "paper", "shadow"}
ALLOWED_ACTIONS = {"reduce25", "partial30", "hold", "stop", "route_change", "rollback", "block"}

PNL_USDT_LIMIT = float(os.environ.get("ZOPS_LEDGER_PNL_USDT_LIMIT", "5"))
PNL_PCT_LIMIT = float(os.environ.get("ZOPS_LEDGER_PNL_PCT_LIMIT", "0.25"))
BALANCE_USDT_LIMIT = float(os.environ.get("ZOPS_LEDGER_BALANCE_USDT_LIMIT", "5"))


def _ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ALIMI_OUTBOX.parent.mkdir(parents=True, exist_ok=True)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _safe(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_safe(v) for v in obj]
    return str(obj)


def _canonical(obj: Any) -> str:
    return json.dumps(_safe(obj), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


def _line_append(path: Path, obj: Dict[str, Any]) -> None:
    _ensure()
    line = json.dumps(_safe(obj), ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        if fcntl:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            except Exception:
                pass
        fh.write(line)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except Exception:
            pass
        if fcntl:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


def _read_jsonl(path: Path, limit: int = 5000) -> List[Dict[str, Any]]:
    _ensure()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]
    out: List[Dict[str, Any]] = []
    for ln in lines:
        if not ln.strip():
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            out.append({"event": "corrupt_line", "raw": ln[:500]})
    return out


def _head_hash() -> str:
    events = _read_jsonl(EVENTS_FILE, limit=1)
    if not events:
        return "GENESIS"
    return str(events[-1].get("event_hash") or "GENESIS")


def _append_ledger_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(payload.get("mode") or "paper").lower()
    if mode not in ALLOWED_MODES:
        raise HTTPException(status_code=400, detail={"ok": False, "error": "invalid_mode", "allowed": sorted(ALLOWED_MODES)})

    action = str(payload.get("action") or payload.get("allowed_action") or "hold")
    if action not in ALLOWED_ACTIONS:
        action = "hold"

    prev_hash = _head_hash()
    base = {
        "event": "ledger_event",
        "contract_version": CONTRACT_VERSION,
        "ts_ms": int(payload.get("ts_ms") or _now_ms()),
        "mode": mode,
        "account": str(payload.get("account") or payload.get("exchange") or "default"),
        "exchange": str(payload.get("exchange") or "internal"),
        "symbol": str(payload.get("symbol") or "NA").upper(),
        "strategy": str(payload.get("strategy") or payload.get("team") or "NA"),
        "team": str(payload.get("team") or payload.get("strategy") or "NA"),
        "decision_id": str(payload.get("decision_id") or "NA"),
        "order_id": str(payload.get("order_id") or "NA"),
        "receipt_id": str(payload.get("receipt_id") or payload.get("zlice_receipt_id") or "NA"),
        "side": str(payload.get("side") or "NA"),
        "action": action,
        "qty": _num(payload.get("qty")),
        "price": _num(payload.get("price")),
        "fee": _num(payload.get("fee")),
        "realized_pnl": _num(payload.get("realized_pnl") if "realized_pnl" in payload else payload.get("pnl")),
        "unrealized_pnl": _num(payload.get("unrealized_pnl")),
        "balance_delta": _num(payload.get("balance_delta")),
        "equity": _num(payload.get("equity")),
        "balance": _num(payload.get("balance")),
        "source": str(payload.get("source") or "manual"),
        "source_hash": str(payload.get("source_hash") or _sha256(payload.get("source_payload") or payload)),
        "zlice_proof_hash": str(payload.get("zlice_proof_hash") or payload.get("proof_hash") or "NA"),
        "authority": "advisory_only",
        "order_mutation": "blocked",
        "os_final_approval_required": True,
        "prev_hash": prev_hash,
    }
    event_hash = hashlib.sha256((prev_hash + _canonical(base)).encode("utf-8")).hexdigest()
    base["event_id"] = "led_" + event_hash[:24]
    base["event_hash"] = event_hash
    base["immutable_append_only"] = True
    _line_append(EVENTS_FILE, base)
    SNAPSHOT_FILE.write_text(json.dumps(_ledger_summary(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return base


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except Exception:
        return None


def _sum(vals: List[Optional[float]]) -> float:
    return float(sum(v for v in vals if isinstance(v, (int, float))))


def _ledger_summary(limit: int = 10000) -> Dict[str, Any]:
    events = [e for e in _read_jsonl(EVENTS_FILE, limit=limit) if e.get("event") == "ledger_event"]
    by_mode: Dict[str, Dict[str, Any]] = {}
    for mode in sorted(ALLOWED_MODES):
        evs = [e for e in events if e.get("mode") == mode]
        symbols = sorted({str(e.get("symbol")) for e in evs if e.get("symbol")})
        strategies = sorted({str(e.get("strategy")) for e in evs if e.get("strategy")})
        latest = evs[-1] if evs else None
        by_mode[mode] = {
            "events": len(evs),
            "symbols": symbols[:50],
            "strategies": strategies[:50],
            "realized_pnl": _sum([_num(e.get("realized_pnl")) for e in evs]),
            "fees": _sum([_num(e.get("fee")) for e in evs]),
            "balance_delta": _sum([_num(e.get("balance_delta")) for e in evs]),
            "latest_equity": _num(latest.get("equity")) if latest else None,
            "latest_balance": _num(latest.get("balance")) if latest else None,
            "latest_event_id": latest.get("event_id") if latest else None,
            "latest_decision_id": latest.get("decision_id") if latest else None,
        }
    return {
        "ok": True,
        "contract_version": CONTRACT_VERSION,
        "authority": "advisory_only",
        "order_mutation": "blocked",
        "os_final_approval_required": True,
        "counts": {"events": len(events), "hash_head": _head_hash()},
        "modes": by_mode,
        "thresholds": {
            "pnl_usdt_limit": PNL_USDT_LIMIT,
            "pnl_pct_limit": PNL_PCT_LIMIT,
            "balance_usdt_limit": BALANCE_USDT_LIMIT,
        },
    }


def _latest_recon() -> Optional[Dict[str, Any]]:
    rows = _read_jsonl(RECON_FILE, limit=1)
    return rows[-1] if rows else None


def _write_alimi_alert(rec: Dict[str, Any]) -> None:
    if not rec.get("violated"):
        return
    sev = str(rec.get("severity") or "M")
    metric = str(rec.get("primary_metric") or "ledger_mismatch")
    limit = rec.get("primary_limit")
    value = rec.get("primary_value")
    action = str(rec.get("action") or "hold")
    line = f"ALERT:LEDGER/reconciliation|{metric} {value}>limit:{limit}|{action}|sev={sev}|src=ledger:{rec.get('reconcile_id')}"
    _line_append(ALIMI_OUTBOX, {
        "event": "alimi_alert_enqueued",
        "ts_ms": _now_ms(),
        "line": line,
        "source": "ledger_reconciliation",
        "reconcile_id": rec.get("reconcile_id"),
        "authority": "advisory_only",
        "order_mutation": "blocked",
    })


def _reconcile(payload: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(payload.get("mode") or "real").lower()
    if mode not in ALLOWED_MODES:
        raise HTTPException(status_code=400, detail={"ok": False, "error": "invalid_mode", "allowed": sorted(ALLOWED_MODES)})
    summary = _ledger_summary()
    internal_in = payload.get("internal") or {}
    external = payload.get("external") or payload.get("bingx") or {}
    m = (summary.get("modes") or {}).get(mode, {})

    internal = {
        "equity": _num(internal_in.get("equity")) if internal_in else _num(m.get("latest_equity")),
        "balance": _num(internal_in.get("balance")) if internal_in else _num(m.get("latest_balance")),
        "realized_pnl": _num(internal_in.get("realized_pnl")) if internal_in else _num(m.get("realized_pnl")),
        "fees": _num(internal_in.get("fees")) if internal_in else _num(m.get("fees")),
    }
    ext = {
        "exchange": str(external.get("exchange") or "bingx"),
        "equity": _num(external.get("equity")),
        "balance": _num(external.get("balance")),
        "realized_pnl": _num(external.get("realized_pnl") if "realized_pnl" in external else external.get("pnl")),
        "fees": _num(external.get("fees")),
        "positions_count": len(external.get("positions") or []) if isinstance(external.get("positions"), list) else None,
    }
    checks: List[Dict[str, Any]] = []

    def add_check(name: str, a: Optional[float], b: Optional[float], limit: float, unit: str) -> None:
        if a is None or b is None:
            checks.append({"metric": name, "status": "missing", "internal": a, "external": b, "limit": limit, "unit": unit})
            return
        delta = abs(float(a) - float(b))
        checks.append({"metric": name, "status": "violated" if delta > limit else "ok", "internal": a, "external": b, "delta": delta, "limit": limit, "unit": unit})

    add_check("equity_delta_usdt", internal["equity"], ext["equity"], BALANCE_USDT_LIMIT, "USDT")
    add_check("balance_delta_usdt", internal["balance"], ext["balance"], BALANCE_USDT_LIMIT, "USDT")
    add_check("realized_pnl_delta_usdt", internal["realized_pnl"], ext["realized_pnl"], PNL_USDT_LIMIT, "USDT")

    # PnL percentage delta is computed only when external equity/balance anchor is present.
    anchor = ext.get("equity") or ext.get("balance") or internal.get("equity") or internal.get("balance")
    pnl_delta = next((c.get("delta") for c in checks if c.get("metric") == "realized_pnl_delta_usdt" and c.get("delta") is not None), None)
    if anchor and pnl_delta is not None:
        pct_delta = abs(float(pnl_delta) / max(abs(float(anchor)), 1.0) * 100.0)
        checks.append({"metric": "realized_pnl_delta_pct", "status": "violated" if pct_delta > PNL_PCT_LIMIT else "ok", "delta": pct_delta, "limit": PNL_PCT_LIMIT, "unit": "%"})

    violated = [c for c in checks if c.get("status") == "violated"]
    missing = [c for c in checks if c.get("status") == "missing"]
    primary = violated[0] if violated else (missing[0] if missing else {"metric": "none", "delta": 0, "limit": 0, "unit": ""})
    severity = "C" if violated else ("M" if missing else "ok")
    action = "hold" if (violated or missing) else "hold"
    rid_src = {"ts_ms": _now_ms(), "payload": payload, "summary_head": summary["counts"]["hash_head"]}
    rid = "rec_" + _sha256(rid_src)[:24]
    rec = {
        "event": "ledger_reconciliation",
        "contract_version": CONTRACT_VERSION,
        "reconcile_id": rid,
        "ts_ms": _now_ms(),
        "mode": mode,
        "internal": internal,
        "external": ext,
        "checks": checks,
        "violated": bool(violated or missing),
        "missing": bool(missing),
        "severity": severity,
        "action": action,
        "strategy_pause_recommended": bool(violated or missing),
        "primary_metric": primary.get("metric"),
        "primary_value": primary.get("delta", primary.get("external")),
        "primary_limit": primary.get("limit"),
        "authority": "advisory_only",
        "order_mutation": "blocked",
        "os_final_approval_required": True,
        "hash_head": summary["counts"]["hash_head"],
    }
    _line_append(RECON_FILE, rec)
    _write_alimi_alert(rec)
    return rec


@router.get("")
def ledger_root() -> Dict[str, Any]:
    return ledger_status()


@router.get("/health")
def ledger_health() -> Dict[str, Any]:
    _ensure()
    return {
        "ok": True,
        "service": "zops-dual-ledger",
        "phase": "phase-6-dual-ledger-reconciliation-v1",
        "contract_version": CONTRACT_VERSION,
        "modes": sorted(ALLOWED_MODES),
        "authority": "advisory_only",
        "order_mutation": "blocked",
        "os_final_approval_required": True,
        "data_dir": str(DATA_DIR),
        "alimi_outbox": str(ALIMI_OUTBOX),
        "ts_ms": _now_ms(),
    }


@router.get("/status")
def ledger_status() -> Dict[str, Any]:
    summary = _ledger_summary()
    summary["service"] = "zops-dual-ledger"
    summary["latest_reconciliation"] = _latest_recon()
    summary["endpoints"] = [
        "/api/ledger/health",
        "/api/ledger/status",
        "/api/ledger/sample",
        "POST /api/ledger/event",
        "/api/ledger/events?mode=paper",
        "POST /api/ledger/reconcile",
        "/api/ledger/reconcile/latest",
        "/api/ledger/timeseries?mode=real&days=365",
    ]
    return summary


@router.get("/sample")
def ledger_sample() -> Dict[str, Any]:
    return {
        "ok": True,
        "contract_version": CONTRACT_VERSION,
        "event_payload": {
            "mode": "paper",
            "exchange": "bingx",
            "symbol": "BTCUSDT",
            "strategy": "alpha1",
            "team": "alpha",
            "decision_id": "decision_sample_001",
            "action": "hold",
            "qty": 0.001,
            "price": 65000,
            "fee": 0.03,
            "realized_pnl": 0.0,
            "equity": 10000,
            "balance": 10000,
            "source": "sample",
        },
        "reconcile_payload": {
            "mode": "paper",
            "internal": {"equity": 10000, "balance": 10000, "realized_pnl": 0},
            "external": {"exchange": "bingx", "equity": 10000, "balance": 10000, "realized_pnl": 0, "positions": []},
        },
    }


@router.post("/event")
def ledger_event(payload: Optional[Dict[str, Any]] = Body(default=None)) -> Dict[str, Any]:
    event = _append_ledger_event(payload or {})
    return {"ok": True, "ledger_event": event, "status_url": "/api/ledger/status"}


@router.get("/events")
def ledger_events(
    mode: Optional[str] = Query(default=None),
    decision_id: Optional[str] = Query(default=None),
    strategy: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
) -> Dict[str, Any]:
    events = [e for e in _read_jsonl(EVENTS_FILE, limit=5000) if e.get("event") == "ledger_event"]
    if mode:
        events = [e for e in events if str(e.get("mode")) == mode]
    if decision_id:
        events = [e for e in events if str(e.get("decision_id")) == decision_id]
    if strategy:
        events = [e for e in events if str(e.get("strategy")) == strategy]
    return {"ok": True, "events": events[-limit:], "count": len(events[-limit:]), "hash_head": _head_hash()}


@router.post("/reconcile")
def ledger_reconcile(payload: Optional[Dict[str, Any]] = Body(default=None)) -> Dict[str, Any]:
    return {"ok": True, "reconciliation": _reconcile(payload or {})}


@router.get("/reconcile/latest")
def ledger_reconcile_latest() -> Dict[str, Any]:
    return {"ok": True, "latest_reconciliation": _latest_recon()}


@router.get("/timeseries")
def ledger_timeseries(mode: str = Query(default="real"), days: int = Query(default=365, ge=1, le=2000)) -> Dict[str, Any]:
    if mode not in ALLOWED_MODES:
        raise HTTPException(status_code=400, detail={"ok": False, "error": "invalid_mode", "allowed": sorted(ALLOWED_MODES)})
    cutoff_ms = _now_ms() - days * 24 * 60 * 60 * 1000
    events = [e for e in _read_jsonl(EVENTS_FILE, limit=20000) if e.get("event") == "ledger_event" and e.get("mode") == mode and int(e.get("ts_ms") or 0) >= cutoff_ms]
    buckets: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"pnl": 0.0, "fees": 0.0, "events": 0, "latest_equity": None, "latest_balance": None})
    for e in events:
        day = time.strftime("%Y-%m-%d", time.gmtime(int(e.get("ts_ms") or 0) / 1000.0))
        b = buckets[day]
        b["pnl"] += _num(e.get("realized_pnl")) or 0.0
        b["fees"] += _num(e.get("fee")) or 0.0
        b["events"] += 1
        if _num(e.get("equity")) is not None:
            b["latest_equity"] = _num(e.get("equity"))
        if _num(e.get("balance")) is not None:
            b["latest_balance"] = _num(e.get("balance"))
    rows = [{"date": k, **v} for k, v in sorted(buckets.items())]
    return {"ok": True, "mode": mode, "days": days, "rows": rows, "count": len(rows)}
