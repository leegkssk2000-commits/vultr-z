from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

ALLOWED_MODES = {"SHADOW", "PAPER", "LIVE"}
ALLOWED_SIGNALS = {"LONG", "SHORT", "EXIT", "FLAT"}
ACTIVE_ALPHA_STATE = "SURVIVOR_ACTIVE"


@dataclass(frozen=True)
class SpineDecision:
    state: str
    action: str
    order_intent: str
    submit_exchange_order: bool
    ledger_event_required: bool
    reason: str
    mode: str
    symbol: str
    strategy_id: str
    alpha_state: str
    risk_state: str
    position_state: str
    idempotency_key: str


def _stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _required(payload: Mapping[str, Any], key: str) -> Any:
    if key not in payload:
        raise ValueError(f"MISSING_REQUIRED_FIELD:{key}")
    return payload[key]


def _idempotency_key(payload: Mapping[str, Any], intent: str) -> str:
    material = {
        "symbol": payload.get("symbol"),
        "strategy_id": payload.get("strategy_id"),
        "alpha_id": payload.get("alpha_id"),
        "signal_ts": payload.get("signal_ts"),
        "position_id": payload.get("position_id"),
        "intent": intent,
        "mode": payload.get("mode"),
    }
    return _stable_sha(material)


def evaluate_spine(payload: Mapping[str, Any]) -> SpineDecision:
    mode = str(_required(payload, "mode")).upper()
    symbol = str(_required(payload, "symbol"))
    strategy_id = str(_required(payload, "strategy_id"))
    alpha_state = str(_required(payload, "alpha_state")).upper()
    signal = str(_required(payload, "signal")).upper()
    risk_state = str(_required(payload, "risk_state")).upper()
    position_state = str(_required(payload, "position_state")).upper()
    market_data_ok = bool(_required(payload, "market_data_ok"))
    emergency_stop = bool(payload.get("emergency_stop", False))

    if mode not in ALLOWED_MODES:
        raise ValueError(f"INVALID_MODE:{mode}")
    if signal not in ALLOWED_SIGNALS:
        raise ValueError(f"INVALID_SIGNAL:{signal}")

    def decision(state: str, action: str, intent: str, reason: str, ledger: bool = False) -> SpineDecision:
        # Exchange submission is intentionally impossible in v1, including LIVE.
        return SpineDecision(
            state=state,
            action=action,
            order_intent=intent,
            submit_exchange_order=False,
            ledger_event_required=ledger,
            reason=reason,
            mode=mode,
            symbol=symbol,
            strategy_id=strategy_id,
            alpha_state=alpha_state,
            risk_state=risk_state,
            position_state=position_state,
            idempotency_key=_idempotency_key(payload, intent),
        )

    if emergency_stop:
        return decision("STOPPED", "stop", "NONE", "EMERGENCY_STOP")
    if mode == "LIVE":
        return decision("BLOCKED", "block", "NONE", "LIVE_NOT_ACTIVATED")
    # A missing/non-executable alpha is a complete, deterministic no-order state.
    # Do not require or synthesize market price/quantity merely to prove that no
    # trading authority exists. Once alpha is active, market integrity remains
    # mandatory before risk/order planning.
    if alpha_state != ACTIVE_ALPHA_STATE:
        return decision("HOLD", "hold", "NONE", "NO_VALIDATED_ALPHA")
    if not market_data_ok:
        return decision("HOLD", "hold", "NONE", "MARKET_DATA_INTEGRITY_FAIL")
    if risk_state != "PASS":
        return decision("BLOCKED", "block", "NONE", f"RISK_GATE_{risk_state}")

    if signal == "FLAT":
        return decision("READY", "hold", "NONE", "NO_ACTION_SIGNAL")

    if signal == "EXIT":
        if position_state == "FLAT":
            return decision("READY", "hold", "NONE", "DUPLICATE_CLOSE_FORBIDDEN")
        return decision("ORDER_PLAN_READY", "hold", "CLOSE", "VALIDATED_EXIT", ledger=True)

    if signal == "LONG":
        if position_state != "FLAT":
            return decision("READY", "hold", "NONE", "DUPLICATE_OPEN_FORBIDDEN")
        return decision("ORDER_PLAN_READY", "hold", "OPEN_LONG", "VALIDATED_LONG_ENTRY", ledger=True)

    if signal == "SHORT":
        if position_state != "FLAT":
            return decision("READY", "hold", "NONE", "DUPLICATE_OPEN_FORBIDDEN")
        return decision("ORDER_PLAN_READY", "hold", "OPEN_SHORT", "VALIDATED_SHORT_ENTRY", ledger=True)

    raise AssertionError("unreachable")


def build_ledger_event(payload: Mapping[str, Any], decision: SpineDecision) -> dict[str, Any]:
    if not decision.ledger_event_required:
        raise ValueError("LEDGER_EVENT_NOT_REQUIRED")
    event = {
        "schema_version": "zel.formal_ledger_event.v1",
        "mode": decision.mode,
        "symbol": decision.symbol,
        "strategy_id": decision.strategy_id,
        "alpha_id": payload.get("alpha_id"),
        "signal_ts": payload.get("signal_ts"),
        "position_id": payload.get("position_id"),
        "order_intent": decision.order_intent,
        "risk_state": decision.risk_state,
        "cost_model_id": payload.get("cost_model_id"),
        "idempotency_key": decision.idempotency_key,
        "simulated": True,
        "exchange_order_submitted": False,
    }
    event["event_sha256"] = _stable_sha(event)
    return event


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    result = evaluate_spine(payload)
    out: dict[str, Any] = {"decision": asdict(result)}
    if result.ledger_event_required:
        out["ledger_event"] = build_ledger_event(payload, result)
    out["receipt_sha256"] = _stable_sha(out)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
