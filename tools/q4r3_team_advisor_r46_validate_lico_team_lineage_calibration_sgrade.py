#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import importlib
import importlib.util
import json
import os
import re
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "q4r3_team_advisor_r46_lico_team_lineage_calibration_sgrade_v1"
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
        return ["LICO_CALIBRATION_SYNTAX_INVALID"]
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


def load_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"MODULE_SPEC_INVALID:{name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def fixture(calibration, r36: dict[str, Any]):
    team_data = r36["report"]["teams"]["AlphaTeam"]
    team = calibration.TeamContext(
        selected_team="AlphaTeam",
        main_owner=team_data["main_owner"],
        support_owner=team_data["support_owner"],
        watcher_owners=tuple(team_data["watcher_owners"]),
        reserve_owner=team_data["reserve_owner"],
        helper_owner=None,
        helper_trigger="",
        mission=team_data["mission"],
        policy_family=team_data["policy_family"],
    )
    lineages = tuple(
        calibration.EvidenceLineage(
            position_id=f"paper.r46.{index}",
            decision_id=f"decision.r46.{index}",
            strategy_id="strategy.trend.v1",
            method_id="method.pullback.v1",
            skill_id="skill.runner.v1",
            source_ids=("cf:market", "sheets:policy"),
            evidence_ids=(f"shadow:{index}", f"paper:{index}"),
            contract_version="r46-fixture",
            decision_ts_ms=9000 + index,
        )
        for index in range(1, 4)
    )
    shadow = tuple(
        calibration.FillObservation(
            mode="shadow",
            position_id=item.position_id,
            decision_id=item.decision_id,
            symbol="BTCUSDT",
            side="long",
            fill_price=D("100") + D(index),
            fill_latency_ms=20 + index,
            partial_fill=False,
            net_r=D("0.50") + D(index) / D("100"),
            observed_at_ms=9100 + index,
            evidence_id=f"shadow:{index}",
        )
        for index, item in enumerate(lineages, start=1)
    )
    paper = tuple(
        calibration.FillObservation(
            mode="paper",
            position_id=item.position_id,
            decision_id=item.decision_id,
            symbol="BTCUSDT",
            side="long",
            fill_price=D("100.01") + D(index),
            fill_latency_ms=25 + index,
            partial_fill=False,
            net_r=D("0.51") + D(index) / D("100"),
            observed_at_ms=9200 + index,
            evidence_id=f"paper:{index}",
        )
        for index, item in enumerate(lineages, start=1)
    )
    policy = calibration.CalibrationPolicy(
        allowed_teams=tuple(sorted(calibration.ALL_TEAMS)),
        required_bots=tuple(sorted(calibration.ALL_BOTS)),
        minimum_sample_count=3,
        max_fill_price_error_bps=D("5"),
        max_fill_latency_error_ms=100,
        require_partial_fill_match=True,
        max_net_r_gap=D("0.10"),
        policy_refs=("cf:lico:calibration_policy", "sheets:lico:calibration_policy"),
        schema_version="r46-fixture",
    )
    return team, lineages, shadow, paper, policy


def prior_pass(payload: dict[str, Any], stage: str, fields: tuple[str, ...], next_route: str) -> bool:
    report = payload.get("report", {})
    return (
        payload.get("official_stage") == stage
        and payload.get("state") == "PASS"
        and not payload.get("blockers")
        and all(report.get(field) is True for field in fields)
        and report.get("next_route") == next_route
    )


