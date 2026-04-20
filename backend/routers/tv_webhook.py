from __future__ import annotations

import importlib
from datetime import datetime, timezone
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from backend.contracts.null_error_contract import (
    NULL_ERROR_CONTRACT_VERSION,
    safe_str as contract_safe_str,
)

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from backend.engine.tv_hmac import verify_tv_hmac_only
from backend.engine.ingress_guard import check_and_mark_event_id

try:
    from backend.engine.lbot_core import (
        CONTRACT_INGRESS_SIDES,
        CONTRACT_MODES,
        CONTRACT_ROUTES,
        lbot_process,
    )
except Exception:  # pragma: no cover
    from backend.engine.lbot_core import lbot_process
    CONTRACT_INGRESS_SIDES = ("buy", "sell", "long", "short", "exit")
    CONTRACT_MODES = ("noop", "dummy", "paper", "shadow", "live")
    CONTRACT_ROUTES = ("noop", "paper", "live")

try:
    from backend.state.trade_state import sync_webhook_result
except Exception:  # pragma: no cover
    from state.trade_state import sync_webhook_result

router = APIRouter(prefix="/api/v1/tv", tags=["tv"])
logger = logging.getLogger("backend.routers.tv_webhook")

DATA_DIR = Path("/home/z/z/backend/data")
INBOX_DIR = DATA_DIR / "inbox" / "tv"
PROCESSED_DIR = DATA_DIR / "processed" / "tv"
FAILED_DIR = DATA_DIR / "failed" / "tv"
LOG_DIR = DATA_DIR / "logs"
JOURNAL_DIR = DATA_DIR / "journal"

RUNTIME_SPINE_VERSION = "2026-04-20.inline.c1"
RUNTIME_SPINE_EVIDENCE_ROOT = DATA_DIR / "evidence" / "runtime_spine"

TV_SECRET_PATH = Path("/home/z/z/backend/config/tv_secret.txt")
TV_NONCE_TTL_MS = 5 * 60 * 1000
TV_MAX_SKEW_S = 300
TV_NONCE_LEDGER_PATH = DATA_DIR / "tv_nonce_ledger.json"

REQUIRED_SIGNAL_KEYS = ("symbol", "side")
ALLOWED_ACTIONS = {
    "enter",
    "buy",
    "long",
    "sell",
    "short",
    "exit",
    "close",
    "reduce25",
    "partial30",
    "hold",
    "stop",
    "route_change",
    "rollback",
    "block",
}
ALLOWED_SIGNAL_PAYLOAD_KEYS = {
    "lev",
    "liq",
    "tp",
    "sl",
    "rr",
    "liq_warn",
    "sl_ok",
    "action",
    "dry_run",
}


class TvWebhookResponse(BaseModel):
    ok: bool = True
    event_id: str
    decision_id: str = ""
    signal_id: str = ""
    accepted_at: int
    queued_file: str
    processed_inline: bool = False
    deduped: bool = False
    reason: str = ""


def _mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _safe_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    return str(v).strip()


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def _safe_int(v: Any, default: int) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default


def _safe_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _norm_mode(v: Any, default: str = "paper") -> str:
    s = _safe_str(v, default).lower() or default
    return s if s in CONTRACT_MODES else default


def _norm_route(v: Any, default: str = "paper") -> str:
    s = _safe_str(v, default).lower() or default
    return s if s in CONTRACT_ROUTES else default


def _norm_side(v: Any, default: str = "") -> str:
    s = _safe_str(v, default).lower()
    return s if s in CONTRACT_INGRESS_SIDES else default


