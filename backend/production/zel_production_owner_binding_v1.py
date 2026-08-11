from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from backend.engine.execution.execution_router import ExecutionRouter, OrderIntent
from backend.production.zel_production_spine_v1 import evaluate_spine

SCHEMA = "zel.production_owner_binding.v1"
OWNER_SHA = {
    "market_data": "17a0397af95fc5f8a6503a7ed337d19d8a5cbec2",
    "risk_gate": "4648fdc1c72500795b893f73ae259d2886753ef3",
    "position_and_pnl": "2f1be1eca145023d5e0c0c5dbb4eea9dc6c29704",
    "state_read_model": "ad3b1139867d0741b0ad01876c7871516b5a8399",
    "execution": "6298efa83870c2131722ba707197986a7dccdab0",
    "alimi": "c8ce168e1c27bbb1d51c13d73dafec517e634ce6",
}


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class ProductionEventLedger:
    """Single append-only simulated trade-event ledger for SHADOW/PAPER.

    Position and PnL are recomputed from events; no secondary mutable position owner
    is authoritative inside the production spine.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS trade_events (
                    sequence_no INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    event_sha256 TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL NOT NULL,
                    price REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    event_json TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30.0)
        db.row_factory = sqlite3.Row
        return db

    def events(self, symbol: str | None = None, strategy_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT event_json FROM trade_events"
        params: list[Any] = []
        clauses: list[str] = []
        if symbol is not None:
            clauses.append("symbol=?")
            params.append(symbol)
        if strategy_id is not None:
            clauses.append("strategy_id=?")
            params.append(strategy_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY sequence_no"
        with self._connect() as db:
            return [json.loads(row["event_json"]) for row in db.execute(query, params)]

    def count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM trade_events").fetchone()[0])

    def position(self, symbol: str, strategy_id: str) -> dict[str, Any]:
        pos = {"state": "FLAT", "side": "", "qty": 0.0, "avg_entry": 0.0}
        for event in self.events(symbol, strategy_id):
            kind = str(event["event_type"])
            if kind == "OPEN_LONG":
                pos = {"state": "LONG", "side": "long", "qty": _f(event["qty"]), "avg_entry": _f(event["price"])}
            elif kind == "OPEN_SHORT":
                pos = {"state": "SHORT", "side": "short", "qty": _f(event["qty"]), "avg_entry": _f(event["price"])}
            elif kind == "CLOSE":
                pos = {"state": "FLAT", "side": "", "qty": 0.0, "avg_entry": 0.0}
        return pos

    def realized_pnl(self, symbol: str | None = None, strategy_id: str | None = None) -> float:
        return sum(_f(event.get("realized_pnl")) for event in self.events(symbol, strategy_id))

    def append_fill(
        self,
        *,
        idempotency_key: str,
        symbol: str,
        strategy_id: str,
        event_type: str,
        side: str,
        qty: float,
        price: float,
        alpha_id: str,
        signal_ts: Any,
        mode: str,
        cost_model_id: str,
        execution_result: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self._connect() as db:
            prior = db.execute(
                "SELECT event_json FROM trade_events WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            if prior is not None:
                out = json.loads(prior["event_json"])
                out["replayed"] = True
                return out

        current = self.position(symbol, strategy_id)
        realized = 0.0
        if event_type == "CLOSE":
            if current["state"] == "FLAT":
                raise ValueError("CLOSE_WITHOUT_OPEN_POSITION")
            close_qty = min(float(qty), float(current["qty"]))
            if current["state"] == "LONG":
                realized = (float(price) - float(current["avg_entry"])) * close_qty
            else:
                realized = (float(current["avg_entry"]) - float(price)) * close_qty
        elif current["state"] != "FLAT":
            raise ValueError("DUPLICATE_OPEN_FORBIDDEN")

        event: dict[str, Any] = {
            "schema_version": "zel.production_trade_event.v1",
            "idempotency_key": idempotency_key,
            "symbol": symbol,
            "strategy_id": strategy_id,
            "alpha_id": alpha_id,
            "signal_ts": signal_ts,
            "mode": mode,
            "event_type": event_type,
            "side": side,
            "qty": float(qty),
            "price": float(price),
            "realized_pnl": float(realized),
            "cost_model_id": cost_model_id,
            "simulated": True,
            "exchange_order_submitted": False,
            "execution_result": dict(execution_result),
            "owner_sha": dict(OWNER_SHA),
        }
        event["event_sha256"] = stable_sha(event)
        encoded = json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    """
                    INSERT INTO trade_events(
                        idempotency_key,event_sha256,symbol,strategy_id,event_type,side,qty,price,realized_pnl,event_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        idempotency_key,
                        event["event_sha256"],
                        symbol,
                        strategy_id,
                        event_type,
                        side,
                        float(qty),
                        float(price),
                        float(realized),
                        encoded,
                    ),
                )
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                prior = db.execute(
                    "SELECT event_json FROM trade_events WHERE idempotency_key=?", (idempotency_key,)
                ).fetchone()
                if prior is None:
                    raise
                out = json.loads(prior["event_json"])
                out["replayed"] = True
                return out
        event["replayed"] = False
        return event