def validate(
    worktree: Path,
    r36_path: Path,
    r42_path: Path,
    r43_path: Path,
    r44_path: Path,
    r45_path: Path,
    contract_path: Path,
) -> dict[str, Any]:
    blockers: list[str] = []
    r36 = read_json(r36_path)
    r42 = read_json(r42_path)
    r43 = read_json(r43_path)
    r44 = read_json(r44_path)
    r45 = read_json(r45_path)
    contract = read_json(contract_path)
    calibration_path = worktree / "canonical/lico_calibration.py"
    audit_path = worktree / "tools/q4r3_team_advisor_r41_lico_sgrade_gap_audit.py"
    owners = canonical_owner_paths(worktree)

    if r36.get("state") != "PASS" or r36.get("report", {}).get("sgrade_ready_count") != 4:
        blockers.append("R36_FOUR_TEAM_SGRADE_LOCK_NOT_PROVEN")
    if r36.get("report", {}).get("team_count") != 4:
        blockers.append("R36_TEAM_COUNT_INVALID")
    if not prior_pass(r42, "R4.2", ("source_consensus_ready",), "R4.3_LICO_MARKET_STREAM_VENUE_HEALTH"):
        blockers.append("R42_PASS_NOT_PROVEN")
    if not prior_pass(r43, "R4.3", ("market_stream_ready", "venue_health_ready"), "R4.4_LICO_EXECUTION_COST_REALISTIC_FILL"):
        blockers.append("R43_PASS_NOT_PROVEN")
    if not prior_pass(r44, "R4.4", ("execution_cost_ready", "realistic_fill_ready"), "R4.5_LICO_FEE_FUNDING_LIQUIDATION_STRESS"):
        blockers.append("R44_PASS_NOT_PROVEN")
    if not prior_pass(r45, "R4.5", ("fee_funding_liquidation_ready", "stress_scenarios_ready"), "R4.6_LICO_TEAM_LINEAGE_CALIBRATION_SGRADE_LOCK"):
        blockers.append("R45_PASS_NOT_PROVEN")

    if owners != ["canonical/lico.py"]:
        blockers.append("LICO_CANONICAL_OWNER_NOT_UNIQUE")
    if not calibration_path.is_file():
        blockers.append("LICO_CALIBRATION_MODEL_MISSING")
    if not audit_path.is_file():
        blockers.append("LICO_FINAL_AUDITOR_MISSING")
    if contract.get("schema") != "q4r3_lico_team_lineage_calibration_sgrade_contract_v1":
        blockers.append("LICO_CALIBRATION_CONTRACT_SCHEMA_INVALID")
    if contract.get("canonical_owner") != "canonical/lico.py":
        blockers.append("LICO_CALIBRATION_CONTRACT_OWNER_INVALID")
    if contract.get("sgrade_lock", {}).get("remaining_gap_count") != 0:
        blockers.append("LICO_SGRADE_CONTRACT_GAP_COUNT_INVALID")

    authority_hits = authority_violations(calibration_path) if calibration_path.is_file() else []
    if authority_hits:
        blockers.append("LICO_CALIBRATION_FORBIDDEN_AUTHORITY_SURFACE")

    calibration = None
    if calibration_path.is_file():
        sys.path.insert(0, str(worktree))
        try:
            calibration = importlib.import_module("canonical.lico_calibration")
        except Exception as exc:
            blockers.append(f"LICO_CALIBRATION_IMPORT_FAILED:{type(exc).__name__}")
        finally:
            if sys.path and sys.path[0] == str(worktree):
                sys.path.pop(0)

    team_ready = False
    lineage_ready = False
    calibration_ready = False
    route_change_count = 0
    fail_closed_count = 0
    sample_count = 0
    if calibration is not None:
        if calibration.MODEL_OWNER != "canonical/lico.py":
            blockers.append("LICO_CALIBRATION_OWNER_IDENTITY_INVALID")
        if calibration.EXECUTION_AUTHORITY != "none" or not calibration.OBSERVER_ONLY:
            blockers.append("LICO_CALIBRATION_AUTHORITY_BOUNDARY_INVALID")
        if calibration.RUNTIME_ENABLED or calibration.ORDER_ENABLED:
            blockers.append("LICO_CALIBRATION_RUNTIME_OR_ORDER_ENABLED")

        team, lineages, shadow, paper, policy = fixture(calibration, r36)
        result = calibration.evaluate_team_lineage_calibration(
            team, lineages, shadow, paper, policy=policy
        )
        team_ready = result.team_context
        lineage_ready = result.evidence_lineage
        calibration_ready = result.calibration and result.sgrade_ready
        sample_count = result.sample_count
        if not (
            result.state == "READY"
            and result.action == "hold"
            and team_ready
            and lineage_ready
            and result.actual_vs_simulated
            and calibration_ready
            and sample_count == 3
            and result.execution_authority == "none"
        ):
            blockers.append("LICO_TEAM_LINEAGE_CALIBRATION_NOT_READY")

        hold_cases = (
            (
                replace(team, watcher_owners=("OBot", "MBot")),
                lineages,
                shadow,
                paper,
            ),
            (
                team,
                (lineages[0], lineages[0], lineages[2]),
                shadow,
                paper,
            ),
            (
                team,
                (replace(lineages[0], source_ids=("sheets:policy",)), *lineages[1:]),
                shadow,
                paper,
            ),
            (
                team,
                lineages,
                (replace(shadow[0], observed_at_ms=lineages[0].decision_ts_ms - 1), *shadow[1:]),
                paper,
            ),
            (
                team,
                lineages[:2],
                shadow[:2],
                paper[:2],
            ),
        )
        for case_team, case_lineages, case_shadow, case_paper in hold_cases:
            case = calibration.evaluate_team_lineage_calibration(
                case_team, case_lineages, case_shadow, case_paper, policy=policy
            )
            if case.state == "HOLD" and case.action == "hold" and case.abstain and case.fail_closed:
                fail_closed_count += 1
        if fail_closed_count != 5:
            blockers.append("LICO_CALIBRATION_FAIL_CLOSED_MATRIX_INCOMPLETE")

        route_cases = (
            tuple(replace(item, fill_price=item.fill_price + D("1")) for item in paper),
            tuple(replace(item, partial_fill=True) for item in paper),
        )
        for case_paper in route_cases:
            case = calibration.evaluate_team_lineage_calibration(
                team, lineages, shadow, case_paper, policy=policy
            )
            if case.state == "READY" and case.action == "route_change" and not case.calibration:
                route_change_count += 1
        if route_change_count != 2:
            blockers.append("LICO_CALIBRATION_ROUTE_CHANGE_MATRIX_INCOMPLETE")

    final_surface_count = 0
    final_missing_count = 16
    final_audit_pass = False
    final_forbidden_count = 0
    if audit_path.is_file() and r36_path.is_file():
        try:
            auditor = load_path("q4r3_r46_final_lico_auditor", audit_path)
            audit = auditor.analyze(worktree, r36_path)
            audit_report = audit.get("report", {})
            final_surface_count = int(audit_report.get("ready_surface_count", 0))
            final_missing_count = int(audit_report.get("missing_surface_count", 16))
            final_forbidden_count = int(audit_report.get("forbidden_hit_count", 0))
            final_audit_pass = (
                audit.get("state") == "PASS"
                and not audit.get("blockers")
                and final_surface_count == 16
                and final_missing_count == 0
                and audit_report.get("canonical_owner_count") == 1
                and final_forbidden_count == 0
            )
            if not final_audit_pass:
                blockers.append("LICO_FINAL_16_SURFACE_AUDIT_FAILED")
        except Exception as exc:
            blockers.append(f"LICO_FINAL_AUDIT_FAILED:{type(exc).__name__}")

    state = "PASS" if not blockers else "HOLD"
    return {
        "schema": SCHEMA,
        "official_stage": "R4.6",
        "state": state,
        "verdict": "R46_LICO_SGRADE_LOCK_PASS" if state == "PASS" else "R46_LICO_SGRADE_LOCK_HOLD",
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
            "prior_stage_pass_count": sum(
                payload.get("state") == "PASS" and not payload.get("blockers")
                for payload in (r42, r43, r44, r45)
            ),
            "r36_team_sgrade_ready_count": int(r36.get("report", {}).get("sgrade_ready_count", 0)),
            "team_context_ready": team_ready,
            "evidence_lineage_ready": lineage_ready,
            "shadow_paper_calibration_ready": calibration_ready,
            "calibration_sample_count": sample_count,
            "fail_closed_scenario_count": fail_closed_count,
            "route_change_scenario_count": route_change_count,
            "final_surface_count": final_surface_count,
            "final_missing_surface_count": final_missing_count,
            "final_forbidden_authority_hit_count": final_forbidden_count,
            "final_16_surface_audit_pass": final_audit_pass,
            "forbidden_authority_hit_count": len(authority_hits),
            "closed_gap_count": 3 if state == "PASS" else 0,
            "remaining_gap_count": 0 if state == "PASS" else 3,
            "runtime_binding": False,
            "sgrade_ready": state == "PASS",
            "same_epoch_auto_apply": False,
            "next_route": "R5.1_ZBOT_SGRADE_GAP_AUDIT",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--r36", type=Path, required=True)
    parser.add_argument("--r42", type=Path, required=True)
    parser.add_argument("--r43", type=Path, required=True)
    parser.add_argument("--r44", type=Path, required=True)
    parser.add_argument("--r45", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = validate(
        args.worktree.resolve(),
        args.r36.resolve(),
        args.r42.resolve(),
        args.r43.resolve(),
        args.r44.resolve(),
        args.r45.resolve(),
        args.contract.resolve(),
    )
    atomic_json(args.output.resolve(), payload)
    print(json.dumps({
        "state": payload["state"],
        "team_context_ready": payload["report"]["team_context_ready"],
        "evidence_lineage_ready": payload["report"]["evidence_lineage_ready"],
        "shadow_paper_calibration_ready": payload["report"]["shadow_paper_calibration_ready"],
        "final_surface_count": payload["report"]["final_surface_count"],
        "remaining_gap_count": payload["report"]["remaining_gap_count"],
        "sgrade_ready": payload["report"]["sgrade_ready"],
        "blocker_count": len(payload["blockers"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
