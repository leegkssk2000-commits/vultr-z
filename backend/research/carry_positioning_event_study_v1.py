from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "zel.carry_positioning.event_study.v1"
CONTRACT_SCHEMA = "zel.production_carry_positioning.v1"
FEATURE_SCHEMA = "zel.p3.prospective_native_feature_record.v1"
COVERAGE_SCHEMA = "zel.p3.prospective_native_coverage.v1"
SYMBOLS = ("BTC-USDT", "ETH-USDT")


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def finite(value: Any, label: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"CARRY_POSITIONING_NUMERIC_INVALID:{label}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"CARRY_POSITIONING_NUMERIC_NONFINITE:{label}")
    return out


def integer(value: Any, label: str) -> int:
    try:
        out = int(float(value))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"CARRY_POSITIONING_INTEGER_INVALID:{label}") from exc
    if out <= 0:
        raise RuntimeError(f"CARRY_POSITIONING_INTEGER_NONPOSITIVE:{label}")
    return out


def read_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise RuntimeError(f"CARRY_POSITIONING_HISTORY_MISSING:{path.name}")
    rows: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except Exception as exc:
            raise RuntimeError(f"CARRY_POSITIONING_HISTORY_JSON_INVALID:{path.name}:{line_no}") from exc
        if not isinstance(row, dict):
            raise RuntimeError(f"CARRY_POSITIONING_HISTORY_ROW_INVALID:{path.name}:{line_no}")
        rows.append(row)
    if not rows:
        raise RuntimeError(f"CARRY_POSITIONING_HISTORY_EMPTY:{path.name}")
    return rows


def validate_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    if contract.get("schema_version") != CONTRACT_SCHEMA:
        raise RuntimeError("CARRY_POSITIONING_CONTRACT_SCHEMA")
    if contract.get("family") != "carry_positioning":
        raise RuntimeError("CARRY_POSITIONING_CONTRACT_FAMILY")
    if contract.get("mode") != "PAPER":
        raise RuntimeError("CARRY_POSITIONING_CONTRACT_MODE")
    if contract.get("selection_authority") is not False or contract.get("promotion_authority") is not False:
        raise RuntimeError("CARRY_POSITIONING_CONTRACT_SELECTION_AUTHORITY")
    if contract.get("execution_authority") != "NONE" or contract.get("order_authority") != "BLOCKED":
        raise RuntimeError("CARRY_POSITIONING_CONTRACT_EXECUTION_AUTHORITY")
    mechanism = contract.get("mechanism")
    if not isinstance(mechanism, Mapping):
        raise RuntimeError("CARRY_POSITIONING_MECHANISM_MISSING")
    if mechanism.get("parameter_search") is not False or mechanism.get("numeric_signal_thresholds") != []:
        raise RuntimeError("CARRY_POSITIONING_PARAMETER_SEARCH_FORBIDDEN")
    if mechanism.get("event_anchor") != "native premiumIndex.nextFundingTime":
        raise RuntimeError("CARRY_POSITIONING_EVENT_ANCHOR_DRIFT")
    if mechanism.get("temporal_durability_split") != "FIRST_HALF_VS_SECOND_HALF_BY_ORDERED_NATIVE_FUNDING_EVENT_GROUP":
        raise RuntimeError("CARRY_POSITIONING_TEMPORAL_SPLIT_DRIFT")
    cost = contract.get("execution_cost_authority")
    if not isinstance(cost, Mapping) or int(cost.get("source_pull_request") or 0) != 570:
        raise RuntimeError("CARRY_POSITIONING_COST_AUTHORITY_MISSING")
    declared = finite(cost.get("round_trip_execution_cost_bps"), "round_trip_execution_cost_bps")
    derived = 2.0 * finite(cost.get("taker_fee_pct_one_way"), "taker_fee_pct_one_way") * 100.0 + 2.0 * finite(cost.get("slippage_floor_bps_one_way"), "slippage_floor_bps_one_way")
    if abs(declared - derived) > 1e-9:
        raise RuntimeError("CARRY_POSITIONING_COST_DERIVATION_MISMATCH")
    return dict(contract)


