from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Dict, Optional


ALLOWED_EXCHANGES = {"bingx"}
CONTRACT_EXECUTION_SIDES = {"buy", "sell"}
ALLOWED_SIDES = CONTRACT_EXECUTION_SIDES
ALLOWED_ORDER_TYPES = {"market", "limit"}

CONTRACT_RUNTIME_MODES = {"noop", "dummy", "paper", "shadow", "live"}
CONTRACT_RUNTIME_ROUTES = {"noop", "paper", "live"}
ALLOWED_MODES = CONTRACT_RUNTIME_MODES
ALLOWED_ROUTES = CONTRACT_RUNTIME_ROUTES


def _now_ts() -> int:
    return int(time.time())


def _clean_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    return str(v).strip()


def _clean_lower(v: Any, default: str = "") -> str:
    return _clean_str(v, default).lower()


def _normalize_execution_side(v: Any) -> str:
    s = _clean_lower(v)
    if s in {"buy", "long"}:
        return "buy"
    if s in {"sell", "short", "exit"}:
        return "sell"
    return s


def _as_dict(v: Any) -> Dict[str, Any]:
    if v is None:
        return {}
    if isinstance(v, dict):
        return dict(v)
    if is_dataclass(v):
        return asdict(v)
    data = getattr(v, "__dict__", None)
    if isinstance(data, dict):
        return dict(data)
    return {}


def _to_pos_float(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


@dataclass
class GuardState:
    ok: bool = True
    reason: str = ""
    code: str = "ok"
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "code": self.code,
            "details": dict(self.details),
        }


@dataclass
class OrderIntent:
    symbol: str = ""
    side: str = ""
    event_id: str = ""
    decision_id: str = ""
    qty: Optional[float] = None
    size: Optional[float] = None
    amount: Optional[float] = None
    price: Optional[float] = None
    order_type: str = "market"
    reduce_only: bool = False
    exchange: str = "bingx"
    strategy: Optional[str] = None
    mode: str = "noop"
    route: str = "noop"
    raw: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_any(cls, value: Any) -> "OrderIntent":
        d = _as_dict(value)
        raw = d.get("raw")
        if not isinstance(raw, dict):
            raw = dict(d)
        meta = d.get("meta")
        if not isinstance(meta, dict):
            meta = {}

        return cls(
            symbol=_clean_str(d.get("symbol")),
            side=_normalize_execution_side(d.get("execution_side") or d.get("side")),
            event_id=_clean_str(d.get("event_id")),
            decision_id=_clean_str(d.get("decision_id")),
            qty=_to_pos_float(d.get("qty")),
            size=_to_pos_float(d.get("size")),
            amount=_to_pos_float(d.get("amount")),
            price=_to_pos_float(d.get("price")),
            order_type=_clean_lower(d.get("order_type") or d.get("type") or "market"),
            reduce_only=bool(d.get("reduce_only", False)),
            exchange=_clean_lower(d.get("exchange") or "bingx"),
            strategy=_clean_str(d.get("strategy")),
            mode=_clean_lower(d.get("mode") or "noop"),
            route=_clean_lower(d.get("route") or "noop"),
            raw=raw,
            meta=meta,
        )

    def normalized_qty(self) -> Optional[float]:
        for v in (self.qty, self.size, self.amount):
            if isinstance(v, (int, float)):
                x = float(v)
                if x > 0:
                    return x
        return None

    def intent_kind(self) -> str:
        return "reduce" if self.reduce_only else "open"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "event_id": self.event_id,
            "decision_id": self.decision_id,
            "qty": self.qty,
            "size": self.size,
            "amount": self.amount,
            "price": self.price,
            "order_type": self.order_type,
            "reduce_only": self.reduce_only,
            "exchange": self.exchange,
            "strategy": self.strategy,
            "mode": self.mode,
            "route": self.route,
            "raw": dict(self.raw),
            "meta": dict(self.meta),
        }


@dataclass
class ExecutionResult:
    ok: bool
    status: str
    reason: str = ""
    route: str = "noop"
    mode: str = "noop"
    intent_kind: str = "open"
    event_id: Optional[str] = None
    decision_id: Optional[str] = None
    symbol: Optional[str] = None
    side: Optional[str] = None
    exchange: Optional[str] = None
    order_type: Optional[str] = None
    requested_qty: Optional[float] = None
    reduce_only: bool = False
    accepted_at: int = field(default_factory=_now_ts)
    guard: Dict[str, Any] = field(default_factory=dict)
    payload: Dict[str, Any] = field(default_factory=dict)
    effective_mode: Optional[str] = None
    effective_route: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "reason": self.reason,
            "route": self.route,
            "mode": self.mode,
            "intent_kind": self.intent_kind,
            "event_id": self.event_id,
            "decision_id": self.decision_id,
            "symbol": self.symbol,
            "side": self.side,
            "exchange": self.exchange,
            "order_type": self.order_type,
            "requested_qty": self.requested_qty,
            "reduce_only": self.reduce_only,
            "accepted_at": self.accepted_at,
            "guard": dict(self.guard),
            "payload": dict(self.payload),
            "effective_mode": self.effective_mode or self.mode,
            "effective_route": self.effective_route or self.route,
        }