def _first_nonempty(*values: Any) -> str:
    for v in values:
        s = _safe_str(v)
        if s:
            return s
    return ""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _build_runtime_spine(envelope: Dict[str, Any], req: Dict[str, Any], out: Dict[str, Any]) -> Dict[str, Any]:
    event_id = _first_nonempty(req.get("event_id"), out.get("event_id"), "tv_inline")
    signal_id = _first_nonempty(req.get("signal_id"), out.get("signal_id"), event_id)
    decision_id = _first_nonempty(req.get("decision_id"), out.get("decision_id"), signal_id)
    stage_17_status = _first_nonempty(out.get("status"), "accepted")
    executor_status = _first_nonempty(out.get("executor_status"), "skipped")
    executor_result = _first_nonempty(out.get("executor_result"), "disabled")
    decision_action = _first_nonempty(out.get("decision_action"), out.get("risk_action"), "hold")
    decision_reason = _first_nonempty(out.get("decision_reason"), out.get("reason"), "inline_processed")
    effective_mode = _first_nonempty(out.get("effective_mode"), "shadow")
    effective_route = _first_nonempty(out.get("effective_route"), "paper")

    return {
        "version": RUNTIME_SPINE_VERSION,
        "flow": "Pre-17 -> 17 -> 18-23 -> 24-28",
        "event_id": event_id,
        "signal_id": signal_id,
        "decision_id": decision_id,
        "written_at": _utc_now_iso(),
        "source": _first_nonempty(((envelope or {}).get("meta") or {}).get("source"), "tv"),
        "request_id": _first_nonempty(((envelope or {}).get("meta") or {}).get("request_id"), event_id),
        "stage_pre17": {
            "status": "accepted",
            "event_id": event_id,
            "signal_id": signal_id,
            "decision_id": decision_id,
            "symbol": _safe_str(req.get("symbol")),
            "strategy": _safe_str(req.get("strategy")),
            "side": _safe_str(req.get("side")),
            "timeframe": _safe_str(req.get("timeframe")),
        },
        "stage_17": {
            "status": stage_17_status,
            "decision_action": decision_action,
            "decision_reason": decision_reason,
        },
        "stage_18_23": {
            "status": executor_status,
            "executor_status": executor_status,
            "executor_result": executor_result,
        },
        "stage_24_28": {
            "status": executor_result,
            "effective_mode": effective_mode,
            "effective_route": effective_route,
        },
    }


def _write_runtime_spine_snapshot(event_id: str, runtime_spine: Dict[str, Any], ts: Optional[int] = None) -> str:
    snap_dir = _today_dir(RUNTIME_SPINE_EVIDENCE_ROOT, _safe_int(ts, int(time.time())) or int(time.time()))
    snapshot_path = snap_dir / f"{_safe_name(event_id) or 'tv_inline'}_runtime_spine.json"
    payload = dict(runtime_spine or {})
    payload.setdefault("runtime_spine_version", RUNTIME_SPINE_VERSION)
    payload.setdefault("written_at", _utc_now_iso())
    payload["runtime_spine"] = dict(runtime_spine or {})
    _write_json(snapshot_path, payload)
    return str(snapshot_path)


