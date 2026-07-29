# ZOPS_PROMOTION_GATE_V2_ACTUAL_BACKEND_MOUNT_V2
# Advisory-only Promotion Gate API. No exchange/order mutation.
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from fastapi import APIRouter, Body
except Exception:  # pragma: no cover
    APIRouter = None  # type: ignore
    Body = None  # type: ignore

CONTRACT_VERSION = "promotion_gate_v2_actual_backend_mount_v2"
AUTHORITY = "advisory_only"
ORDER_MUTATION = "blocked"
PHASE = "phase-7-promotion-gate-v2-regression-harness-v1"
DATA_DIR = Path(os.environ.get("ZOPS_DATA_DIR", "/home/z/z/data")) / "promotion"
ALIMI_OUTBOX = Path(os.environ.get("ZOPS_ALIMI_OUTBOX", "/home/z/z/data/alimi/outbox.jsonl"))
CONFIG_PATH = DATA_DIR / "promotion_gate_v2_config.json"
DECISIONS_PATH = DATA_DIR / "promotion_decisions.jsonl"
REGRESSION_PATH = DATA_DIR / "regression_runs.jsonl"
ACTIONS = ["reduce25", "partial30", "hold", "stop", "route_change", "rollback", "block"]

DEFAULT_CONFIG: Dict[str, Any] = {
    "contract_version": CONTRACT_VERSION,
    "authority": AUTHORITY,
    "order_mutation": ORDER_MUTATION,
    "os_final_approval_required": True,
    "min_winrate_pct": 55.0,
    "min_expectancy_R": 0.05,
    "max_dd_pct": 5.0,
    "max_slippage_bps": 8.0,
    "max_funding_cost_pct": 0.25,
    "max_proof_freshness_ms": 60000,
    "min_route_stability_pct": 98.0,
    "max_shadow_live_divergence_bps": 12.0,
    "min_canary_days": 14,
    "min_trade_count": 30,
    "min_regime_similarity_pct": 70.0,
    "max_correlation_pct": 70.0,
    "max_exposure_pct": 100.0,
    "max_leverage": 20.0,
    "min_liq_buffer_pct": 10.0,
    "max_latency_ms": 750,
    "max_partial_fill_rate_pct": 12.0,
    "max_rejection_rate_pct": 3.0,
    "min_regression_pass_rate_pct": 100.0,
    "canary_capital_cap_pct": 5.0,
    "live_requires_manual_os_approval": True,
    "allowed_actions": ACTIONS,
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ALIMI_OUTBOX.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _config() -> Dict[str, Any]:
    _ensure()
    cfg = dict(DEFAULT_CONFIG)
    user = _read_json(CONFIG_PATH, {})
    if isinstance(user, dict):
        cfg.update(user)
    cfg["authority"] = AUTHORITY
    cfg["order_mutation"] = ORDER_MUTATION
    cfg["os_final_approval_required"] = True
    cfg["allowed_actions"] = ACTIONS
    return cfg


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _last_jsonl(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    last = None
    try:
        for line in path.open("r", encoding="utf-8"):
            line = line.strip()
            if line:
                last = json.loads(line)
    except Exception:
        return last
    return last


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return sum(1 for _ in path.open("r", encoding="utf-8"))
    except Exception:
        return 0


def _append_jsonl(path: Path, record: Dict[str, Any]) -> Dict[str, Any]:
    _ensure()
    prev = _last_jsonl(path) or {}
    out = dict(record)
    out.setdefault("ts_ms", _now_ms())
    out["prev_hash"] = prev.get("record_hash", "GENESIS")
    out["record_hash"] = _hash({k: v for k, v in out.items() if k != "record_hash"})
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False, sort_keys=True) + "\n")
    return out


def _sample() -> Dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "strategy": "alpha1",
        "team": "Alpha",
        "mode": "canary",
        "manual_os_approval": False,
        "decision_id": "decision_sample_001",
        "metrics": {
            "winrate_pct": 61.2,
            "expectancy_R": 0.18,
            "maxDD_pct": 2.7,
            "slippage_bps": 4.1,
            "funding_cost_pct": 0.04,
            "proof_freshness_ms": 18000,
            "route_stability_pct": 99.2,
            "shadow_live_divergence_bps": 5.5,
            "canary_days": 16,
            "trade_count": 41,
            "regime_similarity_pct": 78.0,
            "correlation_pct": 45.0,
            "exposure_pct": 25.0,
            "leverage": 3.0,
            "liq_buffer_pct": 31.5,
            "latency_ms": 122,
            "partial_fill_rate_pct": 1.8,
            "rejection_rate_pct": 0.3,
            "regression_pass_rate_pct": 100.0,
        },
    }


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except Exception:
        return None


