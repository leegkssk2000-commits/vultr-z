from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DAY_MS = 86_400_000
START_UTC = datetime(2026, 1, 1, tzinfo=timezone.utc)


def load_base(path: str):
    spec = importlib.util.spec_from_file_location("zel_bingx_private_history_fetch_v1", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("BASE_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def timestamp_ms(item: dict[str, Any]) -> int | None:
    for key in (
        "time", "timestamp", "transactTime", "updateTime", "createTime",
        "orderTime", "fillTime", "tradeTime", "executedTime",
    ):
        value = item.get(key)
        try:
            numeric = int(float(value))
        except (TypeError, ValueError):
            continue
        if numeric < 10_000_000_000:
            numeric *= 1000
        return numeric
    return None


def month_of(item: dict[str, Any]) -> str:
    value = timestamp_ms(item)
    if value is None:
        return "unknown"
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m")


def first_value(item: dict[str, Any], keys: tuple[str, ...], default: str = "unknown") -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def summarize(orders: list[dict[str, Any]], fills: list[dict[str, Any]], income: list[dict[str, Any]], commission: Any, errors: list[dict[str, Any]], start_ms: int, end_ms: int, credential_meta: dict[str, Any]) -> dict[str, Any]:
    months: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "orders": 0,
        "fills": 0,
        "income_entries": 0,
        "symbols": set(),
        "realized_pnl_usdt": 0.0,
        "commission_usdt": 0.0,
        "funding_usdt": 0.0,
        "other_income_usdt": 0.0,
    })
    status = Counter()
    order_type = Counter()
    side = Counter()
    position_side = Counter()
    leverage = Counter()
    symbols = Counter()
    income_types = Counter()

    for row in orders:
        month = month_of(row)
        months[month]["orders"] += 1
        symbol = first_value(row, ("symbol", "contract", "currency"))
        months[month]["symbols"].add(symbol)
        symbols[symbol] += 1
        status[first_value(row, ("status", "orderStatus", "state"))] += 1
        order_type[first_value(row, ("type", "orderType"))] += 1
        side[first_value(row, ("side",))] += 1
        position_side[first_value(row, ("positionSide", "position_side"))] += 1
        lev = first_value(row, ("leverage",), default="unknown")
        leverage[lev] += 1

    for row in fills:
        month = month_of(row)
        months[month]["fills"] += 1
        symbol = first_value(row, ("symbol", "contract", "currency"))
        months[month]["symbols"].add(symbol)
        symbols[symbol] += 1

    for row in income:
        month = month_of(row)
        months[month]["income_entries"] += 1
        symbol = first_value(row, ("symbol", "contract", "currency"))
        months[month]["symbols"].add(symbol)
        symbols[symbol] += 1
        kind = first_value(row, ("incomeType", "type", "businessType")).upper()
        income_types[kind] += 1
        amount = number(row.get("income", row.get("amount", row.get("value", 0))))
        if any(token in kind for token in ("REALIZED", "PNL", "PROFIT")):
            months[month]["realized_pnl_usdt"] += amount
        elif any(token in kind for token in ("COMMISSION", "FEE")):
            months[month]["commission_usdt"] += amount
        elif "FUND" in kind:
            months[month]["funding_usdt"] += amount
        else:
            months[month]["other_income_usdt"] += amount

    normalized_months = {}
    for month in sorted(months):
        row = months[month]
        normalized_months[month] = {
            **{key: value for key, value in row.items() if key != "symbols"},
            "symbols": sorted(value for value in row["symbols"] if value != "unknown"),
        }

    all_timestamps = [value for value in (timestamp_ms(row) for row in orders + fills + income) if value is not None]
    return {
        "schema_version": "zel.bingx.private_history.sanitized_summary.v1",
        "state": "PASS_BINGX_HISTORY_SINCE_2026_READ_ONLY" if not errors else "HOLD_BINGX_HISTORY_SINCE_2026_PARTIAL_ERRORS",
        "read_only": True,
        "raw_private_records_included": False,
        "order_ids_included": False,
        "api_credentials_included": False,
        "requested_start_utc": datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat(),
        "requested_end_utc": datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).isoformat(),
        "first_record_utc": datetime.fromtimestamp(min(all_timestamps) / 1000, tz=timezone.utc).isoformat() if all_timestamps else None,
        "last_record_utc": datetime.fromtimestamp(max(all_timestamps) / 1000, tz=timezone.utc).isoformat() if all_timestamps else None,
        "counts": {
            "orders": len(orders),
            "fills": len(fills),
            "income_entries": len(income),
            "request_errors": len(errors),
        },
        "monthly": normalized_months,
        "distributions": {
            "symbols": dict(symbols.most_common()),
            "order_status": dict(status.most_common()),
            "order_type": dict(order_type.most_common()),
            "side": dict(side.most_common()),
            "position_side": dict(position_side.most_common()),
            "leverage": dict(leverage.most_common()),
            "income_type": dict(income_types.most_common()),
        },
        "commission_rate": commission,
        "credential": credential_meta,
        "errors": errors,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-client", required=True)
    parser.add_argument("--raw-out", required=True)
    parser.add_argument("--summary-out", required=True)
    args = parser.parse_args()
    base = load_base(args.base_client)
    candidates = base.discover_candidates()
    validation = []
    selected = None
    commission = None
    for candidate in candidates:
        try:
            commission = base.signed_request(candidate["key"], candidate["secret"], base.ALLOWED["commission"], {})
            selected = candidate
            validation.append({"fingerprint": candidate["fingerprint"], "source_type": candidate["source_type"], "valid": True})
            break
        except Exception as exc:
            validation.append({"fingerprint": candidate["fingerprint"], "source_type": candidate["source_type"], "valid": False, "error": base.safe_error(exc, candidate["key"], candidate["secret"])})
    if selected is None:
        summary = {
            "schema_version": "zel.bingx.private_history.sanitized_summary.v1",
            "state": "HOLD_BINGX_VALID_CREDENTIAL_NOT_FOUND",
            "credential_candidate_count": len(candidates),
            "credential_validation": validation,
            "read_only": True,
            "raw_private_records_included": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold",
        }
        Path(args.summary_out).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        Path(args.raw_out).write_text(json.dumps(summary, separators=(",", ":")) + "\n")
        return 0

    key = selected["key"]
    secret = selected["secret"]
    start_ms = int(START_UTC.timestamp() * 1000)
    end_ms = int(time.time() * 1000)
    cursor = start_ms
    orders: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    income: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    targets = {"orders": orders, "fills": fills, "income": income}
    while cursor < end_ms:
        stop = min(cursor + DAY_MS - 1, end_ms)
        calls = (
            ("orders", base.ALLOWED["orders"], {"currency": "USDT", "startTime": cursor, "endTime": stop, "limit": 1000}),
            ("fills", base.ALLOWED["fills"], {"currency": "USDT", "tradingUnit": "COIN", "startTs": cursor, "endTs": stop}),
            ("income", base.ALLOWED["income"], {"startTime": cursor, "endTime": stop, "limit": 1000}),
        )
        for name, path, params in calls:
            try:
                targets[name].extend(base.rows(base.signed_request(key, secret, path, params)))
            except Exception as exc:
                errors.append({"endpoint": name, "start": cursor, "end": stop, "error": base.safe_error(exc, key, secret)})
            time.sleep(0.24)
        cursor = stop + 1

    clean_orders = base.deduplicate(orders, ("orderID", "orderId", "clientOrderId"))
    clean_fills = base.deduplicate(fills, ("tradeId", "fillId", "orderId"))
    clean_income = base.deduplicate(income, ("tranId", "tradeId", "time"))
    credential_meta = {
        "candidate_count": len(candidates),
        "selected_fingerprint": selected["fingerprint"],
        "selected_source_type": selected["source_type"],
        "values_exposed": False,
    }
    raw = {
        "schema_version": "zel.bingx.private_history.raw.since_2026.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "start_utc": START_UTC.isoformat(),
        "credential": credential_meta,
        "orders": clean_orders,
        "fills": clean_fills,
        "income": clean_income,
        "commission": commission,
        "errors": errors,
        "write_endpoint_called": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    summary = summarize(clean_orders, clean_fills, clean_income, commission, errors, start_ms, end_ms, credential_meta)
    Path(args.raw_out).write_text(json.dumps(raw, ensure_ascii=False, separators=(",", ":")) + "\n")
    Path(args.summary_out).write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"state": summary["state"], "counts": summary.get("counts", {}), "start": START_UTC.isoformat()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
