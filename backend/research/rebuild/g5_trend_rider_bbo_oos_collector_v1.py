#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import trend_rider_transition_freshness_child_policy_v1 as transition_policy
from backend.research.rebuild import trend_rider_wr80_us_chase_cooling_child_policy_v1 as frozen_parent_policy

ROOT = Path(__file__).resolve().parents[3]
STATE_PATH = ROOT / "backend/research/rebuild/g5_trend_rider_bbo_oos_state_v1.json"
EVENTS_PATH = ROOT / "backend/research/rebuild/g5_trend_rider_bbo_oos_events_v1.jsonl"
COST_PATH = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
TRANSITION_POLICY_PATH = ROOT / "backend/research/rebuild/trend_rider_transition_freshness_child_policy_v1.py"

SCHEMA = "zel.g5.trend_rider.bbo_oos_event.v1"
STATE_SCHEMA = "zel.g5.trend_rider.bbo_oos_state.v1"
STATUS_SCHEMA = "zel.g5.trend_rider.bbo_oos_status.v1"
PARENT_IDENTITY = "TREND_RIDER_WR8125_CHASE_COOLING_FROZEN_PARENT"
ARCHITECTURE_ID = "TR_US_BBO_IMBALANCE_CONFIRM_V1"
SYMBOLS = ("BTC-USDT", "ETH-USDT")
HOUR_MS = 3_600_000
AUTHORITY = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "formal_credit": 0,
}


def now_ms() -> int:
    return int(time.time() * 1000)


