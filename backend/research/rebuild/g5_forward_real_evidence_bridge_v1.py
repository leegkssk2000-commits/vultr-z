#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "backend/research/contracts/g5_forward_real_evidence_contract_v1.json"
EFFECTIVE_PATH = ROOT / "backend/research/rebuild/g5_clean_runner_contract_effective_v1.json"
CUTOVER_PATH = ROOT / "backend/research/rebuild/g5_clean_runner_cutover_receipt_v1.json"
STALE_PATH = ROOT / "backend/research/rebuild/g5_data_stale_evidence_v1.json"
COST_PATH = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
STATE_PATH = ROOT / "backend/research/rebuild/g5_clean_runner_state_events_v1.jsonl"
BRIDGE_STATE_PATH = ROOT / "backend/research/rebuild/g5_forward_real_bridge_state_v1.jsonl"
BRIDGE_LEDGER_PATH = ROOT / "backend/research/rebuild/g5_forward_real_evidence_ledger_v1.jsonl"
CANONICAL_LEDGER_PATH = ROOT / "backend/research/prep/g5_economic_evidence_ledger_v1.jsonl"

DEPTH_API = "https://open-api.bingx.com/openApi/swap/v2/quote/depth"
FUNDING_API = "https://open-api.bingx.com/openApi/swap/v2/quote/fundingRate"
KLINE_API = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
CONTRACT_SCHEMA = "zel.g5.forward_real_evidence_contract.v1"
EVIDENCE_SCHEMA = "zel.g5.economic_evidence_row.v1"
BRIDGE_EVENT_SCHEMA = "zel.g5.forward_real_bridge_event.v1"
FOUR_HOURS_MS = 14_400_000
EIGHT_HOURS_MS = 28_800_000
FIVE_MIN_MS = 300_000


def stable(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode("utf-8") + data).hexdigest()


def now_ms() -> int:
    return int(time.time() * 1000)