def validate_coverage(coverage: Mapping[str, Any], contract: Mapping[str, Any]) -> bool:
    if coverage.get("schema_version") != COVERAGE_SCHEMA:
        raise RuntimeError("CARRY_POSITIONING_COVERAGE_SCHEMA")
    required = integer(contract["coverage_contract"]["required_capture_span_ms"], "required_capture_span_ms")
    if integer(coverage.get("required_capture_span_ms"), "coverage.required_capture_span_ms") != required:
        raise RuntimeError("CARRY_POSITIONING_COVERAGE_SPAN_MISMATCH")
    if coverage.get("selection_authority") is not False or coverage.get("promotion_authority") is not False:
        raise RuntimeError("CARRY_POSITIONING_COVERAGE_AUTHORITY")
    if coverage.get("execution_authority") != "NONE" or coverage.get("order_authority") != "BLOCKED":
        raise RuntimeError("CARRY_POSITIONING_COVERAGE_EXECUTION")
    return coverage.get("basis_oi_duration_gate_pass") is True


def validate_feature_row(row: Mapping[str, Any], feature: str, symbol: str) -> tuple[int, dict[str, Any]]:
    if row.get("schema_version") != FEATURE_SCHEMA:
        raise RuntimeError(f"CARRY_POSITIONING_FEATURE_SCHEMA:{feature}:{symbol}")
    if row.get("feature") != feature or row.get("symbol") != symbol:
        raise RuntimeError(f"CARRY_POSITIONING_FEATURE_IDENTITY:{feature}:{symbol}")
    if row.get("prospective_only") is not True or row.get("historical_coverage_claim") is not False:
        raise RuntimeError(f"CARRY_POSITIONING_PROSPECTIVE_CONTRACT:{feature}:{symbol}")
    if row.get("signal_generation_enabled") is not False:
        raise RuntimeError(f"CARRY_POSITIONING_UPSTREAM_SIGNAL_AUTHORITY:{feature}:{symbol}")
    if row.get("execution_authority") != "NONE" or row.get("order_authority") != "BLOCKED":
        raise RuntimeError(f"CARRY_POSITIONING_UPSTREAM_EXECUTION_AUTHORITY:{feature}:{symbol}")
    collected = integer(row.get("collected_at_ms"), f"{feature}.{symbol}.collected_at_ms")
    sha = str(row.get("source_payload_sha256") or "")
    if len(sha) != 64:
        raise RuntimeError(f"CARRY_POSITIONING_UPSTREAM_SHA:{feature}:{symbol}")
    values = row.get("values")
    if not isinstance(values, dict):
        raise RuntimeError(f"CARRY_POSITIONING_VALUES_MISSING:{feature}:{symbol}")
    return collected, values


def paired_snapshots(history_dir: Path, symbol: str) -> list[dict[str, Any]]:
    compact = symbol.replace("-", "")
    premium_rows = read_ndjson(history_dir / f"premium_index__{compact}.ndjson")
    oi_rows = read_ndjson(history_dir / f"open_interest__{compact}.ndjson")
    premium: dict[int, dict[str, Any]] = {}
    oi: dict[int, dict[str, Any]] = {}
    for row in premium_rows:
        ts, values = validate_feature_row(row, "premium_index", symbol)
        if ts in premium:
            raise RuntimeError(f"CARRY_POSITIONING_DUPLICATE_PREMIUM_COLLECTION:{symbol}:{ts}")
        premium[ts] = values
    for row in oi_rows:
        ts, values = validate_feature_row(row, "open_interest", symbol)
        if ts in oi:
            raise RuntimeError(f"CARRY_POSITIONING_DUPLICATE_OI_COLLECTION:{symbol}:{ts}")
        oi[ts] = values
    common = sorted(set(premium) & set(oi))
    if len(common) != len(premium) or len(common) != len(oi):
        raise RuntimeError(f"CARRY_POSITIONING_PAIR_PARITY:{symbol}:{len(premium)}:{len(oi)}:{len(common)}")
    out: list[dict[str, Any]] = []
    for collected in common:
        p = premium[collected]
        o = oi[collected]
        mark = finite(p.get("markPrice"), f"{symbol}.markPrice")
        index = finite(p.get("indexPrice"), f"{symbol}.indexPrice")
        funding = finite(p.get("lastFundingRate"), f"{symbol}.lastFundingRate")
        oi_value = finite(o.get("openInterest"), f"{symbol}.openInterest")
        next_funding = integer(p.get("nextFundingTime"), f"{symbol}.nextFundingTime")
        if mark <= 0 or index <= 0 or oi_value < 0:
            raise RuntimeError(f"CARRY_POSITIONING_DOMAIN_INVALID:{symbol}:{collected}")
        if next_funding <= collected:
            raise RuntimeError(f"CARRY_POSITIONING_NEXT_FUNDING_NOT_FUTURE:{symbol}:{collected}:{next_funding}")
        out.append({
            "symbol": symbol,
            "collected_at_ms": collected,
            "next_funding_time_ms": next_funding,
            "mark_price": mark,
            "index_price": index,
            "funding_rate": funding,
            "basis_bps": (mark / index - 1.0) * 10000.0,
            "open_interest": oi_value,
        })
    return out