def stable(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=str).encode("utf-8")
    ).hexdigest()


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
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


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(dict(row), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def validate_state(state: Mapping[str, Any]) -> None:
    if state.get("schema_version") != STATE_SCHEMA:
        raise RuntimeError("BBO_OOS_STATE_SCHEMA_MISMATCH")
    if state.get("architecture_id") != ARCHITECTURE_ID or state.get("parent_identity") != PARENT_IDENTITY:
        raise RuntimeError("BBO_OOS_STATE_IDENTITY_DRIFT")
    if int(state.get("activation_ms") or 0) <= 0:
        raise RuntimeError("BBO_OOS_ACTIVATION_REQUIRED")
    if state.get("future_only") is not True or state.get("historical_backfill") is not False:
        raise RuntimeError("BBO_OOS_FUTURE_ONLY_DRIFT")
    for key, expected in AUTHORITY.items():
        if state.get(key) != expected:
            raise RuntimeError(f"BBO_OOS_AUTHORITY_DRIFT:{key}")


def validate_chain(rows: Sequence[Mapping[str, Any]]) -> None:
    prev: str | None = None
    seen: set[str] = set()
    for idx, row in enumerate(rows):
        if row.get("schema_version") != SCHEMA or int(row.get("seq") or -1) != idx:
            raise RuntimeError(f"BBO_OOS_EVENT_SCHEMA_OR_SEQ:{idx}")
        if row.get("prev_sha256") != prev:
            raise RuntimeError(f"BBO_OOS_EVENT_PREV_SHA:{idx}")
        event_id = str(row.get("event_id") or "")
        if not event_id or event_id in seen:
            raise RuntimeError(f"BBO_OOS_EVENT_ID_INVALID:{idx}")
        seen.add(event_id)
        supplied = str(row.get("record_sha256") or "")
        core = dict(row)
        core.pop("record_sha256", None)
        if supplied != stable(core):
            raise RuntimeError(f"BBO_OOS_EVENT_HASH:{idx}")
        prev = supplied


def append_event(rows: list[dict[str, Any]], payload: Mapping[str, Any]) -> dict[str, Any]:
    core = dict(payload)
    core.update({
        "schema_version": SCHEMA,
        "seq": len(rows),
        "prev_sha256": str(rows[-1]["record_sha256"]) if rows else None,
    })
    core["record_sha256"] = stable(core)
    rows.append(core)
    return core


def bbo_confirms(side: str, bid_qty: float, ask_qty: float) -> bool:
    if bid_qty <= 0 or ask_qty <= 0:
        raise RuntimeError("BBO_QTY_NONPOSITIVE")
    if side == "long":
        return bid_qty > ask_qty
    if side == "short":
        return ask_qty > bid_qty
    raise RuntimeError(f"BBO_SIDE_INVALID:{side}")


def fetch_bbo(symbol: str) -> dict[str, Any]:
    requested_at_ms = now_ms()
    payload = ev.request_json(ev.DEPTH_API, {"symbol": symbol, "limit": 5})
    observed_at_ms = now_ms()
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    bids = data.get("bids") or []
    asks = data.get("asks") or []
    if not bids or not asks or len(bids[0]) < 2 or len(asks[0]) < 2:
        raise RuntimeError(f"BBO_EMPTY:{symbol}")
    bid_px, bid_qty = float(bids[0][0]), float(bids[0][1])
    ask_px, ask_qty = float(asks[0][0]), float(asks[0][1])
    if bid_px <= 0 or ask_px <= bid_px or bid_qty <= 0 or ask_qty <= 0:
        raise RuntimeError(f"BBO_INVALID:{symbol}:{bid_px}:{bid_qty}:{ask_px}:{ask_qty}")
    mid = (bid_px + ask_px) / 2.0
    body = {
        "symbol": symbol,
        "requested_at_ms": requested_at_ms,
        "observed_at_ms": observed_at_ms,
        "bid_px": bid_px,
        "bid_qty": bid_qty,
        "ask_px": ask_px,
        "ask_qty": ask_qty,
        "spread_bps": (ask_px - bid_px) / mid * 10_000.0,
        "source_endpoint": "/openApi/swap/v2/quote/depth",
        "point_in_time": True,
    }
    body["snapshot_sha256"] = stable(body)
    return body


def latest_closed_bars(symbol: str, current_ms: int) -> list[dict[str, Any]]:
    bars = [dict(row) for row in ev.fetch_bars(symbol, "1h", 1000)]
    return [row for row in bars if int(row["ts_ms"]) + HOUR_MS <= current_ms]


def candidate_probe(symbol: str, bars: Sequence[Mapping[str, Any]], current_ms: int, cost_authority: Mapping[str, Any]) -> dict[str, Any] | None:
    if len(bars) < 65:
        return None
    signal_ts = int(bars[-1]["ts_ms"])
    signal_close_ms = signal_ts + HOUR_MS

    transition_cfg = transition_policy.TrendRiderTransitionFreshnessConfig()
    transition_feature = transition_policy.compute_trend_rider_feature(
        bars, symbol=symbol, now_ts_ms=current_ms, config=transition_cfg
    )
    long_transition = bool(transition_feature.values.get("long_confirm"))
    short_transition = bool(transition_feature.values.get("short_confirm"))
    if long_transition == short_transition:
        return None

    # Validate the unsuppressed transition as a real parent intent using the same
    # public cost authority used by the existing G5 evaluator. Only after that
    # do we inspect whether the frozen WR81.25 US chase gate blocked it.
    execution_snapshot = ev.fetch_execution_snapshot(symbol, dict(cost_authority))
    transition_intent = transition_policy.build_trend_rider_intent(
        transition_feature,
        policy_source_sha=ev.git_blob_sha(TRANSITION_POLICY_PATH),
        verified_round_trip_cost_bps=float(execution_snapshot["pretrade_verified_cost_bps"]),
        config=transition_cfg,
    )
    if bool(getattr(transition_intent, "no_trade")):
        return None
    side = str(getattr(transition_intent, "side"))

    frozen_cfg = frozen_parent_policy.TrendRiderWR80USChaseCoolingConfig()
    frozen_feature = frozen_parent_policy.compute_trend_rider_feature(
        bars, symbol=symbol, now_ts_ms=current_ms, config=frozen_cfg
    )
    values = frozen_feature.values
    if str(values.get("session")) != "US":
        return None
    still_admitted = bool(values.get("long_confirm")) if side == "long" else bool(values.get("short_confirm"))
    if still_admitted:
        return None

    return {
        "symbol": symbol,
        "signal_ts": signal_ts,
        "signal_bar_close_ms": signal_close_ms,
        "side": side,
        "session": "US",
        "chase_state": str(values.get("chase_state")),
        "transition_feature_sha": str(transition_feature.feature_sha),
        "frozen_parent_feature_sha": str(frozen_feature.feature_sha),
        "transition_intent_sha": ev.intent_sha(transition_intent),
        "pretrade_verified_cost_bps": float(execution_snapshot["pretrade_verified_cost_bps"]),
        "cost_snapshot_sha256": str(execution_snapshot["snapshot_sha256"]),
    }


def make_state(current_ms: int) -> dict[str, Any]:
    body = {
        "schema_version": STATE_SCHEMA,
        "state": "ACTIVE_FUTURE_ONLY_BBO_COLLECTION",
        "architecture_id": ARCHITECTURE_ID,
        "parent_identity": PARENT_IDENTITY,
        "activation_ms": int(current_ms),
        "future_only": True,
        "historical_backfill": False,
        "candidate_rule": "US_BASELINE_BLOCKED_ONLY__LONG_BID_QTY_GT_ASK_QTY__SHORT_ASK_QTY_GT_BID_QTY",
        "symbols": list(SYMBOLS),
        **AUTHORITY,
    }
    body["state_sha256"] = stable(body)
    return body


def run(*, state: dict[str, Any] | None, events: list[dict[str, Any]], current_ms: int) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    validate_chain(events)
    if state is None:
        state = make_state(current_ms)
        status = {
            "schema_version": STATUS_SCHEMA,
            "state": "ACTIVATED_FUTURE_ONLY_T0",
            "architecture_id": ARCHITECTURE_ID,
            "activation_ms": int(state["activation_ms"]),
            "candidate_T_total": len(events),
            "confirmed_T_total": sum(1 for row in events if row.get("bbo_confirm") is True),
            "new_events": 0,
            **AUTHORITY,
        }
        status["receipt_sha256"] = stable(status)
        return state, events, status

    validate_state(state)
    activation_ms = int(state["activation_ms"])
    known = {str(row["event_id"]) for row in events}
    cost_authority = ev.load_json(COST_PATH)
    if cost_authority.get("state") != "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY":
        raise RuntimeError("BBO_OOS_COST_AUTHORITY_INVALID")

    new_events = 0
    scanned: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        bars = latest_closed_bars(symbol, current_ms)
        if not bars:
            scanned.append({"symbol": symbol, "latest_closed_signal_ts": None, "result": "NO_CLOSED_BAR"})
            continue
        signal_ts = int(bars[-1]["ts_ms"])
        signal_close_ms = signal_ts + HOUR_MS
        if signal_close_ms <= activation_ms:
            scanned.append({"symbol": symbol, "latest_closed_signal_ts": signal_ts, "result": "PRE_ACTIVATION"})
            continue
        probe = candidate_probe(symbol, bars, current_ms, cost_authority)
        if probe is None:
            scanned.append({"symbol": symbol, "latest_closed_signal_ts": signal_ts, "result": "NO_BASELINE_BLOCKED_US_SIGNAL"})
            continue
        identity = {
            "architecture_id": ARCHITECTURE_ID,
            "symbol": probe["symbol"],
            "signal_ts": probe["signal_ts"],
            "side": probe["side"],
        }
        event_id = stable(identity)
        if event_id in known:
            scanned.append({"symbol": symbol, "latest_closed_signal_ts": signal_ts, "result": "ALREADY_CAPTURED"})
            continue

        bbo = fetch_bbo(symbol)
        confirmed = bbo_confirms(str(probe["side"]), float(bbo["bid_qty"]), float(bbo["ask_qty"]))
        payload = {
            "event_id": event_id,
            "architecture_id": ARCHITECTURE_ID,
            "parent_identity": PARENT_IDENTITY,
            **probe,
            "observed_at_ms": int(bbo["observed_at_ms"]),
            "capture_lag_ms": int(bbo["observed_at_ms"]) - int(probe["signal_bar_close_ms"]),
            "bbo": bbo,
            "bbo_rule": "LONG_BID_QTY_GT_ASK_QTY__SHORT_ASK_QTY_GT_BID_QTY",
            "bbo_confirm": bool(confirmed),
            "candidate_admitted": bool(confirmed),
            "counterfactual_entry_reference_px": float(bbo["ask_px"] if probe["side"] == "long" else bbo["bid_px"]),
            "outcome_state": "PENDING_FUTURE_ONLY_SETTLEMENT" if confirmed else "NOT_ADMITTED",
            "historical_backfill": False,
            **AUTHORITY,
        }
        append_event(events, payload)
        known.add(event_id)
        new_events += 1
        scanned.append({"symbol": symbol, "latest_closed_signal_ts": signal_ts, "result": "BBO_CAPTURED", "bbo_confirm": bool(confirmed)})

    validate_chain(events)
    status = {
        "schema_version": STATUS_SCHEMA,
        "state": "COLLECTING_FUTURE_BBO_OOS",
        "architecture_id": ARCHITECTURE_ID,
        "activation_ms": activation_ms,
        "generated_at_ms": int(current_ms),
        "candidate_T_total": len(events),
        "confirmed_T_total": sum(1 for row in events if row.get("bbo_confirm") is True),
        "rejected_T_total": sum(1 for row in events if row.get("bbo_confirm") is False),
        "new_events": new_events,
        "scanned": scanned,
        "historical_backfill": False,
        "numeric_threshold_sweep": False,
        "rr_exit_mutation": False,
        **AUTHORITY,
    }
    status["receipt_sha256"] = stable(status)
    return state, events, status


def self_test() -> int:
    assert bbo_confirms("long", 2.0, 1.0) is True
    assert bbo_confirms("long", 1.0, 2.0) is False
    assert bbo_confirms("short", 1.0, 2.0) is True
    assert bbo_confirms("short", 2.0, 1.0) is False
    assert bbo_confirms("long", 1.0, 1.0) is False
    rows: list[dict[str, Any]] = []
    append_event(rows, {"event_id": "a", "architecture_id": ARCHITECTURE_ID})
    append_event(rows, {"event_id": "b", "architecture_id": ARCHITECTURE_ID})
    validate_chain(rows)
    state = make_state(123456789)
    validate_state(state)
    assert state["historical_backfill"] is False and state["formal_credit"] == 0
    print("PASS_G5_TREND_RIDER_BBO_OOS_COLLECTOR_V1")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--state", default=str(STATE_PATH))
    parser.add_argument("--events", default=str(EVENTS_PATH))
    parser.add_argument("--out-dir", default="out")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    current_ms = now_ms()
    state = read_json(Path(args.state))
    events = read_jsonl(Path(args.events))
    state, events, status = run(state=state, events=events, current_ms=current_ms)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "g5_trend_rider_bbo_oos_state_v1.json", state)
    write_jsonl(out / "g5_trend_rider_bbo_oos_events_v1.jsonl", events)
    write_json(out / "g5_trend_rider_bbo_oos_latest_v1.json", status)
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