def build_output_snapshot(
    ledger: ProductionEventLedger,
    *,
    symbol: str,
    strategy_id: str,
    mark_price: float,
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    pos = ledger.position(symbol, strategy_id)
    realized = ledger.realized_pnl()
    unrealized = 0.0
    if pos["state"] == "LONG":
        unrealized = (float(mark_price) - float(pos["avg_entry"])) * float(pos["qty"])
    elif pos["state"] == "SHORT":
        unrealized = (float(pos["avg_entry"]) - float(mark_price)) * float(pos["qty"])
    canonical = {
        "schema_version": "zel.production_snapshot.v1",
        "symbol": symbol,
        "strategy_id": strategy_id,
        "position": pos,
        "pnl": {
            "realized": float(realized),
            "unrealized": float(unrealized),
            "total": float(realized + unrealized),
        },
        "ledger_event_count": ledger.count(),
        "decision": dict(decision),
        "exchange_order_submitted": False,
    }
    canonical["snapshot_sha256"] = stable_sha(canonical)
    return {
        "canonical": canonical,
        "alimi": {"snapshot_sha256": canonical["snapshot_sha256"], "snapshot": canonical},
        "telegram": {"snapshot_sha256": canonical["snapshot_sha256"], "snapshot": canonical},
    }


def _execution_intent(payload: Mapping[str, Any], decision: Mapping[str, Any], position: Mapping[str, Any]) -> OrderIntent:
    intent_kind = str(decision["order_intent"])
    mode = str(payload["mode"]).lower()
    route = "paper" if mode == "paper" else "noop"
    if intent_kind == "OPEN_LONG":
        side, reduce_only = "buy", False
        qty = _f(payload.get("qty"), 1.0)
    elif intent_kind == "OPEN_SHORT":
        side, reduce_only = "sell", False
        qty = _f(payload.get("qty"), 1.0)
    elif intent_kind == "CLOSE":
        side = "sell" if position["state"] == "LONG" else "buy"
        reduce_only = True
        # Closing exposure is owned by the canonical ledger position. Upstream
        # Risk+Sizing intentionally emits qty=0 for EXIT/FLAT because it must not
        # invent a new exposure quantity. Resolve exact reduce-only quantity here.
        qty = _f(position.get("qty"), 0.0)
        if qty <= 0.0:
            raise RuntimeError("CLOSE_POSITION_QTY_INVALID")
    else:
        raise ValueError(f"UNSUPPORTED_ORDER_INTENT:{intent_kind}")
    key = str(decision["idempotency_key"])
    return OrderIntent(
        symbol=str(payload["symbol"]),
        side=side,
        event_id=str(payload.get("event_id") or key),
        decision_id=str(payload.get("decision_id") or key),
        qty=qty,
        price=_f(payload.get("price")),
        order_type="market",
        reduce_only=reduce_only,
        exchange="bingx",
        strategy=str(payload["strategy_id"]),
        mode=mode,
        route=route,
        meta={"production_spine": True, "simulated_only": True},
    )


def run_cycle(payload: Mapping[str, Any], ledger: ProductionEventLedger) -> dict[str, Any]:
    symbol = str(payload["symbol"])
    strategy_id = str(payload["strategy_id"])
    current = ledger.position(symbol, strategy_id)
    spine_input = dict(payload)
    spine_input["position_state"] = current["state"]
    spine_input["market_data_ok"] = bool(payload.get("market_data_ok", True)) and _f(payload.get("price")) > 0.0
    spine_decision = evaluate_spine(spine_input)
    decision = {key: value for key, value in spine_decision.__dict__.items()}
    fill = None

    if spine_decision.order_intent != "NONE":
        intent = _execution_intent(spine_input, decision, current)
        execution = ExecutionRouter(route_mode=intent.mode).route(intent)
        execution_dict = execution.to_dict()
        if not execution.ok:
            raise RuntimeError(f"SIMULATION_EXECUTION_REJECTED:{execution.reason}")
        event_type = spine_decision.order_intent
        event_side = "long" if event_type == "OPEN_LONG" else "short" if event_type == "OPEN_SHORT" else current["side"]
        qty = current["qty"] if event_type == "CLOSE" else float(intent.normalized_qty() or 0.0)
        fill = ledger.append_fill(
            idempotency_key=spine_decision.idempotency_key,
            symbol=symbol,
            strategy_id=strategy_id,
            event_type=event_type,
            side=event_side,
            qty=float(qty),
            price=float(intent.price or 0.0),
            alpha_id=str(payload.get("alpha_id") or ""),
            signal_ts=payload.get("signal_ts"),
            mode=str(payload["mode"]).upper(),
            cost_model_id=str(payload.get("cost_model_id") or "UNBOUND"),
            execution_result=execution_dict,
        )

    snapshots = build_output_snapshot(
        ledger,
        symbol=symbol,
        strategy_id=strategy_id,
        mark_price=_f(payload.get("price")),
        decision=decision,
    )
    result = {
        "schema_version": SCHEMA,
        "decision": decision,
        "fill": fill,
        "snapshot": snapshots,
        "owner_sha": dict(OWNER_SHA),
        "exchange_order_submitted": False,
    }
    result["receipt_sha256"] = stable_sha(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    result = run_cycle(payload, ProductionEventLedger(args.ledger))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