def funding_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["next_funding_time_ms"]), []).append(row)
    groups: list[dict[str, Any]] = []
    for event_ms in sorted(grouped):
        xs = sorted(grouped[event_ms], key=lambda r: int(r["collected_at_ms"]))
        groups.append({"event_ms": event_ms, "entry": xs[0], "exit": xs[-1], "snapshot_count": len(xs)})
    return groups


def make_trades(symbol: str, groups: list[dict[str, Any]], round_trip_cost_bps: float) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    for prev, cur in zip(groups, groups[1:]):
        entry = cur["entry"]
        exit_row = cur["exit"]
        oi_up = float(entry["open_interest"]) > float(prev["entry"]["open_interest"])
        funding = float(entry["funding_rate"])
        basis = float(entry["basis_bps"])
        crowding_sign = 1 if funding > 0 and basis > 0 and oi_up else (-1 if funding < 0 and basis < 0 and oi_up else 0)
        if crowding_sign == 0:
            continue
        side = -crowding_sign
        raw_bps = side * (float(exit_row["mark_price"]) / float(entry["mark_price"]) - 1.0) * 10000.0
        net_bps = raw_bps - round_trip_cost_bps
        trades.append({
            "symbol": symbol,
            "funding_event_ms": int(cur["event_ms"]),
            "entry_collected_at_ms": int(entry["collected_at_ms"]),
            "exit_collected_at_ms": int(exit_row["collected_at_ms"]),
            "side": "LONG" if side > 0 else "SHORT",
            "funding_rate_state": funding,
            "basis_bps_state": basis,
            "oi_delta": float(entry["open_interest"]) - float(prev["entry"]["open_interest"]),
            "raw_return_bps": raw_bps,
            "execution_cost_bps": round_trip_cost_bps,
            "net_return_bps": net_bps,
        })
    return trades


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    vals = [float(t["net_return_bps"]) for t in trades]
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for v in vals:
        equity += v
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "trade_count": len(vals),
        "net_return_sum_bps": sum(vals),
        "net_expectancy_bps": sum(vals) / len(vals) if vals else 0.0,
        "profit_factor": gp / gl if gl > 0 else (999.0 if gp > 0 else 0.0),
        "win_rate_pct": len(wins) / len(vals) * 100.0 if vals else 0.0,
        "max_drawdown_bps_additive": max_dd,
    }


def positive_gate(m: Mapping[str, Any]) -> bool:
    return bool(
        int(m.get("trade_count") or 0) > 0
        and float(m.get("net_return_sum_bps") or 0.0) > 0.0
        and float(m.get("net_expectancy_bps") or 0.0) > 0.0
        and float(m.get("profit_factor") or 0.0) >= 1.0
    )


