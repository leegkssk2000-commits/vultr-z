from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

UTC = timezone.utc
MAX_CONTEXT_AGE_SEC = 180.0


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_time(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000.0
        return number
    text = str(value).strip()
    if not text:
        return None
    try:
        return parse_time(float(text))
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def extract_positions(*payloads: Mapping[str, Any]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        for item in walk(payload):
            position_id = str(item.get("position_id") or "").strip()
            symbol = str(item.get("symbol") or "").strip().upper()
            entry_epoch = parse_time(
                item.get("entry_epoch")
                or item.get("entry_ts")
                or item.get("opened_at")
            )
            if not position_id or not symbol or entry_epoch is None:
                continue
            found.setdefault(position_id, dict(item))
    return list(found.values())


def load_jsonl(path: Path, limit: int = 20_000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def context_before_entry(
    rows: list[dict[str, Any]],
    symbol: str,
    entry_epoch: float,
) -> tuple[dict[str, Any] | None, float | None]:
    candidates: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        if str(row.get("symbol") or "").upper() != symbol:
            continue
        epoch = finite(row.get("bar_epoch"))
        if epoch is None:
            epoch = parse_time(row.get("bar_ts") or row.get("generated_at"))
        if epoch is None or epoch > entry_epoch:
            continue
        candidates.append((epoch, row))
    if not candidates:
        return None, None
    epoch, row = max(candidates, key=lambda item: item[0])
    age = entry_epoch - epoch
    if age < 0 or age > MAX_CONTEXT_AGE_SEC:
        return None, age
    return row, age


def read_existing_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("position_id"):
            ids.add(str(row["position_id"]))
    return ids


def append_rows(path: Path, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    appended = 0
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        existing: set[str] = set()
        for line in handle:
            try:
                prior = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(prior, dict) and prior.get("position_id"):
                existing.add(str(prior["position_id"]))
        handle.seek(0, 2)
        for row in rows:
            position_id = str(row["position_id"])
            if position_id in existing:
                continue
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            existing.add(position_id)
            appended += 1
        handle.flush()
    return appended


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def derive_regime(context: Mapping[str, Any]) -> str | None:
    direction = str(context.get("trend_direction") or "").lower()
    strength = finite(context.get("trend_strength"))
    if strength is None:
        return None
    if strength < 1.0:
        return "range"
    if direction in {"long", "short"}:
        return f"trend_{direction}"
    return "transition"


def build_capture(
    position: Mapping[str, Any],
    context: Mapping[str, Any] | None,
    context_age_sec: float | None,
    execution: Mapping[str, Any],
    activation: Mapping[str, Any],
) -> dict[str, Any]:
    position_id = str(position["position_id"])
    entry_epoch = parse_time(
        position.get("entry_epoch")
        or position.get("entry_ts")
        or position.get("opened_at")
    )
    if entry_epoch is None:
        raise RuntimeError(f"ENTRY_TIME_MISSING:{position_id}")

    entry_price = finite(position.get("entry_price") or position.get("entry"))
    stop_price = finite(position.get("stop_price") or position.get("sl"))
    target_price = finite(position.get("take_profit_price") or position.get("tp"))
    qty = finite(position.get("qty"))

    target_distance_bps = None
    stop_distance_bps = None
    planned_target_r = None
    requested_notional = None

    if entry_price not in (None, 0.0):
        if target_price is not None:
            target_distance_bps = abs(target_price - entry_price) / entry_price * 10_000.0
        if stop_price is not None:
            stop_distance_bps = abs(entry_price - stop_price) / entry_price * 10_000.0
        if target_distance_bps is not None and stop_distance_bps not in (None, 0.0):
            planned_target_r = target_distance_bps / stop_distance_bps
        if qty is not None:
            requested_notional = abs(qty * entry_price)

    entry_features = position.get("entry_features")
    if not isinstance(entry_features, dict):
        entry_features = {}
    context = dict(context or {})

    atr_pct = finite(context.get("atr_pct"))
    realized_volatility_pct = finite(context.get("realized_volatility_pct"))
    funding_8h_pct = finite(context.get("funding_8h_pct"))

    unresolved = [
        "method",
        "method_subtype",
        "entry_style",
        "hold_horizon",
        "risk_mode",
        "available_depth_usdt",
        "market_impact_bps",
        "latency_adverse_selection_bps",
        "position_size_pct",
        "leverage",
        "dd_day_pct",
        "dd_total_pct",
        "liq_buffer_pct",
    ]
    if funding_8h_pct is None:
        unresolved.append("funding_8h_bps")

    capture_id = hashlib.sha256(
        json.dumps(
            {
                "position_id": position_id,
                "entry_epoch": entry_epoch,
                "symbol": position.get("symbol"),
                "strategy_id": position.get("strategy_id"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    return {
        "schema": "q4r3_exact25_preentry_method_context_v1",
        "capture_id": capture_id,
        "captured_at": now_iso(),
        "activation_at": activation.get("activation_at"),
        "position_id": position_id,
        "strategy_id": position.get("strategy_id"),
        "owner_sha256": position.get("owner_sha256"),
        "symbol": str(position.get("symbol") or "").upper(),
        "side": position.get("side"),
        "signal_ts_epoch_ms": int(entry_epoch * 1000),
        "reference_price": entry_price,
        "planned_stop_price": stop_price,
        "planned_target_price": target_price,
        "expected_gross_edge_bps": target_distance_bps,
        "expected_stop_distance_bps": stop_distance_bps,
        "planned_target_r": planned_target_r,
        "requested_notional_usdt": requested_notional,
        "initial_risk_usdt": finite(position.get("initial_risk_usdt")),
        "fee_bps_round_trip": execution.get("fee_bps_round_trip"),
        "slippage_bps": execution.get("slippage_bps_round_trip"),
        "execution_cost_provenance": execution.get("interpretation"),
        "spread_bps": finite(context.get("spread_bps")),
        "funding_8h_bps": funding_8h_pct * 100.0 if funding_8h_pct is not None else None,
        "realized_vol_bps": realized_volatility_pct * 100.0 if realized_volatility_pct is not None else None,
        "atr_bps": atr_pct * 100.0 if atr_pct is not None else None,
        "regime": derive_regime(context),
        "session_bucket": entry_features.get("session_window") or context.get("session_bucket"),
        "market_context_snapshot_id": context.get("snapshot_id"),
        "market_context_bar_epoch": finite(context.get("bar_epoch")),
        "market_context_age_sec": context_age_sec,
        "market_context_join_rule": "same_symbol_latest_bar_epoch_lte_entry_maximum_age_180s",
        "htf_bias": entry_features.get("htf_bias"),
        "swing_sequence": entry_features.get("swing_sequence"),
        "premium_discount_side": entry_features.get("premium_discount_side"),
        "ote_depth": entry_features.get("ote_depth"),
        "ltf_reversal_confirm": entry_features.get("ltf_reversal_confirm"),
        "invalidation_swing_distance_pct": entry_features.get("invalidation_swing_distance_pct"),
        "method": None,
        "method_subtype": None,
        "method_neutral": True,
        "six_profile_projection_pending": True,
        "projection_contract_complete": False,
        "unresolved_fields": sorted(set(unresolved)),
        "historical_backfill": False,
        "observer_only": True,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
    }


def run(args: argparse.Namespace) -> int:
    activation = load_object(args.activation)
    execution = load_object(args.execution_contract)
    open_payload = load_object(args.open_positions)
    state_payload = load_object(args.producer_state)

    activation_epoch = finite(activation.get("activation_epoch"))
    if activation_epoch is None:
        raise RuntimeError("ACTIVATION_EPOCH_MISSING")

    positions = extract_positions(open_payload, state_payload)
    contexts = load_jsonl(args.market_context)
    existing = read_existing_ids(args.ledger)

    candidates: list[dict[str, Any]] = []
    pre_activation_ignored = 0
    context_joined = 0
    context_missing = 0

    for position in positions:
        position_id = str(position["position_id"])
        if position_id in existing:
            continue
        entry_epoch = parse_time(
            position.get("entry_epoch")
            or position.get("entry_ts")
            or position.get("opened_at")
        )
        if entry_epoch is None:
            continue
        if entry_epoch < activation_epoch:
            pre_activation_ignored += 1
            continue
        symbol = str(position.get("symbol") or "").upper()
        context, context_age = context_before_entry(contexts, symbol, entry_epoch)
        if context is None:
            context_missing += 1
        else:
            context_joined += 1
        candidates.append(build_capture(position, context, context_age, execution, activation))

    appended = append_rows(args.ledger, candidates)
    total_captured = len(read_existing_ids(args.ledger))
    verdict = (
        "WAITING_FOR_FIRST_POST_ACTIVATION_OPEN"
        if total_captured == 0
        else "CAPTURING_FUTURE_PREENTRY_CONTEXT"
    )

    status = {
        "schema": "q4r3_exact25_preentry_method_context_capture_status_v1",
        "state": "HEALTHY",
        "verdict": verdict,
        "updated_at": now_iso(),
        "activation_at": activation.get("activation_at"),
        "formal_baseline_rows": activation.get("formal_baseline_rows"),
        "visible_position_count": len(positions),
        "pre_activation_ignored_count": pre_activation_ignored,
        "eligible_position_count": len(candidates),
        "new_capture_count": appended,
        "capture_count": total_captured,
        "market_context_join_count": context_joined,
        "market_context_missing_count": context_missing,
        "method_neutral": True,
        "six_profile_projection_enabled": False,
        "historical_backfill_allowed": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "order_authority": "blocked",
        "execution_authority": "none",
        "action": "hold",
        "next_action": "ACCUMULATE_POST_ACTIVATION_OPEN_CLOSE_PAIRS_THEN_BUILD_SIX_PROFILE_PROJECTION",
    }
    atomic_json(args.status, status)
    print(json.dumps(status, ensure_ascii=False, sort_keys=True))
    return 0


def self_test() -> int:
    context = {
        "symbol": "BTCUSDT",
        "bar_epoch": 100.0,
        "atr_pct": 1.0,
        "realized_volatility_pct": 2.0,
        "trend_direction": "long",
        "trend_strength": 1.5,
    }
    selected, age = context_before_entry([context], "BTCUSDT", 120.0)
    assert selected == context
    assert age == 20.0
    assert derive_regime(context) == "trend_long"
    with tempfile.TemporaryDirectory() as temporary:
        ledger = Path(temporary) / "capture.jsonl"
        row = {"position_id": "p1", "value": 1}
        assert append_rows(ledger, [row]) == 1
        assert append_rows(ledger, [row]) == 0
    print("PREENTRY_METHOD_CONTEXT_SELF_TEST_PASS")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--activation", type=Path)
    parser.add_argument("--execution-contract", type=Path)
    parser.add_argument("--open-positions", type=Path)
    parser.add_argument("--producer-state", type=Path)
    parser.add_argument("--market-context", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--status", type=Path)
    args = parser.parse_args()
    if not args.self_test:
        for key in (
            "activation",
            "execution_contract",
            "open_positions",
            "producer_state",
            "market_context",
            "ledger",
            "status",
        ):
            if getattr(args, key) is None:
                parser.error(f"--{key.replace('_', '-')} required")
    return args


if __name__ == "__main__":
    arguments = parse_args()
    raise SystemExit(self_test() if arguments.self_test else run(arguments))
