from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
HARDENING_POLICY_PATH = ROOT / "backend/research/zel_economic_hardening_policy_v1.json"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def finite(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return x if math.isfinite(x) else None


def load_policy(path: Path = HARDENING_POLICY_PATH) -> dict[str, Any]:
    row = json.loads(path.read_text(encoding="utf-8"))
    if row.get("schema_version") != "zel.economic_hardening.policy.v2":
        raise RuntimeError("A1_SURVIVOR_GATE_HARDENING_POLICY_INVALID")
    return row


def load_external_hardening_evidence() -> dict[str, Any] | None:
    """Read an explicitly supplied existing hardening receipt only.

    Production has no permission to synthesize OOS/retention/H4 evidence. If the
    environment path is absent, unreadable, or not an object, the gate remains
    PENDING and passed=false.
    """
    raw = os.environ.get("A1_HARDENING_RECEIPT_PATH", "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_file():
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return row if isinstance(row, dict) else None


def _completed_symbols(receipt: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    for trade in receipt.get("trades") or []:
        if isinstance(trade, Mapping) and str(trade.get("symbol") or "").strip():
            out.add(str(trade["symbol"]))
    return out


def _check(name: str, state: str, actual: Any = None, required: Any = None, source: str | None = None) -> dict[str, Any]:
    return {"name": name, "state": state, "actual": actual, "required": required, "source": source}


def _bool_state(value: bool) -> str:
    return "PASS" if value else "FAIL"


def build_survivor_gate(
    receipt: Mapping[str, Any],
    hardening_evidence: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = dict(policy or load_policy())
    gate_cfg = cfg.get("survivor_gate") or {}
    h4_cfg = cfg.get("h4_placebo_negative_controls") or {}
    checks: list[dict[str, Any]] = []

    trades_n = int(receipt.get("completed_trades") or 0)
    symbols = _completed_symbols(receipt)
    checks.append(_check("tier_a_completed_trades", _bool_state(trades_n >= 25), trades_n, ">=25", "generic_receipt"))
    checks.append(_check("tier_a_completed_symbols", _bool_state(len(symbols) >= 2), len(symbols), ">=2", "generic_receipt.trades"))

    metrics = receipt.get("metrics") if isinstance(receipt.get("metrics"), Mapping) else {}
    economic_rules = [
        ("net_pnl_positive", finite(metrics.get("net_pnl_bps")), lambda x: x > float(gate_cfg.get("minimum_net_R", 0.0)), ">0"),
        ("net_expectancy_positive", finite(metrics.get("net_expectancy_bps")), lambda x: x > float(gate_cfg.get("minimum_expectancy_R", 0.0)), ">0"),
        ("profit_factor", finite(metrics.get("net_profit_factor")), lambda x: x >= float(gate_cfg.get("minimum_profit_factor", 1.0)), f">={gate_cfg.get('minimum_profit_factor',1.0)}"),
        ("payoff", finite(metrics.get("net_payoff")), lambda x: x >= float(gate_cfg.get("minimum_payoff_ratio", 1.0)), f">={gate_cfg.get('minimum_payoff_ratio',1.0)}"),
    ]
    for name, actual, predicate, required in economic_rules:
        state = "PENDING" if actual is None else _bool_state(predicate(actual))
        checks.append(_check(name, state, actual, required, "generic_receipt.metrics"))

    defects = list(receipt.get("integrity_defects") or [])
    leakage = int(receipt.get("leakage_lookahead") or 0)
    checks.append(_check("integrity_defects_zero", _bool_state(not defects), len(defects), 0, "generic_receipt"))
    checks.append(_check("leakage_zero", _bool_state(leakage == 0), leakage, 0, "generic_receipt"))

    evidence = dict(hardening_evidence) if isinstance(hardening_evidence, Mapping) else None
    if evidence is None:
        for name in ("retention_positive", "oos_positive", "negative_control_superiority"):
            checks.append(_check(name, "PENDING", None, "explicit_existing_hardening_receipt", None))
    else:
        retention = finite(evidence.get("retention_pct"))
        min_retention = float(gate_cfg.get("minimum_retention_pct", 60.0))
        checks.append(_check("retention_positive", "PENDING" if retention is None else _bool_state(retention >= min_retention), retention, f">={min_retention}", "hardening_evidence"))

        oos = evidence.get("oos") if isinstance(evidence.get("oos"), Mapping) else {}
        oos_net = finite(oos.get("net_pnl_bps"))
        oos_exp = finite(oos.get("net_expectancy_bps"))
        oos_ok = oos_net is not None and oos_exp is not None and oos_net > 0 and oos_exp > 0
        oos_state = "PENDING" if oos_net is None or oos_exp is None else _bool_state(oos_ok)
        checks.append(_check("oos_positive", oos_state, {"net_pnl_bps": oos_net, "net_expectancy_bps": oos_exp}, {"net_pnl_bps": ">0", "net_expectancy_bps": ">0"}, "hardening_evidence.oos"))

        h4 = evidence.get("negative_control") if isinstance(evidence.get("negative_control"), Mapping) else {}
        required_controls = list(h4_cfg.get("required_controls") or [])
        controls = h4.get("controls") if isinstance(h4.get("controls"), Mapping) else {}
        p_value = finite(h4.get("p_value"))
        ci_low = finite(h4.get("candidate_minus_control_ci_low_R"))
        same_budget = h4.get("equal_trade_budget") is True
        same_cost = h4.get("identical_cost_model_sha") is True
        same_window = h4.get("identical_window_sha") is True
        receipt_state = str(h4.get("state") or "")
        controls_ok = all(name in controls and isinstance(controls[name], Mapping) and controls[name].get("state") == "PASS" for name in required_controls)
        h4_complete = p_value is not None and ci_low is not None and bool(required_controls)
        h4_ok = (
            h4_complete
            and receipt_state == str(h4_cfg.get("required_source_receipt_state"))
            and controls_ok
            and p_value <= float(h4_cfg.get("maximum_p_value", 0.05))
            and ci_low >= float(h4_cfg.get("minimum_candidate_minus_control_ci_low_R", 0.0))
            and (same_budget or not h4_cfg.get("require_equal_trade_budget"))
            and (same_cost or not h4_cfg.get("require_identical_cost_model_sha"))
            and (same_window or not h4_cfg.get("require_identical_window_sha"))
        )
        h4_state = "PENDING" if not h4_complete else _bool_state(h4_ok)
        checks.append(_check("negative_control_superiority", h4_state, {"state": receipt_state, "p_value": p_value, "ci_low_R": ci_low, "controls_present": sorted(controls), "equal_trade_budget": same_budget, "identical_cost_model_sha": same_cost, "identical_window_sha": same_window}, {"state": h4_cfg.get("required_source_receipt_state"), "p_value_max": h4_cfg.get("maximum_p_value"), "ci_low_R_min": h4_cfg.get("minimum_candidate_minus_control_ci_low_R"), "required_controls": required_controls}, "hardening_evidence.negative_control"))

    failed = [x["name"] for x in checks if x["state"] == "FAIL"]
    pending = [x["name"] for x in checks if x["state"] == "PENDING"]
    passed = not failed and not pending and bool(checks)
    state = "PASS" if passed else ("FAIL" if failed else "PENDING")
    return {
        "schema_version": "zel.a1_exact25.generic_survivor_gate.v1",
        "state": state,
        "passed": passed,
        "tier": "A",
        "checks": checks,
        "failed_checks": failed,
        "pending_checks": pending,
        "hardening_policy_sha256": stable_sha(cfg),
        "hardening_evidence_sha256": stable_sha(evidence) if evidence is not None else None,
        "synthetic_pass_forbidden": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
    }


def attach_survivor_gate(receipt: dict[str, Any], hardening_evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    out = json.loads(json.dumps(receipt, allow_nan=False, default=str))
    gate = build_survivor_gate(out, hardening_evidence=hardening_evidence)
    out["survivor_gate"] = gate
    nc = next((x for x in gate["checks"] if x["name"] == "negative_control_superiority"), None)
    if nc is not None:
        out["negative_control_gate"] = f"{nc['state']}_H4_NEGATIVE_CONTROL_SUPERIORITY"
    out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out
