from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

FEE_TYPE_HINTS = ("fee", "commission", "trading fee", "transaction fee")
FUNDING_TYPE_HINTS = ("funding", "fund fee")
PNL_TYPE_HINTS = ("pnl", "realized", "close profit", "settlement")
LIQUIDATION_TYPE_HINTS = ("liquidation", "insurance_clear", "forced liquidation")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(dict(payload), handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        temp = Path(handle.name)
    temp.replace(path)


def safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_epoch_ms(value: Any) -> float | None:
    if value is None:
        return None
    number = safe_float(value)
    if number is not None:
        if number < 10_000_000_000:
            number *= 1000.0
        return number
    try:
        text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(text).timestamp() * 1000.0
    except Exception:
        return None


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * pct
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def rows_from(payload: Mapping[str, Any], keys: Iterable[str]) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    history = payload.get("history")
    if isinstance(history, dict):
        for key in keys:
            value = history.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def type_text(row: Mapping[str, Any]) -> str:
    return " ".join(str(row.get(key) or "") for key in ("type", "incomeType", "category", "businessType", "remark", "status")).lower()


def amount_value(row: Mapping[str, Any]) -> float | None:
    for key in ("amount", "income", "value", "realizedPnl", "realisedPnl", "pnl", "fee", "commission"):
        number = safe_float(row.get(key))
        if number is not None:
            return number
    return None


def commission_rates(payload: Mapping[str, Any]) -> dict[str, float | None]:
    commission = payload.get("commission")
    if not isinstance(commission, dict):
        history = payload.get("history")
        commission = history.get("commission") if isinstance(history, dict) else None
    commission = commission if isinstance(commission, dict) else {}
    def rate(*keys: str) -> float | None:
        for key in keys:
            value = safe_float(commission.get(key))
            if value is not None:
                return value
        return None
    return {
        "maker_rate": rate("makerCommissionRate", "makerFeeRate", "maker_rate"),
        "taker_rate": rate("takerCommissionRate", "takerFeeRate", "taker_rate"),
    }


def order_metrics(orders: list[dict[str, Any]]) -> dict[str, Any]:
    slippage_bps: list[float] = []
    first_fill_latency_ms: list[float] = []
    final_fill_latency_ms: list[float] = []
    partial_count = rejected_count = filled_count = 0
    for row in orders:
        side = str(row.get("side") or row.get("positionSide") or "").lower()
        requested = next((safe_float(row.get(key)) for key in ("requested_price", "price", "orderPrice") if safe_float(row.get(key)) is not None), None)
        average = next((safe_float(row.get(key)) for key in ("average_fill_price", "avgPrice", "averagePrice", "fillPrice") if safe_float(row.get(key)) is not None), None)
        if requested and average and requested > 0:
            raw = (average - requested) / requested * 10_000.0
            adverse = raw if side in {"buy", "long"} else -raw
            slippage_bps.append(adverse)
        created = next((parse_epoch_ms(row.get(key)) for key in ("order_created_at", "createTime", "createdAt", "time") if parse_epoch_ms(row.get(key)) is not None), None)
        first_fill = next((parse_epoch_ms(row.get(key)) for key in ("first_fill_at", "firstFillTime", "fillTime") if parse_epoch_ms(row.get(key)) is not None), None)
        final_fill = next((parse_epoch_ms(row.get(key)) for key in ("final_fill_at", "updateTime", "filledAt") if parse_epoch_ms(row.get(key)) is not None), None)
        if created is not None and first_fill is not None and first_fill >= created:
            first_fill_latency_ms.append(first_fill - created)
        if created is not None and final_fill is not None and final_fill >= created:
            final_fill_latency_ms.append(final_fill - created)
        status = str(row.get("status") or row.get("orderStatus") or "").lower()
        partials = safe_float(row.get("partial_fill_count"))
        if (partials is not None and partials > 0) or "partial" in status:
            partial_count += 1
        if any(token in status for token in ("reject", "failed", "expired")):
            rejected_count += 1
        if any(token in status for token in ("filled", "closed", "complete")):
            filled_count += 1
    return {
        "order_count": len(orders),
        "filled_order_count": filled_count,
        "partial_order_count": partial_count,
        "rejected_order_count": rejected_count,
        "slippage_sample_count": len(slippage_bps),
        "slippage_bps_median": statistics.median(slippage_bps) if slippage_bps else None,
        "slippage_bps_p75": percentile(slippage_bps, 0.75),
        "slippage_bps_p95": percentile(slippage_bps, 0.95),
        "first_fill_latency_sample_count": len(first_fill_latency_ms),
        "first_fill_latency_ms_median": statistics.median(first_fill_latency_ms) if first_fill_latency_ms else None,
        "first_fill_latency_ms_p95": percentile(first_fill_latency_ms, 0.95),
        "final_fill_latency_sample_count": len(final_fill_latency_ms),
        "final_fill_latency_ms_median": statistics.median(final_fill_latency_ms) if final_fill_latency_ms else None,
        "final_fill_latency_ms_p95": percentile(final_fill_latency_ms, 0.95),
    }


def calibrate(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("INPUT_JSON_OBJECT_REQUIRED")
    transactions = rows_from(payload, ("transactions", "income", "statements", "rows"))
    orders = rows_from(payload, ("orders", "fills", "trade_history"))
    rates = commission_rates(payload)

    fee = funding = realized = 0.0
    fee_count = funding_count = realized_count = liquidation_count = 0
    for row in transactions:
        text = type_text(row)
        amount = amount_value(row)
        if amount is None:
            continue
        if any(token in text for token in LIQUIDATION_TYPE_HINTS):
            liquidation_count += 1
        if any(token in text for token in FUNDING_TYPE_HINTS):
            funding += amount
            funding_count += 1
        elif any(token in text for token in FEE_TYPE_HINTS):
            fee += amount
            fee_count += 1
        elif any(token in text for token in PNL_TYPE_HINTS):
            realized += amount
            realized_count += 1

    orders_result = order_metrics(orders)
    has_fee = fee_count > 0 or rates["maker_rate"] is not None or rates["taker_rate"] is not None
    has_slippage = orders_result["slippage_sample_count"] > 0
    has_latency = orders_result["first_fill_latency_sample_count"] > 0
    has_fill_quality = has_slippage and has_latency
    if has_fill_quality:
        coverage = "PRIVATE_FILL_COST_AND_LATENCY_OBSERVED"
    elif has_fee:
        coverage = "OBSERVED_FEE_FUNDING_ONLY"
    else:
        coverage = "HOLD_INSUFFICIENT_EXECUTION_EVIDENCE"

    candidate = {
        "maker_rate": rates["maker_rate"],
        "taker_rate": rates["taker_rate"],
        "slippage_bps_median": orders_result["slippage_bps_median"],
        "slippage_bps_p75": orders_result["slippage_bps_p75"],
        "slippage_bps_p95": orders_result["slippage_bps_p95"],
        "first_fill_latency_ms_median": orders_result["first_fill_latency_ms_median"],
        "first_fill_latency_ms_p95": orders_result["first_fill_latency_ms_p95"],
        "final_fill_latency_ms_median": orders_result["final_fill_latency_ms_median"],
        "final_fill_latency_ms_p95": orders_result["final_fill_latency_ms_p95"],
        "observed_fee_total_usdt": fee,
        "observed_funding_total_usdt": funding,
        "observed_realized_pnl_usdt": realized,
        "observed_net_after_cost_usdt": realized + fee + funding,
    }
    return {
        "schema_version": "zel.bingx.execution_calibration.receipt.v1",
        "generated_at": now_iso(),
        "state": "PASS_BINGX_EXECUTION_CALIBRATION_EVIDENCE" if has_fee else "HOLD_BINGX_EXECUTION_CALIBRATION_INSUFFICIENT",
        "source_sha256": sha256_path(path),
        "raw_order_ids_included": False,
        "api_credentials_included": False,
        "coverage": coverage,
        "transaction_count": len(transactions),
        "fee_record_count": fee_count,
        "funding_record_count": funding_count,
        "realized_pnl_record_count": realized_count,
        "liquidation_count": liquidation_count,
        "orders": orders_result,
        "candidate_cost_model": candidate,
        "unknowns": {
            "user_specific_slippage": not has_slippage,
            "user_specific_latency": not has_latency,
            "partial_fill_rate": orders_result["order_count"] == 0,
            "rejection_rate": orders_result["order_count"] == 0,
            "attached_stop_loss_coverage": True,
        },
        "application_allowed": False,
        "application_requires": [
            "SSOT_COST_MODEL_REVIEW",
            "DATA_B_COST_STRESS",
            "W2_FORWARD",
            "W3_DURABILITY",
        ],
        "selection_authority": False,
        "promotion_authority": False,
        "runtime_binding_allowed": False,
        "shadow_start_allowed": False,
        "paper_start_allowed": False,
        "live_enabled": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "input.json"
        payload = {
            "commission": {"makerCommissionRate": 0.0002, "takerCommissionRate": 0.0005},
            "transactions": [
                {"type": "REALIZED_PNL", "amount": 10.0},
                {"type": "TRADING_FEE", "amount": -1.0},
                {"type": "FUNDING_FEE", "amount": -0.2},
            ],
            "orders": [
                {"side": "BUY", "requested_price": 100.0, "average_fill_price": 100.1, "order_created_at": 1000, "first_fill_at": 1001, "final_fill_at": 1002, "status": "FILLED"},
                {"side": "SELL", "requested_price": 101.0, "average_fill_price": 100.9, "order_created_at": 2000, "first_fill_at": 2001, "final_fill_at": 2001.5, "status": "FILLED"},
            ],
        }
        path.write_text(json.dumps(payload))
        result = calibrate(path)
        assert result["state"] == "PASS_BINGX_EXECUTION_CALIBRATION_EVIDENCE"
        assert result["coverage"] == "PRIVATE_FILL_COST_AND_LATENCY_OBSERVED"
        assert abs(result["candidate_cost_model"]["observed_net_after_cost_usdt"] - 8.8) < 1e-12
        assert result["application_allowed"] is False
    print(json.dumps({"state": "PASS_SELF_TEST"}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.input or not args.out:
        parser.error("input and out are required")
    result = calibrate(Path(args.input))
    atomic_json(Path(args.out), result)
    print(json.dumps({"state": result["state"], "coverage": result["coverage"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