def evaluate(history_dir: Path, coverage: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    cfg = validate_contract(contract)
    coverage_ready = validate_coverage(coverage, cfg)
    base: dict[str, Any] = {
        "schema_version": SCHEMA,
        "family": "carry_positioning",
        "strategy_id": str(cfg["strategy_id"]),
        "coverage_ready": coverage_ready,
        "required_capture_span_ms": int(cfg["coverage_contract"]["required_capture_span_ms"]),
        "parameter_search_performed": False,
        "numeric_signal_threshold_count": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "action": "hold",
    }
    if not coverage_ready:
        base.update({
            "state": "HOLD_CARRY_POSITIONING_HISTORY_COVERAGE_PENDING",
            "next": "WAIT_FOR_FROZEN_21D_PROSPECTIVE_COVERAGE",
            "trades": [],
        })
        base["receipt_sha256"] = stable_sha(base)
        return base

    round_trip_cost_bps = finite(cfg["execution_cost_authority"]["round_trip_execution_cost_bps"], "round_trip_execution_cost_bps")
    groups_by_symbol: dict[str, list[dict[str, Any]]] = {}
    all_event_times: set[int] = set()
    all_trades: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        groups = funding_groups(paired_snapshots(history_dir, symbol))
        groups_by_symbol[symbol] = groups
        all_event_times.update(int(g["event_ms"]) for g in groups)
        all_trades.extend(make_trades(symbol, groups, round_trip_cost_bps))
    event_times = sorted(all_event_times)
    if len(event_times) < 2:
        base.update({"state": "HOLD_CARRY_POSITIONING_EVENT_GROUPS_INSUFFICIENT", "next": "CONTINUE_PROSPECTIVE_CAPTURE", "trades": all_trades})
        base["receipt_sha256"] = stable_sha(base)
        return base
    split_index = len(event_times) // 2
    if split_index <= 0 or split_index >= len(event_times):
        raise RuntimeError("CARRY_POSITIONING_TEMPORAL_SPLIT_INVALID")
    second_start = event_times[split_index]
    first = [t for t in all_trades if int(t["funding_event_ms"]) < second_start]
    second = [t for t in all_trades if int(t["funding_event_ms"]) >= second_start]
    first_m = metrics(first)
    second_m = metrics(second)
    aggregate_m = metrics(sorted(all_trades, key=lambda t: (int(t["funding_event_ms"]), str(t["symbol"]))))
    by_symbol = {s: metrics([t for t in all_trades if t["symbol"] == s]) for s in SYMBOLS}
    first_pass = positive_gate(first_m)
    second_pass = positive_gate(second_m)
    aggregate_pass = positive_gate(aggregate_m)
    economic_candidate = bool(first_pass and second_pass and aggregate_pass)
    if economic_candidate:
        state = "PASS_CARRY_POSITIONING_EVENT_STUDY_CANDIDATE_AUTHORITY_BLOCKED"
        next_step = "BIND_RISK_DD_RETENTION_AUTHORITY_BEFORE_BOOTSTRAP_CANDIDATE"
    else:
        state = "REJECT_CARRY_POSITIONING_EVENT_STUDY_DURABILITY"
        next_step = "ROUTE_CHANGE_TO_NEXT_VERIFIED_ECONOMIC_FAMILY"
    base.update({
        "state": state,
        "next": next_step,
        "temporal_split": {
            "rule": "FIRST_HALF_VS_SECOND_HALF_BY_ORDERED_NATIVE_FUNDING_EVENT_GROUP",
            "unique_event_group_count": len(event_times),
            "second_half_start_event_ms": second_start,
            "first_half": first_m,
            "second_half": second_m,
            "first_half_pass": first_pass,
            "second_half_pass": second_pass,
        },
        "aggregate": aggregate_m,
        "aggregate_pass": aggregate_pass,
        "by_symbol": by_symbol,
        "economic_candidate": economic_candidate,
        "execution_cost_bps": round_trip_cost_bps,
        "event_group_count_by_symbol": {s: len(groups_by_symbol[s]) for s in SYMBOLS},
        "trade_count": len(all_trades),
        "trades": all_trades,
        "survivor_authority": False,
    })
    base["receipt_sha256"] = stable_sha(base)
    return base


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", type=Path, required=True)
    ap.add_argument("--coverage", type=Path, required=True)
    ap.add_argument("--contract", type=Path, default=Path("config/zel_production_carry_positioning_v1.json"))
    ap.add_argument("--out", type=Path, required=True)
    ns = ap.parse_args()
    coverage = json.loads(ns.coverage.read_text(encoding="utf-8"))
    contract = json.loads(ns.contract.read_text(encoding="utf-8"))
    result = evaluate(ns.history_dir, coverage, contract)
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "coverage_ready": result["coverage_ready"],
        "economic_candidate": result.get("economic_candidate", False),
        "trade_count": result.get("trade_count", 0),
        "next": result.get("next"),
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
