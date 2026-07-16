#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import importlib
import json
import os
import re
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "q4r3_team_advisor_r45_lico_fee_funding_liquidation_stress_v1"
FORBIDDEN_CALLS = {
    "create_order", "place_order", "submit_order", "send_order", "cancel_order",
    "private_api", "private_endpoint",
}
SENSITIVE_KEY = re.compile(
    r"(?:BINGX|BITGET|KRAKEN|MEXC|BYBIT|BINANCE|OKX).*(?:API[_-]?KEY|SECRET|PASSPHRASE|PRIVATE[_-]?KEY)",
    re.I,
)
D = Decimal


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def authority_violations(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    violations: list[str] = []
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return ["LICO_RISK_SYNTAX_INVALID"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = dotted_name(node.func)
            if name.rsplit(".", 1)[-1].lower() in FORBIDDEN_CALLS:
                violations.append(f"DIRECT_EXECUTION_CALL:{name}:{getattr(node, 'lineno', 0)}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and SENSITIVE_KEY.search(node.value):
            violations.append(f"SENSITIVE_CREDENTIAL_LITERAL:{getattr(node, 'lineno', 0)}")
    return sorted(set(violations))


def canonical_owner_paths(worktree: Path) -> list[str]:
    canonical = worktree / "canonical"
    found: list[Path] = []
    direct = canonical / "lico.py"
    if direct.is_file():
        found.append(direct)
    package = canonical / "lico"
    if package.exists():
        found.extend(path for path in package.rglob("*") if path.is_file())
    return sorted(str(path.relative_to(worktree)) for path in found)


def fixtures(risk, execution):
    fill = execution.ExecutionFillEnvelope(
        state="READY", action="hold", reason_codes=("FULL_FILL",), request_id="r45",
        symbol="BTCUSDT", side="buy", order_type="market", fill_status="filled",
        requested_qty=D("1"), filled_qty=D("1"), unfilled_qty=D("0"), fill_ratio=D("1"),
        average_fill_price=D("100"), first_fill_price=D("100"), last_fill_price=D("100.01"),
        reference_mid_price=D("99.99"), spread_bps=D("2"), slippage_bps=D("0.5"),
        market_impact_bps=D("1"), execution_cost_bps=D("1"), walked_level_count=2,
        queue_ahead_qty=D("0"), first_fill_ts=9001, final_fill_ts=9002, fill_latency_ms=2,
        no_fill=False, partial_fill=False, order_book_walking=True, queue_model=False,
        execution_cost_ready=True, realistic_fill_model=True, accepted=True, fail_closed=True,
        abstain=False, observer_only=True, execution_authority="none", runtime_enabled=False,
        order_enabled=False, source_ref="cf:bingx:depth", schema_version="r45-fixture",
    )
    snapshot = risk.PositionRiskSnapshot(
        position_id="paper.r45.001", venue="BingX", symbol="BTCUSDT", side="long",
        quantity=D("1"), entry_price=D("100"), mark_price=D("102"), liquidation_price=D("80"),
        leverage=D("10"), margin_balance=D("20"), maintenance_margin=D("2"),
        opened_at_ms=8000, observed_at_ms=9900, funding_rate_8h=D("0.0001"),
        funding_intervals=1, entry_liquidity="maker", exit_liquidity="taker",
        source_ref="cf:paper:position",
    )
    policy = risk.RiskCostPolicy(
        maker_fee_rate=D("0.0002"), taker_fee_rate=D("0.0005"),
        max_abs_funding_rate_8h=D("0.001"), minimum_liq_buffer_pct=D("10"),
        minimum_margin_buffer_pct=D("20"), max_total_cost_bps=D("20"),
        max_stress_cost_bps=D("30"), max_snapshot_age_ms=1000, max_funding_intervals=8,
        required_stress_scenarios=tuple(sorted(risk.REQUIRED_STRESS_SCENARIOS)),
        policy_refs=("cf:lico:risk_policy", "sheets:lico:risk_policy"),
        schema_version="r45-fixture",
    )
    scenarios = (
        risk.StressScenario("capital_stress", D("1"), D("1"), D("0"), D("1"), D("10")),
        risk.StressScenario("liquidity_stress", D("1"), D("1.5"), D("1"), D("1"), D("0")),
        risk.StressScenario("execution_degradation", D("1"), D("2"), D("2"), D("1"), D("0")),
        risk.StressScenario("volatility_shock", D("5"), D("1"), D("0"), D("2"), D("0")),
    )
    return fill, snapshot, policy, scenarios


def validate(worktree: Path, r44_path: Path, contract_path: Path) -> dict[str, Any]:
    blockers: list[str] = []
    r44 = read_json(r44_path)
    contract = read_json(contract_path)
    risk_path = worktree / "canonical/lico_risk.py"
    owners = canonical_owner_paths(worktree)

    report44 = r44.get("report", {})
    if r44.get("state") != "PASS" or r44.get("blockers"):
        blockers.append("R44_PASS_NOT_PROVEN")
    if not report44.get("execution_cost_ready") or not report44.get("realistic_fill_ready"):
        blockers.append("R44_EXECUTION_FILL_NOT_READY")
    if report44.get("next_route") != "R4.5_LICO_FEE_FUNDING_LIQUIDATION_STRESS":
        blockers.append("R44_NEXT_ROUTE_INVALID")
    if owners != ["canonical/lico.py"]:
        blockers.append("LICO_CANONICAL_OWNER_NOT_UNIQUE")
    if not risk_path.is_file():
        blockers.append("LICO_RISK_MODEL_MISSING")
    if contract.get("schema") != "q4r3_lico_fee_funding_liquidation_stress_contract_v1":
        blockers.append("LICO_RISK_CONTRACT_SCHEMA_INVALID")
    if contract.get("canonical_owner") != "canonical/lico.py":
        blockers.append("LICO_RISK_CONTRACT_OWNER_INVALID")

    authority_hits = authority_violations(risk_path) if risk_path.is_file() else []
    if authority_hits:
        blockers.append("LICO_RISK_FORBIDDEN_AUTHORITY_SURFACE")

    risk = execution = None
    if not blockers:
        sys.path.insert(0, str(worktree))
        try:
            risk = importlib.import_module("canonical.lico_risk")
            execution = importlib.import_module("canonical.lico_execution")
        except Exception as exc:
            blockers.append(f"LICO_RISK_IMPORT_FAILED:{type(exc).__name__}")
        finally:
            if sys.path and sys.path[0] == str(worktree):
                sys.path.pop(0)

    ready = False
    stress_ready = False
    scenario_count = 0
    fail_closed_count = 0
    if risk is not None and execution is not None:
        if risk.MODEL_OWNER != "canonical/lico.py":
            blockers.append("LICO_RISK_OWNER_IDENTITY_INVALID")
        if risk.EXECUTION_AUTHORITY != "none" or not risk.OBSERVER_ONLY:
            blockers.append("LICO_RISK_AUTHORITY_BOUNDARY_INVALID")
        if risk.RUNTIME_ENABLED or risk.ORDER_ENABLED:
            blockers.append("LICO_RISK_RUNTIME_OR_ORDER_ENABLED")

        fill, snapshot, policy, scenarios = fixtures(risk, execution)
        result = risk.evaluate_fee_funding_liquidation_stress(
            snapshot, fill, scenarios=scenarios, now_ms=10000, policy=policy
        )
        ready = (
            result.state == "READY"
            and result.fee_funding_liquidation_model
            and result.execution_authority == "none"
            and not result.abstain
        )
        stress_ready = result.stress_scenarios
        scenario_count = result.stress_scenario_count
        if not ready:
            blockers.append("LICO_FEE_FUNDING_LIQUIDATION_NOT_READY")
        if not stress_ready or scenario_count != 4:
            blockers.append("LICO_STRESS_SCENARIO_MATRIX_INCOMPLETE")

        cases = (
            (replace(snapshot, observed_at_ms=1), fill, scenarios),
            (replace(snapshot, side="flat"), fill, scenarios),
            (snapshot, replace(fill, state="HOLD", execution_cost_ready=False), scenarios),
            (snapshot, fill, scenarios[:-1]),
        )
        for case_snapshot, case_fill, case_scenarios in cases:
            case = risk.evaluate_fee_funding_liquidation_stress(
                case_snapshot, case_fill, scenarios=case_scenarios, now_ms=10000, policy=policy
            )
            if case.state == "HOLD" and case.action == "hold" and case.abstain and case.fail_closed:
                fail_closed_count += 1
        if fail_closed_count != 4:
            blockers.append("LICO_RISK_FAIL_CLOSED_MATRIX_INCOMPLETE")

        breach = risk.evaluate_fee_funding_liquidation_stress(
            replace(snapshot, liquidation_price=D("95")),
            fill,
            scenarios=tuple(
                replace(item, adverse_mark_move_pct=D("10")) if item.name == "volatility_shock" else item
                for item in scenarios
            ),
            now_ms=10000,
            policy=policy,
        )
        if breach.action != "route_change" or not breach.liquidation_breached:
            blockers.append("LICO_LIQUIDATION_STRESS_ROUTE_CHANGE_MISSING")

    state = "PASS" if not blockers else "HOLD"
    return {
        "schema": SCHEMA,
        "official_stage": "R4.5",
        "state": state,
        "verdict": "R45_LICO_FEE_FUNDING_LIQUIDATION_STRESS_PASS" if state == "PASS" else "R45_LICO_FEE_FUNDING_LIQUIDATION_STRESS_HOLD",
        "action": "hold",
        "authority": {
            "observer_only": True,
            "execution_authority": "none",
            "order_authority": "none",
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
        },
        "blockers": sorted(set(blockers)),
        "report": {
            "canonical_owner_count": len(owners),
            "fee_funding_liquidation_ready": ready,
            "stress_scenarios_ready": stress_ready,
            "stress_scenario_count": scenario_count,
            "fail_closed_scenario_count": fail_closed_count,
            "forbidden_authority_hit_count": len(authority_hits),
            "closed_gap_count": 2 if state == "PASS" else 0,
            "remaining_gap_count": 3,
            "runtime_binding": False,
            "sgrade_ready": False,
            "next_route": "R4.6_LICO_TEAM_LINEAGE_CALIBRATION_SGRADE_LOCK",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--r44", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = validate(args.worktree.resolve(), args.r44.resolve(), args.contract.resolve())
    atomic_json(args.output.resolve(), payload)
    print(json.dumps({
        "state": payload["state"],
        "fee_funding_liquidation_ready": payload["report"]["fee_funding_liquidation_ready"],
        "stress_scenarios_ready": payload["report"]["stress_scenarios_ready"],
        "stress_scenario_count": payload["report"]["stress_scenario_count"],
        "fail_closed_scenario_count": payload["report"]["fail_closed_scenario_count"],
        "remaining_gap_count": payload["report"]["remaining_gap_count"],
        "blocker_count": len(payload["blockers"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