def iso_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise RuntimeError(f"JSONL_OBJECT_REQUIRED:{path}:{line_no}")
        out.append(value)
    return out


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(
        json.dumps(dict(row), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"
        for row in rows
    )
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def validate_contract(contract: Mapping[str, Any]) -> None:
    if contract.get("schema_version") != CONTRACT_SCHEMA:
        raise RuntimeError("FORWARD_REAL_CONTRACT_SCHEMA_MISMATCH")
    if contract.get("state") != "FROZEN_FUTURE_ONLY_FORWARD_REAL_EVIDENCE_BRIDGE":
        raise RuntimeError("FORWARD_REAL_CONTRACT_NOT_FROZEN")
    activation = contract.get("activation") if isinstance(contract.get("activation"), Mapping) else {}
    if activation.get("future_only") is not True or activation.get("historical_backfill_forbidden") is not True:
        raise RuntimeError("FORWARD_REAL_FUTURE_ONLY_REQUIRED")
    authority = contract.get("authority") if isinstance(contract.get("authority"), Mapping) else {}
    if authority != {"selection": False, "promotion": False, "execution": "NONE", "order": "BLOCKED", "live": "BLOCKED"}:
        raise RuntimeError("FORWARD_REAL_AUTHORITY_DRIFT")


def request_json(url: str, params: Mapping[str, Any]) -> Any:
    target = url + "?" + urllib.parse.urlencode(dict(params))
    req = urllib.request.Request(target, headers={"User-Agent": "zel-g5-forward-real-evidence-v1"})
    with urllib.request.urlopen(req, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if isinstance(payload, dict) and payload.get("code") not in (None, 0):
        raise RuntimeError(f"BINGX_API_ERROR:{payload.get('code')}:{payload.get('msg')}")
    return payload


def _depth_vwap(levels: Sequence[Sequence[Any]], target_quote: float) -> float:
    remaining = float(target_quote)
    quote = 0.0
    base = 0.0
    for row in levels:
        if len(row) < 2:
            continue
        price = float(row[0]); qty = float(row[1])
        if price <= 0 or qty <= 0:
            continue
        take = min(qty, remaining / price)
        quote += take * price
        base += take
        remaining -= take * price
        if remaining <= 1e-8:
            break
    if remaining > max(0.01, target_quote * 1e-6) or base <= 0:
        raise RuntimeError("DEPTH_REFERENCE_NOTIONAL_UNFILLED")
    return quote / base


class MarketProvider(Protocol):
    def depth(self, symbol: str, reference_notional: float) -> dict[str, Any]: ...
    def funding(self, symbol: str) -> dict[str, Any]: ...
    def path5m(self, symbol: str, start_ms: int, end_ms: int) -> dict[str, Any]: ...


class PublicBingXProvider:
    def depth(self, symbol: str, reference_notional: float) -> dict[str, Any]:
        requested_at = now_ms()
        payload = request_json(DEPTH_API, {"symbol": symbol, "limit": 50})
        observed_at = now_ms()
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        bids = data.get("bids") or []
        asks = data.get("asks") or []
        if not bids or not asks:
            raise RuntimeError(f"DEPTH_EMPTY:{symbol}")
        bid = float(bids[0][0]); ask = float(asks[0][0])
        if bid <= 0 or ask <= bid:
            raise RuntimeError(f"DEPTH_TOP_INVALID:{symbol}:{bid}:{ask}")
        mid = (bid + ask) / 2.0
        buy_vwap = _depth_vwap(asks, reference_notional)
        sell_vwap = _depth_vwap(bids, reference_notional)
        row = {
            "schema_version": "zel.g5.forward_real_depth_snapshot.v1",
            "symbol": symbol,
            "requested_at_ms": requested_at,
            "observed_at_ms": observed_at,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "buy_vwap": buy_vwap,
            "sell_vwap": sell_vwap,
            "reference_notional_usdt": reference_notional,
            "source_endpoint": "/openApi/swap/v2/quote/depth",
            "point_in_time": True,
        }
        row["snapshot_sha256"] = stable(row)
        return row

    def funding(self, symbol: str) -> dict[str, Any]:
        requested_at = now_ms()
        payload = request_json(FUNDING_API, {"symbol": symbol, "limit": 100})
        observed_at = now_ms()
        raw_rows = payload.get("data", []) if isinstance(payload, dict) else []
        rows: list[dict[str, Any]] = []
        for raw in raw_rows:
            if not isinstance(raw, Mapping):
                continue
            ts = raw.get("fundingTime")
            if ts is None:
                ts = raw.get("time")
            if ts is None:
                ts = raw.get("timestamp")
            rate = raw.get("fundingRate")
            if rate is None:
                rate = raw.get("rate")
            if ts is None or rate is None:
                continue
            rows.append({"ts_ms": int(ts), "rate": float(rate)})
        rows.sort(key=lambda row: int(row["ts_ms"]))
        body = {
            "schema_version": "zel.g5.forward_real_funding_snapshot.v1",
            "symbol": symbol,
            "requested_at_ms": requested_at,
            "observed_at_ms": observed_at,
            "rows": rows,
            "source_endpoint": "/openApi/swap/v2/quote/fundingRate",
            "signed_rates_preserved": True,
        }
        body["snapshot_sha256"] = stable(body)
        return body

    def path5m(self, symbol: str, start_ms: int, end_ms: int) -> dict[str, Any]:
        payload = request_json(KLINE_API, {"symbol": symbol, "interval": "5m", "limit": 1000})
        raw_rows = payload.get("data", payload if isinstance(payload, list) else [])
        rows: list[dict[str, Any]] = []
        for raw in raw_rows:
            if isinstance(raw, Mapping):
                ts = raw.get("time")
                if ts is None:
                    ts = raw.get("openTime")
                if ts is None:
                    ts = raw.get("timestamp")
                if ts is None:
                    continue
                row = {"ts_ms": int(ts), "open": float(raw["open"]), "high": float(raw["high"]), "low": float(raw["low"]), "close": float(raw["close"])}
            else:
                if len(raw) < 5:
                    continue
                row = {"ts_ms": int(raw[0]), "open": float(raw[1]), "high": float(raw[2]), "low": float(raw[3]), "close": float(raw[4])}
            # Only fully observed 5m bars inside the realized holding interval.
            if int(row["ts_ms"]) >= start_ms and int(row["ts_ms"]) + FIVE_MIN_MS <= end_ms:
                rows.append(row)
        rows = sorted({int(row["ts_ms"]): row for row in rows}.values(), key=lambda row: int(row["ts_ms"]))
        body = {
            "schema_version": "zel.g5.forward_real_path5m.v1",
            "symbol": symbol,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "interval_ms": FIVE_MIN_MS,
            "rows": rows,
        }
        body["path_sha256"] = stable(body)
        return body


def bridge_event(rows: list[dict[str, Any]], *, kind: str, payload: Mapping[str, Any], event_ts_ms: int) -> dict[str, Any]:
    prev = str(rows[-1].get("record_sha256") or "") if rows else None
    core = {
        "schema_version": BRIDGE_EVENT_SCHEMA,
        "seq": len(rows),
        "kind": kind,
        "event_ts_ms": int(event_ts_ms),
        "event_ts_utc": iso_ms(int(event_ts_ms)),
        "prev_sha256": prev,
        "payload": dict(payload),
    }
    core["record_sha256"] = stable(core)
    rows.append(core)
    return core


def validate_bridge_chain(rows: Sequence[Mapping[str, Any]]) -> None:
    prev: str | None = None
    for idx, row in enumerate(rows):
        if row.get("schema_version") != BRIDGE_EVENT_SCHEMA or row.get("seq") != idx:
            raise RuntimeError(f"BRIDGE_STATE_SCHEMA_OR_SEQ:{idx}")
        if row.get("prev_sha256") != prev:
            raise RuntimeError(f"BRIDGE_STATE_PREV_SHA:{idx}")
        supplied = str(row.get("record_sha256") or "")
        core = dict(row); core.pop("record_sha256", None)
        if supplied != stable(core):
            raise RuntimeError(f"BRIDGE_STATE_HASH:{idx}")
        prev = supplied


def signal_identity(row: Mapping[str, Any]) -> str:
    payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
    return "|".join([
        str(payload.get("strategy_id") or ""),
        str(payload.get("child_id") or ""),
        str(payload.get("symbol") or ""),
        str(int(payload.get("signal_bar_close_ts") or 0)),
        str(row.get("record_sha256") or ""),
    ])


def trade_id_for_signal(row: Mapping[str, Any]) -> str:
    return hashlib.sha256(signal_identity(row).encode("utf-8")).hexdigest()


def active_strategy_map(effective: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in effective.get("active_strategies") or []:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        key = (str(row.get("strategy_id") or ""), str(row.get("child_id") or ""))
        if not all(key) or key in out:
            raise RuntimeError(f"ACTIVE_STRATEGY_IDENTITY_INVALID:{key}")
        out[key] = row
    if not out:
        raise RuntimeError("ACTIVE_STRATEGIES_REQUIRED")
    return out


def signal_rows(source_rows: Sequence[Mapping[str, Any]], activation_ms: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in source_rows:
        if raw.get("status") != "EVALUATED":
            continue
        payload = raw.get("payload") if isinstance(raw.get("payload"), Mapping) else {}
        if payload.get("signal") is not True or payload.get("result") != "SIGNAL_EMITTED":
            continue
        if payload.get("correct_child") is not True or int(payload.get("duplicate") or 0) != 0 or int(payload.get("lookahead") or 0) != 0:
            continue
        event_ms = parse_iso_ms(str(raw.get("event_ts") or "1970-01-01T00:00:00Z"))
        if event_ms <= activation_ms:
            continue
        out.append(dict(raw))
    return sorted(out, key=lambda row: (parse_iso_ms(str(row["event_ts"])), signal_identity(row)))


def _entry_execution(depth: Mapping[str, Any], side: str) -> tuple[float, float]:
    mid = float(depth["mid"])
    if side == "long":
        px = float(depth["buy_vwap"])
        slip = max(0.0, px / mid - 1.0) * 10_000.0
    elif side == "short":
        px = float(depth["sell_vwap"])
        slip = max(0.0, mid / px - 1.0) * 10_000.0
    else:
        raise RuntimeError(f"SIDE_INVALID:{side}")
    return px, slip


def _exit_execution(depth: Mapping[str, Any], side: str) -> tuple[float, float]:
    mid = float(depth["mid"])
    if side == "long":
        px = float(depth["sell_vwap"])
        slip = max(0.0, mid / px - 1.0) * 10_000.0
    elif side == "short":
        px = float(depth["buy_vwap"])
        slip = max(0.0, px / mid - 1.0) * 10_000.0
    else:
        raise RuntimeError(f"SIDE_INVALID:{side}")
    return px, slip


def signed_funding_cost_bps(side: str, rows: Sequence[Mapping[str, Any]]) -> float:
    sign = 1.0 if side == "long" else -1.0 if side == "short" else math.nan
    if not math.isfinite(sign):
        raise RuntimeError(f"SIDE_INVALID:{side}")
    return sign * sum(float(row["rate"]) * 10_000.0 for row in rows)


def path_excursions(side: str, entry_mid: float, path: Mapping[str, Any]) -> tuple[float | None, float | None]:
    rows = [row for row in (path.get("rows") or []) if isinstance(row, Mapping)]
    if not rows:
        return None, None
    if side == "long":
        mfe = max(max(0.0, float(row["high"]) / entry_mid - 1.0) * 10_000.0 for row in rows)
        mae = max(max(0.0, 1.0 - float(row["low"]) / entry_mid) * 10_000.0 for row in rows)
    elif side == "short":
        mfe = max(max(0.0, 1.0 - float(row["low"]) / entry_mid) * 10_000.0 for row in rows)
        mae = max(max(0.0, float(row["high"]) / entry_mid - 1.0) * 10_000.0 for row in rows)
    else:
        raise RuntimeError(f"SIDE_INVALID:{side}")
    return mfe, mae


def open_index(bridge_rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    opens: dict[str, dict[str, Any]] = {}
    terminal: set[str] = set()
    for row in bridge_rows:
        kind = str(row.get("kind") or "")
        payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
        tid = str(payload.get("trade_id") or "")
        if kind == "OPENED_PROVENANCE" and tid:
            opens[tid] = dict(payload)
        elif kind in {"CLOSED_PRODUCTION", "CLOSED_FAIL_CLOSED", "OPEN_REJECTED"} and tid:
            terminal.add(tid)
    return {tid: row for tid, row in opens.items() if tid not in terminal}, terminal


def evidence_row(
    *,
    opened: Mapping[str, Any],
    exit_depth: Mapping[str, Any],
    funding_snapshot: Mapping[str, Any],
    path: Mapping[str, Any],
    fee_one_way_bps: float,
    fee_authority_sha: str,
    cutover_ready: bool,
    stale_ready: bool,
) -> dict[str, Any]:
    side = str(opened["side"])
    entry_depth = opened["entry_depth"]
    if not isinstance(entry_depth, Mapping):
        raise RuntimeError("ENTRY_DEPTH_REQUIRED")
    entry_mid = float(entry_depth["mid"]); exit_mid = float(exit_depth["mid"])
    entry_exec, entry_slip = _entry_execution(entry_depth, side)
    exit_exec, exit_slip = _exit_execution(exit_depth, side)
    direction = 1.0 if side == "long" else -1.0
    gross_bps = direction * (exit_mid / entry_mid - 1.0) * 10_000.0
    slippage_bps = entry_slip + exit_slip
    fee_bps = 2.0 * float(fee_one_way_bps)
    entry_ts = int(opened["entry_ts"]); exit_ts = int(exit_depth["observed_at_ms"])
    all_funding = [row for row in (funding_snapshot.get("rows") or []) if isinstance(row, Mapping)]
    crossed = [dict(row) for row in all_funding if entry_ts < int(row.get("ts_ms") or 0) <= exit_ts and row.get("rate") is not None]
    hold_ms = max(0, exit_ts - entry_ts)
    funding_complete = bool(funding_snapshot.get("signed_rates_preserved") is True)
    if hold_ms >= EIGHT_HOURS_MS and not crossed:
        funding_complete = False
    funding_bps = signed_funding_cost_bps(side, crossed) if funding_complete else 0.0
    net_bps = gross_bps - fee_bps - slippage_bps - funding_bps
    mfe_bps, mae_bps = path_excursions(side, entry_mid, path)
    path_ok = mfe_bps is not None and mae_bps is not None and bool(path.get("path_sha256"))

    reasons: list[str] = []
    if not cutover_ready:
        reasons.append("CLEAN_RUNNER_NOT_PRODUCTION_READY")
    if not stale_ready:
        reasons.append("DATA_STALE_AUTHORITY_MISSING")
    if entry_depth.get("point_in_time") is not True or exit_depth.get("point_in_time") is not True:
        reasons.append("POINT_IN_TIME_DEPTH_MISSING")
    if not fee_authority_sha:
        reasons.append("FEE_AUTHORITY_LINEAGE_MISSING")
    if not funding_complete:
        reasons.append("SIGNED_FUNDING_SETTLEMENT_LINEAGE_MISSING")
    if not path_ok:
        reasons.append("INTRABAR_EXECUTION_ORDER_NOT_OBSERVED")
    if opened.get("qty") is None or opened.get("notional") is None:
        reasons.append("SIZE_PROVENANCE_MISSING")
    production_grade = not reasons

    settlement_rows = []
    for row in crossed:
        item = {"ts_ms": int(row["ts_ms"]), "rate": float(row["rate"])}
        item["row_sha256"] = stable(item)
        settlement_rows.append(item)

    trade = {
        "symbol": str(opened["symbol"]),
        "signal_ts": int(opened["signal_bar_close_ts"]),
        "entry_ts": entry_ts,
        "entry": entry_mid,
        "entry_execution_price": entry_exec,
        "exit_ts": exit_ts,
        "exit": exit_mid,
        "exit_execution_price": exit_exec,
        "side": side,
        "qty": float(opened["qty"]),
        "notional": float(opened["notional"]),
        "gross_bps": gross_bps,
        "fee_bps": fee_bps,
        "slippage_bps": slippage_bps,
        "funding_bps": funding_bps,
        "realized_cost_bps": fee_bps + slippage_bps + funding_bps,
        "net_bps": net_bps,
        "MFE_bps": mfe_bps,
        "MAE_bps": mae_bps,
        "reason": "TIME_STOP",
    }
    core: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA,
        "stage": "G5",
        "strategy_id": str(opened["strategy_id"]),
        "lane_id": str(opened["child_id"]),
        "child_id": str(opened["child_id"]),
        "trade_id": str(opened["trade_id"]),
        "source_receipt_sha256": stable({"source_signal_record_sha256": opened["source_signal_record_sha256"], "entry_depth": entry_depth["snapshot_sha256"], "exit_depth": exit_depth["snapshot_sha256"], "funding": funding_snapshot.get("snapshot_sha256"), "path": path.get("path_sha256")}),
        "economic_origin": "FORWARD_REAL",
        "production_grade": production_grade,
        "production_fail_closed_reasons": reasons,
        "trade": trade,
        "cost_provenance": {
            "point_in_time_at_trade": entry_depth.get("point_in_time") is True and exit_depth.get("point_in_time") is True,
            "entry_depth_snapshot_sha256": entry_depth.get("snapshot_sha256"),
            "exit_depth_snapshot_sha256": exit_depth.get("snapshot_sha256"),
            "reference_notional_usdt": float(opened["notional"]),
            "entry_delay_ms": int(opened["entry_delay_ms"]),
            "exit_delay_ms": max(0, exit_ts - int(opened["exit_due_ts"])),
        },
        "fee_provenance": {
            "point_in_time_at_trade": bool(fee_authority_sha),
            "authority_blob_sha": fee_authority_sha,
            "taker_fee_bps_one_way": float(fee_one_way_bps),
            "execution_assumption": "TAKER_BOTH_SIDES",
        },
        "funding_provenance": {
            "signed_settlement_lineage": funding_complete,
            "funding_snapshot_sha256": funding_snapshot.get("snapshot_sha256"),
            "settlement_rows": settlement_rows,
            "side_sign_semantics": "LONG_POSITIVE_RATE_COST_SHORT_INVERSE",
        },
        "execution_provenance": {
            "intrabar_order_observed": path_ok,
            "semantics": "TIME_STOP_ONLY_NO_CONDITIONAL_INTRABAR_EXIT; POINT_IN_TIME_ENTRY_EXIT_DEPTH_PLUS_5M_HOLDING_PATH",
            "path_interval": "5m",
            "path_bar_count": len(path.get("rows") or []),
            "path_sha256": path.get("path_sha256"),
            "entry_execution_price": entry_exec,
            "exit_execution_price": exit_exec,
            "actual_exchange_order": False,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    core["evidence_row_sha256"] = stable(core)
    return core


def validate_evidence_row(row: Mapping[str, Any]) -> None:
    if row.get("schema_version") != EVIDENCE_SCHEMA:
        raise RuntimeError("EVIDENCE_SCHEMA_MISMATCH")
    supplied = str(row.get("evidence_row_sha256") or "")
    core = dict(row); core.pop("evidence_row_sha256", None)
    if not supplied or supplied != stable(core):
        raise RuntimeError("EVIDENCE_HASH_MISMATCH")
    if row.get("selection_authority") is not False or row.get("promotion_authority") is not False:
        raise RuntimeError("EVIDENCE_AUTHORITY_ESCALATION")
    if row.get("execution_authority") != "NONE" or row.get("order_authority") != "BLOCKED" or row.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("EVIDENCE_EXECUTION_AUTHORITY_ESCALATION")


def merge_evidence(current: Sequence[Mapping[str, Any]], new_rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    merged = [dict(row) for row in current]
    known: set[str] = set()
    for row in merged:
        validate_evidence_row(row)
        sha = str(row["evidence_row_sha256"])
        if sha in known:
            raise RuntimeError("EVIDENCE_LEDGER_DUPLICATE_EXISTING")
        known.add(sha)
    appended = 0
    for raw in new_rows:
        row = dict(raw); validate_evidence_row(row)
        sha = str(row["evidence_row_sha256"])
        if sha in known:
            continue
        known.add(sha); merged.append(row); appended += 1
    return merged, appended


def process(
    *,
    source_rows: Sequence[Mapping[str, Any]],
    bridge_rows: list[dict[str, Any]],
    bridge_evidence: Sequence[Mapping[str, Any]],
    canonical_evidence: Sequence[Mapping[str, Any]],
    effective: Mapping[str, Any],
    cutover: Mapping[str, Any],
    stale: Mapping[str, Any],
    cost: Mapping[str, Any],
    provider: MarketProvider,
    current_ms: int,
    fee_authority_sha: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    validate_bridge_chain(bridge_rows)
    strategies = active_strategy_map(effective)
    reference_notional = float((cost.get("slippage_impact") or {}).get("reference_notional_usdt") or 0.0)
    fee_one_way = float((cost.get("fee") or {}).get("taker_fee_bps_one_way") or 0.0)
    if reference_notional <= 0 or fee_one_way <= 0:
        raise RuntimeError("COST_AUTHORITY_REFERENCE_NOTIONAL_OR_FEE_INVALID")
    if cost.get("state") != "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY":
        raise RuntimeError("COST_AUTHORITY_INVALID")

    activation = next((row for row in bridge_rows if row.get("kind") == "ACTIVATED"), None)
    if activation is None:
        bridge_event(bridge_rows, kind="ACTIVATED", payload={
            "activation_ts_ms": current_ms,
            "activation_ts_utc": iso_ms(current_ms),
            "source_state_rows_seen": len(source_rows),
            "preexisting_signals_consumed": 0,
            "historical_backfill": False,
            "formal_credit": 0,
        }, event_ts_ms=current_ms)
        status = {
            "schema_version": "zel.g5.forward_real_bridge_run.v1",
            "state": "ACTIVATED_FUTURE_ONLY_WAIT_NEXT_SIGNAL",
            "activation_ts_ms": current_ms,
            "new_opens": 0,
            "new_closes": 0,
            "new_production_grade_T": 0,
            "bridge_open_T": 0,
            "production_grade_T_total": sum(1 for row in bridge_evidence if row.get("production_grade") is True),
            "historical_backfill": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        }
        return bridge_rows, [dict(row) for row in bridge_evidence], [dict(row) for row in canonical_evidence], status

    activation_payload = activation.get("payload") if isinstance(activation.get("payload"), Mapping) else {}
    activation_ms = int(activation_payload.get("activation_ts_ms") or 0)
    if activation_ms <= 0:
        raise RuntimeError("ACTIVATION_TS_INVALID")

    opens, terminal = open_index(bridge_rows)
    new_evidence: list[dict[str, Any]] = []
    new_opens = 0
    new_closes = 0

    # Close already captured future-only bridge positions first.
    for tid, opened in sorted(opens.items(), key=lambda item: (int(item[1]["exit_due_ts"]), item[0])):
        if current_ms < int(opened["exit_due_ts"]):
            continue
        try:
            exit_depth = provider.depth(str(opened["symbol"]), float(opened["notional"]))
            funding_snapshot = provider.funding(str(opened["symbol"]))
            path = provider.path5m(str(opened["symbol"]), int(opened["entry_ts"]), int(exit_depth["observed_at_ms"]))
            row = evidence_row(
                opened=opened,
                exit_depth=exit_depth,
                funding_snapshot=funding_snapshot,
                path=path,
                fee_one_way_bps=fee_one_way,
                fee_authority_sha=fee_authority_sha,
                cutover_ready=cutover.get("production_ready") is True and cutover.get("clean_runner_authority") is True,
                stale_ready=stale.get("authority_created") is True and stale.get("data_stale_authority_allowed") is True,
            )
            new_evidence.append(row)
            bridge_event(bridge_rows, kind="CLOSED_PRODUCTION" if row["production_grade"] else "CLOSED_FAIL_CLOSED", payload={
                "trade_id": tid,
                "strategy_id": opened["strategy_id"],
                "child_id": opened["child_id"],
                "symbol": opened["symbol"],
                "production_grade": row["production_grade"],
                "production_fail_closed_reasons": row["production_fail_closed_reasons"],
                "evidence_row_sha256": row["evidence_row_sha256"],
                "net_bps": row["trade"]["net_bps"],
                "exit_ts": row["trade"]["exit_ts"],
            }, event_ts_ms=int(exit_depth["observed_at_ms"]))
            new_closes += 1
        except Exception as exc:
            bridge_event(bridge_rows, kind="CLOSE_RETRY_REQUIRED", payload={
                "trade_id": tid,
                "strategy_id": opened["strategy_id"],
                "child_id": opened["child_id"],
                "symbol": opened["symbol"],
                "error": f"{type(exc).__name__}:{exc}",
                "retryable": True,
                "formal_credit": 0,
            }, event_ts_ms=current_ms)

    # Rebuild index because some positions may have just closed.
    opens, terminal = open_index(bridge_rows)
    already_seen = set(opens) | terminal

    for signal in signal_rows(source_rows, activation_ms):
        tid = trade_id_for_signal(signal)
        if tid in already_seen:
            continue
        payload = signal.get("payload") if isinstance(signal.get("payload"), Mapping) else {}
        key = (str(payload.get("strategy_id") or ""), str(payload.get("child_id") or ""))
        cfg = strategies.get(key)
        if cfg is None:
            bridge_event(bridge_rows, kind="OPEN_REJECTED", payload={"trade_id": tid, "reason": "SIGNAL_CHILD_NOT_CURRENT_EFFECTIVE_OWNER", "strategy_id": key[0], "child_id": key[1], "symbol": payload.get("symbol"), "formal_credit": 0}, event_ts_ms=current_ms)
            already_seen.add(tid)
            continue
        if str(cfg.get("exit_rule")) != "time_stop" or int(cfg.get("max_hold_bars") or 0) <= 0:
            bridge_event(bridge_rows, kind="OPEN_REJECTED", payload={"trade_id": tid, "reason": "ONLY_FROZEN_TIME_STOP_SUPPORTED", "strategy_id": key[0], "child_id": key[1], "symbol": payload.get("symbol"), "formal_credit": 0}, event_ts_ms=current_ms)
            already_seen.add(tid)
            continue
        try:
            side = str(payload.get("side") or cfg.get("side") or "")
            depth = provider.depth(str(payload["symbol"]), reference_notional)
            entry_exec, _ = _entry_execution(depth, side)
            signal_close = int(payload["signal_bar_close_ts"])
            due = signal_close + int(cfg["max_hold_bars"]) * FOUR_HOURS_MS
            entry_ts = int(depth["observed_at_ms"])
            if entry_ts >= due:
                raise RuntimeError("SIGNAL_DISCOVERY_AFTER_TIME_STOP_DUE")
            opened = {
                "trade_id": tid,
                "strategy_id": key[0],
                "child_id": key[1],
                "symbol": str(payload["symbol"]),
                "side": side,
                "signal_bar_close_ts": signal_close,
                "source_signal_event_ts": str(signal.get("event_ts") or ""),
                "source_signal_record_sha256": str(signal.get("record_sha256") or ""),
                "entry_ts": entry_ts,
                "entry_depth": depth,
                "entry_execution_price": entry_exec,
                "entry_delay_ms": max(0, entry_ts - signal_close),
                "exit_due_ts": due,
                "max_hold_bars": int(cfg["max_hold_bars"]),
                "notional": reference_notional,
                "qty": reference_notional / entry_exec,
                "fee_authority_blob_sha": fee_authority_sha,
                "strategy_sha": cfg.get("strategy_sha"),
                "entry_sha": cfg.get("entry_sha"),
                "exit_sha": cfg.get("exit_sha"),
                "config_sha": cfg.get("config_sha"),
                "formal_credit": 0,
                "exchange_order_submitted": False,
                "execution_authority": "NONE",
                "order_authority": "BLOCKED",
                "live_trade_authority": "BLOCKED",
            }
            bridge_event(bridge_rows, kind="OPENED_PROVENANCE", payload=opened, event_ts_ms=entry_ts)
            already_seen.add(tid); new_opens += 1
        except Exception as exc:
            bridge_event(bridge_rows, kind="OPEN_REJECTED", payload={"trade_id": tid, "reason": f"ENTRY_PROVENANCE_CAPTURE_FAILED:{type(exc).__name__}:{exc}", "strategy_id": key[0], "child_id": key[1], "symbol": payload.get("symbol"), "formal_credit": 0}, event_ts_ms=current_ms)
            already_seen.add(tid)

    merged_bridge, bridge_appended = merge_evidence(bridge_evidence, new_evidence)
    merged_canonical, canonical_appended = merge_evidence(canonical_evidence, [row for row in new_evidence if row.get("production_grade") is True])
    open_after, _ = open_index(bridge_rows)
    total_prod = sum(1 for row in merged_bridge if row.get("production_grade") is True)
    status = {
        "schema_version": "zel.g5.forward_real_bridge_run.v1",
        "state": "PRODUCTION_GRADE_T_AVAILABLE" if total_prod > 0 else "WAIT_FUTURE_FORWARD_REAL_CLOSE",
        "activation_ts_ms": activation_ms,
        "activation_ts_utc": iso_ms(activation_ms),
        "source_state_rows_seen": len(source_rows),
        "eligible_post_activation_signals_seen": len(signal_rows(source_rows, activation_ms)),
        "new_opens": new_opens,
        "new_closes": new_closes,
        "bridge_open_T": len(open_after),
        "bridge_evidence_appended": bridge_appended,
        "canonical_production_rows_appended": canonical_appended,
        "new_production_grade_T": sum(1 for row in new_evidence if row.get("production_grade") is True),
        "production_grade_T_total": total_prod,
        "historical_backfill": False,
        "strategy_mutation": False,
        "threshold_mutation": False,
        "rr_mutation": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    return bridge_rows, merged_bridge, merged_canonical, status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--source-state", default=str(STATE_PATH))
    parser.add_argument("--bridge-state", default=str(BRIDGE_STATE_PATH))
    parser.add_argument("--bridge-ledger", default=str(BRIDGE_LEDGER_PATH))
    parser.add_argument("--canonical-ledger", default=str(CANONICAL_LEDGER_PATH))
    parser.add_argument("--out-dir", default="out")
    args = parser.parse_args()
    if args.self_test:
        contract = read_json(CONTRACT_PATH); validate_contract(contract)
        print("PASS_G5_FORWARD_REAL_BRIDGE_CONTRACT_SELF_TEST")
        return 0

    contract = read_json(CONTRACT_PATH); validate_contract(contract)
    effective = read_json(EFFECTIVE_PATH)
    cutover = read_json(CUTOVER_PATH)
    stale = read_json(STALE_PATH)
    cost = read_json(COST_PATH)
    source_rows = read_jsonl(Path(args.source_state))
    bridge_rows = read_jsonl(Path(args.bridge_state))
    bridge_evidence = read_jsonl(Path(args.bridge_ledger))
    canonical_evidence = read_jsonl(Path(args.canonical_ledger))
    provider = PublicBingXProvider()
    current = now_ms()
    bridge_rows, bridge_evidence, canonical_evidence, status = process(
        source_rows=source_rows,
        bridge_rows=bridge_rows,
        bridge_evidence=bridge_evidence,
        canonical_evidence=canonical_evidence,
        effective=effective,
        cutover=cutover,
        stale=stale,
        cost=cost,
        provider=provider,
        current_ms=current,
        fee_authority_sha=git_blob_sha(COST_PATH),
    )
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / "g5_forward_real_bridge_state_v1.jsonl", bridge_rows)
    write_jsonl(out / "g5_forward_real_evidence_ledger_v1.jsonl", bridge_evidence)
    write_jsonl(out / "g5_economic_evidence_ledger_v1.jsonl", canonical_evidence)
    status["generated_at_ms"] = current
    status["generated_at_utc"] = iso_ms(current)
    status["contract_blob_sha"] = git_blob_sha(CONTRACT_PATH)
    status["effective_contract_blob_sha"] = git_blob_sha(EFFECTIVE_PATH)
    status["cost_authority_blob_sha"] = git_blob_sha(COST_PATH)
    status["receipt_sha256"] = stable(status)
    write_json(out / "g5_forward_real_bridge_latest_v1.json", status)
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