def _check(name: str, value: Any, limit: Any, direction: str, unit: str, required: bool = True) -> Dict[str, Any]:
    x = _num(value)
    lim = _num(limit)
    if x is None or lim is None:
        return {"metric": name, "ok": False if required else True, "missing": x is None, "value": value, "limit": limit, "direction": direction, "unit": unit, "severity": "C" if required else "m", "reason": f"{name} missing_or_invalid"}
    ok = x >= lim if direction == ">=" else x <= lim
    return {"metric": name, "ok": bool(ok), "missing": False, "value": x, "limit": lim, "direction": direction, "unit": unit, "severity": "ok" if ok else ("C" if required else "M"), "reason": "ok" if ok else f"{name} {x}{unit} violates {direction} {lim}{unit}"}


def evaluate(payload: Dict[str, Any]) -> Dict[str, Any]:
    cfg = _config()
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else payload
    symbol = str(payload.get("symbol") or metrics.get("symbol") or "UNKNOWN")
    strategy = str(payload.get("strategy") or metrics.get("strategy") or "unknown")
    team = str(payload.get("team") or metrics.get("team") or "unknown")
    mode = str(payload.get("mode") or metrics.get("mode") or "paper").lower()
    manual = bool(payload.get("manual_os_approval", False))

    checks: List[Dict[str, Any]] = [
        _check("winrate_pct", metrics.get("winrate_pct"), cfg["min_winrate_pct"], ">=", "%"),
        _check("expectancy_R", metrics.get("expectancy_R"), cfg["min_expectancy_R"], ">=", "R"),
        _check("maxDD_pct", metrics.get("maxDD_pct"), cfg["max_dd_pct"], "<=", "%"),
        _check("slippage_bps", metrics.get("slippage_bps"), cfg["max_slippage_bps"], "<=", "bps"),
        _check("funding_cost_pct", metrics.get("funding_cost_pct"), cfg["max_funding_cost_pct"], "<=", "%"),
        _check("proof_freshness_ms", metrics.get("proof_freshness_ms"), cfg["max_proof_freshness_ms"], "<=", "ms"),
        _check("route_stability_pct", metrics.get("route_stability_pct"), cfg["min_route_stability_pct"], ">=", "%"),
        _check("shadow_live_divergence_bps", metrics.get("shadow_live_divergence_bps"), cfg["max_shadow_live_divergence_bps"], "<=", "bps"),
        _check("canary_days", metrics.get("canary_days"), cfg["min_canary_days"], ">=", "d"),
        _check("trade_count", metrics.get("trade_count"), cfg["min_trade_count"], ">=", "trades"),
        _check("regime_similarity_pct", metrics.get("regime_similarity_pct"), cfg["min_regime_similarity_pct"], ">=", "%"),
        _check("correlation_pct", metrics.get("correlation_pct"), cfg["max_correlation_pct"], "<=", "%"),
        _check("exposure_pct", metrics.get("exposure_pct"), cfg["max_exposure_pct"], "<=", "%"),
        _check("leverage", metrics.get("leverage"), cfg["max_leverage"], "<=", "x"),
        _check("liq_buffer_pct", metrics.get("liq_buffer_pct"), cfg["min_liq_buffer_pct"], ">=", "%"),
        _check("latency_ms", metrics.get("latency_ms"), cfg["max_latency_ms"], "<=", "ms"),
        _check("partial_fill_rate_pct", metrics.get("partial_fill_rate_pct"), cfg["max_partial_fill_rate_pct"], "<=", "%"),
        _check("rejection_rate_pct", metrics.get("rejection_rate_pct"), cfg["max_rejection_rate_pct"], "<=", "%"),
        _check("regression_pass_rate_pct", metrics.get("regression_pass_rate_pct"), cfg["min_regression_pass_rate_pct"], ">=", "%"),
    ]
    failed = [c for c in checks if not c.get("ok")]
    missing = [c for c in failed if c.get("missing")]
    action = "hold"
    eligible_next_mode = mode
    reason = "promotion eligible; manual OS approval still required" if not failed else failed[0]["reason"]
    if missing:
        action = "hold"
    elif failed:
        action = "block" if any(c.get("severity") == "C" for c in failed) else "hold"
    elif mode in ("paper", "shadow"):
        eligible_next_mode = "canary"
    elif mode == "canary" and manual:
        eligible_next_mode = "live"
    elif mode == "canary" and not manual:
        eligible_next_mode = "canary_pending_os_approval"

    decision = {
        "decision_id": str(payload.get("decision_id") or f"promotion_{_now_ms()}_{symbol}_{strategy}"),
        "contract_version": CONTRACT_VERSION,
        "phase": PHASE,
        "symbol": symbol,
        "strategy": strategy,
        "team": team,
        "mode": mode,
        "eligible_next_mode": eligible_next_mode,
        "approved_by_os": manual,
        "action": action,
        "allowed_actions": ACTIONS,
        "authority": AUTHORITY,
        "order_mutation": ORDER_MUTATION,
        "os_final_approval_required": True,
        "checks": checks,
        "failed_count": len(failed),
        "missing_count": len(missing),
        "reason": reason,
        "ts_ms": _now_ms(),
    }
    return decision