class ExecutionRouter:
    def __init__(self, env: str = "prod", route_mode: str = "noop", **kwargs: Any) -> None:
        cfg_mode = _clean_lower(route_mode or os.getenv("ZOS_ROUTE_MODE") or "noop")
        if cfg_mode not in ALLOWED_MODES:
            cfg_mode = "noop"

        self.env = _clean_lower(env or os.getenv("ZOS_ENV") or "prod", "prod")
        self.route_mode = cfg_mode
        self.options = dict(kwargs)

    def _deny(
        self,
        intent: OrderIntent,
        guard: GuardState,
        *,
        status: str = "blocked",
        route: Optional[str] = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            ok=False,
            status=status,
            reason=guard.reason,
            route=route or intent.route or "noop",
            mode=intent.mode or self.route_mode,
            intent_kind=intent.intent_kind(),
            event_id=intent.event_id or None,
            decision_id=intent.decision_id or None,
            symbol=intent.symbol or None,
            side=intent.side or None,
            exchange=intent.exchange or None,
            order_type=intent.order_type or None,
            requested_qty=intent.normalized_qty(),
            reduce_only=bool(intent.reduce_only),
            guard=guard.to_dict(),
            payload=intent.to_dict(),
            effective_mode=intent.mode or self.route_mode,
            effective_route=route or intent.route or "noop",
        )

    def _reject(self, intent: OrderIntent, guard: GuardState, route: Optional[str] = None) -> ExecutionResult:
        return self._deny(intent, guard, status="blocked", route=route)

    def _hold(self, intent: OrderIntent, guard: GuardState, route: Optional[str] = None) -> ExecutionResult:
        return self._deny(intent, guard, status="hold", route=route)

    def _accept(self, intent: OrderIntent, reason: str, route: Optional[str] = None) -> ExecutionResult:
        guard = GuardState(ok=True, reason="", code="ok", details={})
        return ExecutionResult(
            ok=True,
            status="accepted",
            reason=reason,
            route=route or intent.route or "noop",
            mode=intent.mode or self.route_mode,
            intent_kind=intent.intent_kind(),
            event_id=intent.event_id,
            decision_id=intent.decision_id,
            symbol=intent.symbol,
            side=intent.side,
            exchange=intent.exchange,
            order_type=intent.order_type,
            requested_qty=intent.normalized_qty(),
            reduce_only=bool(intent.reduce_only),
            guard=guard.to_dict(),
            payload=intent.to_dict(),
            effective_mode=intent.mode or self.route_mode,
            effective_route=route or intent.route or "noop",
        )

    def _guard(self, intent: OrderIntent) -> GuardState:
        if not intent.symbol:
            return GuardState(False, "missing symbol", "missing_symbol")

        if intent.side not in ALLOWED_SIDES:
            return GuardState(
                False,
                "invalid side",
                "invalid_side",
                {"allowed": sorted(ALLOWED_SIDES), "got": intent.side},
            )

        if not intent.event_id:
            return GuardState(False, "missing event_id", "missing_event_id")

        if not intent.decision_id:
            return GuardState(False, "missing decision_id", "missing_decision_id")

        if intent.exchange not in ALLOWED_EXCHANGES:
            return GuardState(
                False,
                "invalid exchange",
                "invalid_exchange",
                {"allowed": sorted(ALLOWED_EXCHANGES), "got": intent.exchange},
            )

        if intent.order_type not in ALLOWED_ORDER_TYPES:
            return GuardState(
                False,
                "invalid order_type",
                "invalid_order_type",
                {"allowed": sorted(ALLOWED_ORDER_TYPES), "got": intent.order_type},
            )

        qty = intent.normalized_qty()
        raw_has_qty = any(v is not None for v in (intent.qty, intent.size, intent.amount))
        if raw_has_qty and qty is None:
            return GuardState(
                False,
                "invalid qty",
                "invalid_qty",
                {"qty": intent.qty, "size": intent.size, "amount": intent.amount},
            )

        if qty is not None and qty <= 0:
            return GuardState(
                False,
                "invalid qty",
                "invalid_qty",
                {"requested_qty": qty},
            )

        if intent.price is not None and intent.price <= 0:
            return GuardState(
                False,
                "invalid price",
                "invalid_price",
                {"price": intent.price},
            )

        if intent.mode not in ALLOWED_MODES:
            return GuardState(
                False,
                "invalid mode",
                "invalid_mode",
                {"allowed": sorted(ALLOWED_MODES), "got": intent.mode},
            )

        if intent.route not in ALLOWED_ROUTES:
            return GuardState(
                False,
                "invalid route",
                "invalid_route",
                {"allowed": sorted(ALLOWED_ROUTES), "got": intent.route},
            )

        return GuardState(True, "", "ok")

    def _guard_boundary(self, intent: OrderIntent) -> GuardState:
        # dummy / paper / live 완전 분리
        # shadow는 exchange/live 절대 금지 -> noop만 허용
        # live인데 exchange_disabled면 hold
        if intent.mode == "shadow":
            if intent.route != "noop":
                return GuardState(
                    False,
                    "shadow_exchange_forbidden",
                    "shadow_exchange_forbidden",
                    {"mode": intent.mode, "route": intent.route, "effective_route": "noop"},
                )
            return GuardState(True, "", "ok", {"effective_route": "noop"})

        if intent.mode == "dummy":
            if intent.route != "noop":
                return GuardState(
                    False,
                    "dummy_must_be_noop",
                    "dummy_must_be_noop",
                    {"mode": intent.mode, "route": intent.route, "effective_route": "noop"},
                )
            return GuardState(True, "", "ok", {"effective_route": "noop"})

        if intent.mode == "paper":
            if intent.route != "paper":
                return GuardState(
                    False,
                    "paper_requires_paper_route",
                    "paper_requires_paper_route",
                    {"mode": intent.mode, "route": intent.route, "effective_route": "paper"},
                )
            return GuardState(True, "", "ok", {"effective_route": "paper"})

        if intent.mode == "live":
            if intent.route != "live":
                return GuardState(
                    False,
                    "live_requires_live_route",
                    "live_requires_live_route",
                    {"mode": intent.mode, "route": intent.route, "effective_route": "live"},
                )
            if os.getenv("Z_LIVE_TRADING_ENABLED", "0").strip() != "1":
                return GuardState(
                    False,
                    "exchange_disabled",
                    "exchange_disabled",
                    {"mode": intent.mode, "route": intent.route, "effective_route": "live"},
                )
            return GuardState(True, "", "ok", {"effective_route": "live"})

        if intent.mode == "noop":
            if intent.route != "noop":
                return GuardState(
                    False,
                    "noop_must_be_noop",
                    "noop_must_be_noop",
                    {"mode": intent.mode, "route": intent.route, "effective_route": "noop"},
                )
            return GuardState(True, "", "ok", {"effective_route": "noop"})

        return GuardState(
            False,
            "invalid_mode_boundary",
            "invalid_mode_boundary",
            {"mode": intent.mode, "route": intent.route},
        )

    def _route_noop(self, intent: OrderIntent, reason: str = "accepted_noop") -> ExecutionResult:
        return self._accept(intent, reason=reason, route="noop")

    def _route_paper(self, intent: OrderIntent) -> ExecutionResult:
        return self._accept(intent, reason="accepted_paper", route="paper")

    def _route_live(self, intent: OrderIntent) -> ExecutionResult:
        # 여기까지 왔으면 Z_LIVE_TRADING_ENABLED=1 상태
        # adapter 직연결 전이라 live는 최종 block
        return self._reject(
            intent,
            GuardState(
                False,
                "live_adapter_not_ready",
                "live_adapter_not_ready",
                {"mode": intent.mode, "route": intent.route, "env": self.env},
            ),
            route="live",
        )

    def route(self, intent: Any) -> ExecutionResult:
        obj = intent if isinstance(intent, OrderIntent) else OrderIntent.from_any(intent)

        guard = self._guard(obj)
        if not guard.ok:
            return self._reject(obj, guard)

        boundary = self._guard_boundary(obj)
        if not boundary.ok:
            if boundary.code == "exchange_disabled":
                return self._hold(obj, boundary, route="live")
            return self._reject(obj, boundary)

        # route 기준 분기 금지. mode 기준으로만 dispatch.
        if obj.mode == "noop":
            return self._route_noop(obj, reason="accepted_noop")

        if obj.mode == "dummy":
            return self._route_noop(obj, reason="accepted_dummy_noop")

        if obj.mode == "shadow":
            return self._route_noop(obj, reason="accepted_shadow_noop")

        if obj.mode == "paper":
            return self._route_paper(obj)

        if obj.mode == "live":
            return self._route_live(obj)

        return self._reject(
            obj,
            GuardState(
                False,
                "invalid_mode_dispatch",
                "invalid_mode_dispatch",
                {"mode": obj.mode, "route": obj.route},
            ),
        )

    def execute(self, intent: Any) -> ExecutionResult:
        return self.route(intent)

    def route_intent(self, intent: Any) -> ExecutionResult:
        return self.route(intent)

    def submit(self, intent: Any) -> ExecutionResult:
        return self.route(intent)

    def handle(self, intent: Any) -> ExecutionResult:
        return self.route(intent)

    def run(self, intent: Any) -> ExecutionResult:
        return self.route(intent)

__all__ = [
    "CONTRACT_EXECUTION_SIDES",
    "CONTRACT_RUNTIME_MODES",
    "CONTRACT_RUNTIME_ROUTES",
    "ALLOWED_EXCHANGES",
    "ALLOWED_ORDER_TYPES",
    "OrderIntent",
    "ExecutionResult",
    "ExecutionRouter",
]