def _attach_inline_runtime_spine(
    norm: Dict[str, Any],
    request_id: str,
    engine_out: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    out = dict(engine_out or {})
    if _safe_str(out.get("runtime_spine_snapshot_path")):
        return out

    req = _build_process_req(norm)
    env = {"meta": {"source": "tv", "request_id": request_id}}
    runtime_spine = _build_runtime_spine(env, req, out)

    try:
        snapshot_path = _write_runtime_spine_snapshot(
            event_id=_first_nonempty(req.get("event_id"), request_id),
            runtime_spine=runtime_spine,
            ts=_safe_int(req.get("ts"), int(time.time())),
        )
    except Exception as exc:
        logger.exception("runtime spine snapshot write failed request_id=%s", request_id)
        raise

    runtime_spine["runtime_spine_snapshot_path"] = snapshot_path
    out["runtime_spine_version"] = RUNTIME_SPINE_VERSION
    out["runtime_spine_flow"] = runtime_spine.get("flow")
    out["runtime_spine_snapshot_path"] = snapshot_path
    out["runtime_spine"] = runtime_spine
    return out


def _safe_name(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    _mkdir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _write_text(path: Path, text: str) -> None:
    _mkdir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _append_text_log(path: Path, line: str) -> None:
    _mkdir(path.parent)
    with path.open("a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    _mkdir(path.parent)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _today_dir(base: Path, ts: int) -> Path:
    day = time.strftime("%Y%m%d", time.gmtime(ts))
    p = base / day
    _mkdir(p)
    return p


def _get_webhook_secret() -> str:
    return TV_SECRET_PATH.read_text(encoding="utf-8").strip()


def _candidate_paths_for_event(root: Path, safe_event: str) -> list[Path]:
    if not safe_event or not root.exists():
        return []
    patterns = [
        f"**/{safe_event}.json",
        f"**/*_{safe_event}.json",
        f"**/{safe_event}.seen",
        f"**/*_{safe_event}.seen",
    ]
    hits: list[Path] = []
    for pat in patterns:
        hits.extend([p for p in root.glob(pat) if p.is_file()])
    return hits


def _find_existing_event_file(event_id: str, decision_id: str = "") -> Optional[Path]:
    keys = []
    for raw in (event_id, decision_id):
        safe = _safe_name(raw)
        if safe and safe not in keys:
            keys.append(safe)

    if not keys:
        return None

    for key in keys:
        direct_seen = PROCESSED_DIR / f"{key}.seen"
        if direct_seen.is_file():
            return direct_seen

    hits: list[Path] = []
    for key in keys:
        for root in (INBOX_DIR, PROCESSED_DIR, FAILED_DIR):
            hits.extend(_candidate_paths_for_event(root, key))

    if not hits:
        return None

    hits.sort(key=lambda p: p.stat().st_mtime)
    return hits[-1]


def _mark_event_seen(event_id: str, decision_id: str, payload: Dict[str, Any]) -> Optional[Path]:
    keys = []
    for raw in (event_id, decision_id):
        safe = _safe_name(raw)
        if safe and safe not in keys:
            keys.append(safe)

    if not keys:
        return None

    seen_path: Optional[Path] = None
    for key in keys:
        path = PROCESSED_DIR / f"{key}.seen"
        _write_text(
            path,
            json.dumps(
                {
                    "event_id": event_id,
                    "decision_id": decision_id,
                    "seen_at": int(time.time()),
                    "source": "tv_webhook",
                    "payload_ref": payload.get("queued_file", ""),
                },
                ensure_ascii=False,
            ),
        )
        seen_path = path
    return seen_path


def _missing_required_signal_keys(payload: Dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for key in REQUIRED_SIGNAL_KEYS:
        if contract_safe_str(payload.get(key)) == "":
            missing.append(key)
    return missing


def _normalize_side_for_engine(raw_side: str) -> str:
    s = _norm_side(raw_side)
    if s in {"buy", "long"}:
        return "buy"
    if s in {"sell", "short", "exit"}:
        return "sell"
    return s


def _normalize_action(payload: Dict[str, Any]) -> str:
    inner = payload.get("payload")
    inner = inner if isinstance(inner, dict) else {}
    action = _safe_str(payload.get("action") or inner.get("action"), "").lower()
    if action:
        return action
    side = _safe_str(payload.get("side"), "").lower()
    if side in {"buy", "long"}:
        return "enter"
    if side in {"sell", "short", "exit"}:
        return "exit"
    return ""


def _resolve_dry_run(payload: Dict[str, Any]) -> bool:
    inner = payload.get("payload")
    inner = inner if isinstance(inner, dict) else {}
    if "dry_run" in payload:
        return _safe_bool(payload.get("dry_run"), True)
    if "dry_run" in inner:
        return _safe_bool(inner.get("dry_run"), True)
    return True


def _collect_signal_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    inner = payload.get("payload")
    inner = inner if isinstance(inner, dict) else {}
    out: Dict[str, Any] = {}
    for key in ALLOWED_SIGNAL_PAYLOAD_KEYS:
        if key in inner:
            out[key] = inner[key]
        elif key in payload:
            out[key] = payload[key]
    return out


def _is_payload_ts_stale(ts: int, accepted_at: int, max_skew_s: int = TV_MAX_SKEW_S) -> bool:
    if ts <= 0:
        return False
    return abs(int(accepted_at) - int(ts)) > int(max_skew_s)


def _resolve_registry_strategy(symbol: str, requested_strategy: str) -> str:
    requested_strategy = _safe_str(requested_strategy).lower()
    symbol = _safe_str(symbol).upper()

    for mod_path in ("backend.engine.strategy_registry", "backend.engine.strategy_registry_g0_runtime_safe"):
        try:
            mod = importlib.import_module(mod_path)
            list_fn = getattr(mod, "list_strategy_specs", None)
            if callable(list_fn):
                keys = set()
                for item in list_fn(only_enabled=False):
                    if isinstance(item, dict) and item.get("key"):
                        keys.add(_safe_str(item.get("key")).lower())
                if requested_strategy and requested_strategy in keys:
                    return requested_strategy
                if "btc_trend_v1" in keys:
                    return "btc_trend_v1"
                if keys:
                    return sorted(keys)[0]
        except Exception:
            continue

    try:
        settings_mod = importlib.import_module("backend.routers.settings")
        load_all = getattr(settings_mod, "_load_all", None)
        build_sel = getattr(settings_mod, "_build_registry_selection", None)
        if callable(load_all) and callable(build_sel):
            data = load_all()
            sel = build_sel(data, symbol=symbol, strategy="")
            strategy = _safe_str(sel.get("strategy"), "")
            if strategy:
                return strategy.lower()
    except Exception:
        pass

    if requested_strategy and requested_strategy in {"btc_trend_v1", "eth_trend_v1", "btc_breakout_v1"}:
        return requested_strategy
    return os.getenv("Z_DEFAULT_STRATEGY", "btc_trend_v1").strip().lower() or "btc_trend_v1"


def _normalize_payload(payload: Dict[str, Any], accepted_at: int) -> Dict[str, Any]:
    inner_payload = payload.get("payload")
    inner_payload = inner_payload if isinstance(inner_payload, dict) else {}

    event_id = _safe_str(payload.get("event_id")) or f"tv_{accepted_at}"
    decision_id = _safe_str(payload.get("decision_id")) or event_id
    signal_id = _safe_str(payload.get("signal_id")) or decision_id
    symbol = _safe_str(payload.get("symbol")).upper()
    side = _norm_side(payload.get("side"))
    requested_strategy = _safe_str(payload.get("strategy"), "tv_webhook")
    strategy = _resolve_registry_strategy(symbol, requested_strategy)
    route = _norm_route(payload.get("route") or inner_payload.get("route"), "paper")
    mode = _norm_mode(payload.get("mode") or inner_payload.get("mode"), route)
    action = _normalize_action(payload)

    if not symbol:
        raise HTTPException(status_code=400, detail="missing_symbol")
    if side not in CONTRACT_INGRESS_SIDES:
        raise HTTPException(status_code=400, detail="invalid_side")
    if action and action not in ALLOWED_ACTIONS:
        raise HTTPException(status_code=400, detail=f"invalid_action:{action}")

    dry_run = _resolve_dry_run(payload)
    if dry_run:
        route = "paper"
        if mode == "live":
            mode = "paper"

    return {
        "event_id": event_id,
        "decision_id": decision_id,
        "signal_id": signal_id,
        "symbol": symbol,
        "side": side,
        "requested_strategy": requested_strategy,
        "strategy": strategy,
        "route": route,
        "mode": mode,
        "effective_route": route,
        "effective_mode": mode,
        "action": action or "enter",
        "dry_run": dry_run,
        "price": _safe_float(payload.get("price"), 0.0),
        "qty": payload.get("qty"),
        "size": payload.get("size"),
        "amount": payload.get("amount"),
        "order_type": _safe_str(payload.get("order_type"), "market"),
        "reduce_only": _safe_bool(payload.get("reduce_only"), False),
        "timeframe": _safe_str(payload.get("timeframe"), ""),
        "source": _safe_str(payload.get("source"), "tradingview"),
        "ts": _safe_int(payload.get("ts"), accepted_at),
        "signal_payload": _collect_signal_payload(payload),
        "raw_payload": payload,
    }


def _build_process_req(norm: Dict[str, Any]) -> Dict[str, Any]:
    signal_payload = dict(norm["signal_payload"])
    signal_payload.update(
        {
            "event_id": norm["event_id"],
            "decision_id": norm["decision_id"],
            "raw_side": norm["side"],
            "route": norm["route"],
            "mode": norm["mode"],
            "requested_strategy": norm.get("requested_strategy", ""),
            "action": norm.get("action"),
            "dry_run": norm.get("dry_run", True),
        }
    )

    signal = {
        "signal_id": norm["signal_id"],
        "event_id": norm["event_id"],
        "decision_id": norm["decision_id"],
        "symbol": norm["symbol"],
        "strategy": norm["strategy"],
        "side": _normalize_side_for_engine(norm["side"]),
        "price": norm["price"],
        "ts": norm["ts"],
        "timeframe": norm["timeframe"],
        "source": norm["source"],
        "order_type": norm["order_type"],
        "reduce_only": norm["reduce_only"],
        "payload": signal_payload,
    }

    size_val = _safe_float(norm.get("size"), 0.0)
    qty_val = _safe_float(norm.get("qty"), 0.0)
    amount_val = _safe_float(norm.get("amount"), 0.0)
    final_size = size_val or qty_val or amount_val
    if final_size > 0:
        signal["size"] = final_size
        signal["qty"] = final_size

    return {
        "mode": norm["mode"],
        "route": norm["route"],
        "signal": signal,
    }


def _derive_reason(result: Dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return "processed_inline"

    for key in ("detail", "reason", "decision_reason"):
        val = result.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    executor = result.get("executor", {}) if isinstance(result.get("executor"), dict) else {}
    journal = result.get("journal_event", {}) if isinstance(result.get("journal_event"), dict) else {}

    for key in ("decision_reason", "executor_result", "status"):
        val = journal.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    for key in ("code", "reason", "executor_result", "status"):
        val = executor.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    return "processed_inline"


def _summarize_result(norm: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    top = result if isinstance(result, dict) else {}
    journal = top.get("journal_event", {}) if isinstance(top.get("journal_event"), dict) else {}
    executor = top.get("executor", {}) if isinstance(top.get("executor"), dict) else {}
    reason = _derive_reason(top).lower()

    return {
        "ok": bool(top.get("ok", False)),
        "detail": _safe_str(top.get("detail"), reason).lower() or reason,
        "reason": _safe_str(top.get("reason"), reason).lower() or reason,
        "status": _first_nonempty(top.get("status"), journal.get("status"), "blocked" if not bool(top.get("ok", False)) else "ready").lower(),
        "decision_action": _first_nonempty(top.get("decision_action"), journal.get("decision_action"), executor.get("action"), norm.get("action"), "hold").lower(),
        "risk_action": _first_nonempty(top.get("risk_action"), journal.get("risk_action"), top.get("decision_action"), norm.get("action"), "hold").lower(),
        "decision_reason": _first_nonempty(top.get("decision_reason"), journal.get("decision_reason"), reason).lower() or reason,
        "executor_status": _first_nonempty(
            top.get("executor_status"),
            journal.get("executor_status"),
            executor.get("executor_status"),
            executor.get("status"),
            "blocked" if not bool(top.get("ok", False)) else "ready",
        ).lower(),
        "executor_result": _first_nonempty(
            top.get("executor_result"),
            journal.get("executor_result"),
            executor.get("executor_result"),
            executor.get("result"),
            executor.get("reason"),
            executor.get("code"),
            reason,
        ).lower() or reason,
        "effective_mode": _norm_mode(_first_nonempty(top.get("effective_mode"), journal.get("effective_mode"), norm["mode"]), norm["mode"]),
        "effective_route": _norm_route(_first_nonempty(top.get("effective_route"), journal.get("effective_route"), norm["route"]), norm["route"]),
        "event_id": _first_nonempty(top.get("event_id"), journal.get("event_id"), norm["event_id"]),
        "decision_id": _first_nonempty(top.get("decision_id"), journal.get("decision_id"), norm["decision_id"]),
        "signal_id": _first_nonempty(top.get("signal_id"), journal.get("signal_id"), norm["signal_id"]),
        "symbol": _first_nonempty(top.get("symbol"), journal.get("symbol"), norm["symbol"]).upper(),
        "strategy": _first_nonempty(top.get("strategy"), journal.get("strategy"), norm["strategy"]),
        "requested_strategy": norm.get("requested_strategy", ""),
        "side": _first_nonempty(top.get("side"), journal.get("side"), norm["side"]).lower(),
        "dry_run": bool(norm.get("dry_run", True)),
        "action": _safe_str(norm.get("action"), "enter").lower(),
        "written_at": _first_nonempty(top.get("written_at"), journal.get("written_at"), ""),
        "runtime_spine_version": top.get("runtime_spine_version"),
        "runtime_spine_flow": top.get("runtime_spine_flow"),
        "runtime_spine_snapshot_path": _extract_runtime_spine_snapshot_path(top),
    }


def _archive_processed(inbox_file: Path, accepted_at: int, safe_event: str, payload: Dict[str, Any]) -> Path:
    processed_dir = _today_dir(PROCESSED_DIR, accepted_at)
    processed_file = processed_dir / f"{accepted_at}_{safe_event}.json"
    _write_json(processed_file, payload)
    try:
        if inbox_file.exists():
            inbox_file.unlink()
    except Exception:
        pass
    return processed_file


def _archive_failed(inbox_file: Path, accepted_at: int, safe_event: str, payload: Dict[str, Any]) -> Path:
    failed_dir = _today_dir(FAILED_DIR, accepted_at)
    failed_file = failed_dir / f"{accepted_at}_{safe_event}.json"
    _write_json(failed_file, payload)
    try:
        if inbox_file.exists():
            inbox_file.unlink()
    except Exception:
        pass
    return failed_file


def _process_inline(norm: Dict[str, Any]) -> Dict[str, Any]:
    request_id = _first_nonempty(
        _safe_str(norm.get("decision_id")),
        _safe_str(norm.get("event_id")),
        _safe_str(norm.get("signal_id")),
        f"tv_inline_{int(time.time())}",
    )
    req = _build_process_req(norm)
    result = lbot_process(req)
    return _attach_inline_runtime_spine(norm, request_id, result)


def _extract_runtime_spine_snapshot_path(top: Dict[str, Any]) -> Optional[str]:
    candidates = [
        top.get("runtime_spine_snapshot_path"),
        ((top.get("runtime_spine") or {}).get("runtime_spine_snapshot_path")),
        (((top.get("result") or {}).get("runtime_spine_snapshot_path"))),
        ((((top.get("result") or {}).get("runtime_spine") or {}).get("runtime_spine_snapshot_path"))),
        (((top.get("summary") or {}).get("runtime_spine_snapshot_path"))),
    ]
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _sync_downstream(norm: Dict[str, Any], accepted_at: int, result_reason: str, result_summary: Dict[str, Any], processed_file: Path) -> None:
    sync_webhook_result(
        decision_id=norm["decision_id"],
        signal_id=norm["signal_id"],
        event_id=norm["event_id"],
        symbol=norm["symbol"],
        side=norm["side"],
        strategy=norm["strategy"],
        route=norm["route"],
        mode=norm["mode"],
        price=norm["price"],
        qty=norm.get("qty") or norm.get("size") or norm.get("amount"),
        accepted_at=accepted_at,
        result_reason=result_reason,
        result_summary=result_summary,
    )

    journal_event = {
        "status": result_summary.get("status", "ready"),
        "event_type": "tv_webhook",
        "event_id": norm["event_id"],
        "decision_id": norm["decision_id"],
        "signal_id": norm["signal_id"],
        "strategy": norm["strategy"],
        "requested_strategy": norm.get("requested_strategy", ""),
        "symbol": norm["symbol"],
        "decision_action": result_summary.get("decision_action", norm.get("action", "hold")),
        "decision_reason": result_summary.get("decision_reason", result_reason),
        "risk_action": result_summary.get("risk_action", norm.get("action", "hold")),
        "executor_status": result_summary.get("executor_status", "ready"),
        "executor_result": result_summary.get("executor_result", result_reason),
        "effective_mode": result_summary.get("effective_mode", norm["mode"]),
        "effective_route": result_summary.get("effective_route", norm["route"]),
        "dry_run": bool(norm.get("dry_run", True)),
        "action": norm.get("action", "enter"),
        "ts": accepted_at * 1000,
        "written_at": int(time.time() * 1000),
        "source_file": str(processed_file),
    }
    latest_event = {
        "event_id": norm["event_id"],
        "decision_id": norm["decision_id"],
        "signal_id": norm["signal_id"],
        "journal_event": journal_event,
        "result_reason": result_reason,
        "result_summary": result_summary,
        "processed_file": str(processed_file),
        "updated_at": int(time.time() * 1000),
    }
    _write_json(JOURNAL_DIR / "lbot_event.latest.json", latest_event)
    day = time.strftime("%Y%m%d", time.gmtime(accepted_at))
    _append_jsonl(JOURNAL_DIR / f"lbot_event.{day}.jsonl", latest_event)
    _append_jsonl(JOURNAL_DIR / f"lbot_events.{day}.jsonl", latest_event)
    _append_jsonl(JOURNAL_DIR / f"lbot_events_{day}.jsonl", latest_event)


@router.post("/webhook", response_model=TvWebhookResponse)
async def tv_webhook(
    request: Request,
    x_tv_signature: Optional[str] = Header(default=None, alias="X-TV-Signature"),
):
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty_body")

    verify_result = verify_tv_hmac_only(
        raw_body=body,
        sig_header_value=x_tv_signature,
        secret=_get_webhook_secret(),
        nonce_ttl_ms=TV_NONCE_TTL_MS,
        max_skew_s=TV_MAX_SKEW_S,
        nonce_ledger_path=str(TV_NONCE_LEDGER_PATH),
    )
    if not verify_result.ok:
        raise HTTPException(status_code=verify_result.status_code, detail=verify_result.reason)

    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_json")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid_payload")

    accepted_at = int(time.time())
    missing_required = _missing_required_signal_keys(payload)
    if missing_required:
        raise HTTPException(status_code=400, detail="missing_required_fields:" + ",".join(missing_required))

    norm = _normalize_payload(payload, accepted_at)

    if _is_payload_ts_stale(norm["ts"], accepted_at, TV_MAX_SKEW_S):
        return TvWebhookResponse(
            ok=False,
            event_id=norm["event_id"],
            decision_id=norm["decision_id"],
            signal_id=norm["signal_id"],
            accepted_at=accepted_at,
            queued_file="",
            processed_inline=False,
            deduped=False,
            reason="timestamp_skew",
        )

    ok_once, once_reason = check_and_mark_event_id(norm["event_id"])
    if not ok_once:
        return TvWebhookResponse(
            ok=True,
            event_id=norm["event_id"],
            decision_id=norm["decision_id"],
            signal_id=norm["signal_id"],
            accepted_at=accepted_at,
            queued_file="",
            processed_inline=False,
            deduped=True,
            reason=once_reason,
        )

    existing = _find_existing_event_file(event_id=norm["event_id"], decision_id=norm["decision_id"])
    if existing is not None:
        return TvWebhookResponse(
            ok=True,
            event_id=norm["event_id"],
            decision_id=norm["decision_id"],
            signal_id=norm["signal_id"],
            accepted_at=accepted_at,
            queued_file=str(existing),
            processed_inline=False,
            deduped=True,
            reason="duplicate_event",
        )

    inbox_dir = _today_dir(INBOX_DIR, accepted_at)
    safe_event = _safe_name(norm["event_id"]) or f"tv_{accepted_at}"
    inbox_file = inbox_dir / f"{accepted_at}_{safe_event}.json"

    envelope = {
        "symbol": norm["symbol"],
        "side": norm["side"],
        "event_id": norm["event_id"],
        "decision_id": norm["decision_id"],
        "signal_id": norm["signal_id"],
        "exchange": "bingx",
        "qty": norm["qty"],
        "size": norm["size"],
        "amount": norm["amount"],
        "price": norm["price"],
        "order_type": norm["order_type"],
        "reduce_only": norm["reduce_only"],
        "strategy": norm["strategy"],
        "requested_strategy": norm.get("requested_strategy", ""),
        "route": norm["route"],
        "mode": norm["mode"],
        "action": norm["action"],
        "dry_run": bool(norm["dry_run"]),
        "accepted_at": accepted_at,
        "source": norm["source"],
        "timeframe": norm["timeframe"],
        "ts": norm["ts"],
        "meta": {
            "path": "/api/v1/tv/webhook",
            "remote": request.client.host if request.client else "",
            "ua": request.headers.get("user-agent", ""),
            "content_type": request.headers.get("content-type", ""),
            "schema_version": 29,
        },
        "payload": payload,
        "raw_text": body.decode("utf-8", errors="replace"),
    }

    try:
        _write_json(inbox_file, envelope)
        engine_req = _build_process_req(norm)
        engine_out = _process_inline(norm)
        result_reason = _derive_reason(engine_out)
        result_summary = _summarize_result(norm, engine_out)

        spine = ((engine_out or {}).get("runtime_spine") or {})
        processed_file = _archive_processed(
            inbox_file=inbox_file,
            accepted_at=accepted_at,
            safe_event=safe_event,
            payload={
                **envelope,
                "processed_at": int(time.time()),
                "process_request": engine_req,
                "process_result": engine_out,
                "result_reason": result_reason,
                "result_summary": result_summary,
                "worker_summary": result_summary,
                "result": engine_out,
                "runtime_spine_snapshot_path": result_summary.get("runtime_spine_snapshot_path"),
                "runtime_spine_version": result_summary.get("runtime_spine_version"),
                "runtime_spine_flow": result_summary.get("runtime_spine_flow"),
                "flow": spine.get("flow"),
                "stage_pre17": spine.get("stage_pre17"),
                "stage_17": spine.get("stage_17"),
                "stage_18_23": spine.get("stage_18_23"),
                "stage_24_28": spine.get("stage_24_28"),
                "stage_pre17_status": ((spine.get("stage_pre17") or {}).get("status")),
                "stage_17_status": ((spine.get("stage_17") or {}).get("status")),
                "stage_18_23_status": ((spine.get("stage_18_23") or {}).get("status")),
                "stage_24_28_status": ((spine.get("stage_24_28") or {}).get("status")),
            },
        )

        _mark_event_seen(
            event_id=norm["event_id"],
            decision_id=norm["decision_id"],
            payload={"queued_file": str(processed_file)},
        )

        _sync_downstream(norm, accepted_at, result_reason, result_summary, processed_file)

        _append_text_log(
            LOG_DIR / "tv_signal_bridge.log",
            f'PROCESSED event_id={norm["event_id"]} decision_id={norm["decision_id"]} '
            f'symbol={norm["symbol"]} side={norm["side"]} strategy={norm["strategy"]} '
            f'action={norm["action"]} dry_run={int(bool(norm["dry_run"]))} '
            f'route={norm["route"]} mode={norm["mode"]} reason={result_reason} file={processed_file}'
        )

        return TvWebhookResponse(
            ok=True,
            event_id=norm["event_id"],
            decision_id=norm["decision_id"],
            signal_id=norm["signal_id"],
            accepted_at=accepted_at,
            queued_file=str(processed_file),
            processed_inline=True,
            deduped=False,
            reason=result_reason,
        )
    except HTTPException:
        raise
    except Exception as e:
        failed_file = _archive_failed(
            inbox_file=inbox_file,
            accepted_at=accepted_at,
            safe_event=safe_event,
            payload={**envelope, "failed_at": int(time.time()), "error": repr(e)},
        )
        _append_text_log(
            LOG_DIR / "tv_signal_bridge.log",
            f'FAILED event_id={norm["event_id"]} decision_id={norm["decision_id"]} '
            f'symbol={norm["symbol"]} side={norm["side"]} route={norm["route"]} mode={norm["mode"]} '
            f'error={repr(e)} file={failed_file}'
        )
        raise HTTPException(status_code=500, detail=f"process_failed: {e}")


__all__ = ["router", "TvWebhookResponse", "tv_webhook"]
NULL_ERROR_CONTRACT_MARKER = NULL_ERROR_CONTRACT_VERSION