def _make_router():
    if APIRouter is None:
        raise RuntimeError("fastapi_missing")
    router = APIRouter(prefix="/api/promotion", tags=["zops-promotion-gate-v2"])

    @router.get("/health")
    def health() -> Dict[str, Any]:
        _ensure()
        return {"ok": True, "service": "promotion_gate_v2", "contract_version": CONTRACT_VERSION, "authority": AUTHORITY, "order_mutation": ORDER_MUTATION, "mounted": True, "ts_ms": _now_ms()}

    @router.get("/status")
    def status() -> Dict[str, Any]:
        _ensure()
        last_decision = _last_jsonl(DECISIONS_PATH)
        last_regression = _last_jsonl(REGRESSION_PATH)
        return {"ok": True, "phase": PHASE, "contract_version": CONTRACT_VERSION, "authority": AUTHORITY, "order_mutation": ORDER_MUTATION, "os_final_approval_required": True, "config": _config(), "decision_count": _count_jsonl(DECISIONS_PATH), "regression_count": _count_jsonl(REGRESSION_PATH), "last_decision": last_decision, "last_regression": last_regression, "ts_ms": _now_ms()}

    @router.get("/sample")
    def sample() -> Dict[str, Any]:
        payload = _sample()
        decision = evaluate(payload)
        return {"ok": True, "sample_payload": payload, "decision": decision, "contract": {"authority": AUTHORITY, "order_mutation": ORDER_MUTATION, "os_final_approval_required": True}}

    @router.post("/evaluate")
    def evaluate_route(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:  # type: ignore
        decision = _append_jsonl(DECISIONS_PATH, evaluate(payload or _sample()))
        if decision["action"] in ("block", "hold") and decision.get("failed_count", 0) > 0:
            _append_jsonl(ALIMI_OUTBOX, {"type": "promotion_gate", "symbol": decision["symbol"], "strategy": decision["strategy"], "metric": decision["reason"], "action": decision["action"], "sev": "C" if decision["action"] == "block" else "M", "src": "backend:/api/promotion/evaluate", "decision_id": decision["decision_id"]})
        return {"ok": True, "decision": decision}

    @router.post("/regression/run")
    def regression_run(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:  # type: ignore
        suite = str((payload or {}).get("suite") or "manual_smoke")
        cases = [
            {"name": "paper_to_canary_nominal", "payload": _sample(), "expect_action": "hold"},
            {"name": "missing_metric_hold", "payload": {"symbol": "BTCUSDT", "strategy": "alpha1", "metrics": {"winrate_pct": 60}}, "expect_action": "hold"},
            {"name": "dd_violation_block", "payload": {**_sample(), "metrics": {**_sample()["metrics"], "maxDD_pct": 9.9}}, "expect_action": "block"},
        ]
        results = []
        for case in cases:
            d = evaluate(case["payload"])
            passed = d["action"] == case["expect_action"]
            results.append({"name": case["name"], "passed": passed, "expected": case["expect_action"], "actual": d["action"], "decision_id": d["decision_id"]})
        passed_count = sum(1 for r in results if r["passed"])
        run = {"suite": suite, "contract_version": CONTRACT_VERSION, "passed": passed_count == len(results), "pass_rate_pct": round(100.0 * passed_count / max(len(results), 1), 2), "results": results, "authority": AUTHORITY, "order_mutation": ORDER_MUTATION, "ts_ms": _now_ms()}
        run = _append_jsonl(REGRESSION_PATH, run)
        return {"ok": True, "run": run}

    return router


def mount_promotion_gate(app: Any) -> Dict[str, Any]:
    """Idempotently mount Promotion Gate v2 routes onto a FastAPI app."""
    existing = set()
    try:
        existing = {getattr(r, "path", "") for r in getattr(app, "routes", [])}
    except Exception:
        existing = set()
    wanted = {"/api/promotion/health", "/api/promotion/status", "/api/promotion/sample", "/api/promotion/evaluate", "/api/promotion/regression/run"}
    if wanted.issubset(existing):
        return {"mounted": False, "reason": "already_present", "routes": sorted(wanted)}
    router = _make_router()
    app.include_router(router)
    return {"mounted": True, "routes": sorted(wanted), "contract_version": CONTRACT_VERSION}
