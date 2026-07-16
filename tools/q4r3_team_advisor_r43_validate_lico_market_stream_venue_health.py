#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "q4r3_team_advisor_r43_lico_market_stream_venue_health_v1"
FORBIDDEN_CALLS = {
    "create_order", "place_order", "submit_order", "send_order", "cancel_order",
    "private_api", "private_endpoint",
}
SENSITIVE_KEY = re.compile(
    r"(?:BINGX|BITGET|KRAKEN|MEXC|BYBIT|BINANCE|OKX).*(?:API[_-]?KEY|SECRET|PASSPHRASE|PRIVATE[_-]?KEY)",
    re.I,
)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("canonical_lico_r43", path)
    if not spec or not spec.loader:
        raise RuntimeError("LICO_MODULE_SPEC_INVALID")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
        return ["LICO_CANONICAL_SYNTAX_INVALID"]
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


def source_consensus(module):
    policy = module.SourceConsensusPolicy(
        required_source_prefixes=("cf:", "sheets:"),
        required_metrics=("mark_price",),
        max_age_ms=1000,
        numeric_tolerance_by_metric={"mark_price": Decimal("0")},
        minimum_source_confidence=Decimal("0.8"),
        policy_refs=("cf:lico_policy", "sheets:lico_policy"),
        schema_version="r43-validator",
    )
    observations = (
        module.SourceObservation("cf:market", "mark_price", Decimal("100"), 9900, "ready", Decimal("0.9"), "cf:market:mark"),
        module.SourceObservation("sheets:market", "mark_price", Decimal("100"), 9900, "ready", Decimal("0.9"), "sheets:market:mark"),
    )
    return module.evaluate_source_consensus(observations, now_ms=10000, policy=policy)


def venue_policy(module):
    return module.VenueHealthPolicy(
        venue="BingX",
        max_stream_age_ms=1000,
        max_sequence_gap=5,
        minimum_book_levels=2,
        max_mark_index_deviation_bps=Decimal("20"),
        allowed_venue_statuses=("normal", "degraded"),
        policy_refs=("cf:lico_venue_policy", "sheets:lico_venue_policy"),
        schema_version="r43-validator",
    )


def snapshot(module, **changes):
    values = {
        "venue": "BingX",
        "symbol": "BTC-USDT",
        "observed_at_ms": 9950,
        "sequence": 101,
        "best_bid": Decimal("99.9"),
        "best_ask": Decimal("100.1"),
        "mark_price": Decimal("100"),
        "index_price": Decimal("100"),
        "funding_rate": Decimal("0.0001"),
        "order_book": ((Decimal("99.9"), Decimal("2")), (Decimal("100.1"), Decimal("3"))),
        "trade_stream": True,
        "venue_status": "normal",
        "source_ref": "cf:bingx_public:BTCUSDT",
    }
    values.update(changes)
    return module.MarketStreamSnapshot(**values)


def ready_scenario(module) -> bool:
    result = module.evaluate_market_stream(
        snapshot(module),
        previous=snapshot(module, sequence=100, observed_at_ms=9900),
        consensus=source_consensus(module),
        now_ms=10000,
        policy=venue_policy(module),
    )
    return (
        result.state == "READY"
        and result.market_stream_ready
        and result.venue_health == "healthy"
        and result.execution_authority == "none"
        and not result.abstain
    )


def fail_closed_count(module) -> int:
    consensus = source_consensus(module)
    policy = venue_policy(module)
    cases = [
        (snapshot(module, observed_at_ms=1), None),
        (snapshot(module, sequence=100), snapshot(module, sequence=100, observed_at_ms=9900)),
        (snapshot(module, sequence=110), snapshot(module, sequence=100, observed_at_ms=9900)),
        (snapshot(module, best_bid=Decimal("101"), best_ask=Decimal("100")), None),
        (snapshot(module, trade_stream=False), None),
        (snapshot(module, venue_status="maintenance"), None),
        (snapshot(module, mark_price=Decimal("101"), index_price=Decimal("100")), None),
        (snapshot(module, source_ref="sheets:market:BTCUSDT"), None),
    ]
    count = 0
    for current, previous in cases:
        result = module.evaluate_market_stream(
            current,
            previous=previous,
            consensus=consensus,
            now_ms=10000,
            policy=policy,
        )
        if result.state == "HOLD" and result.action == "hold" and result.fail_closed and result.abstain:
            count += 1
    return count


def validate(worktree: Path, r42_path: Path, contract_path: Path) -> dict[str, Any]:
    blockers: list[str] = []
    r42 = read_json(r42_path)
    contract = read_json(contract_path)
    owner = worktree / "canonical/lico.py"
    owners = canonical_owner_paths(worktree)

    if r42.get("state") != "PASS" or r42.get("blockers"):
        blockers.append("R42_PASS_NOT_PROVEN")
    r42_report = r42.get("report", {})
    if r42_report.get("canonical_owner_count") != 1:
        blockers.append("R42_CANONICAL_OWNER_NOT_PROVEN")
    if not r42_report.get("source_consensus_ready"):
        blockers.append("R42_SOURCE_CONSENSUS_NOT_PROVEN")
    if r42_report.get("next_route") != "R4.3_LICO_MARKET_STREAM_VENUE_HEALTH":
        blockers.append("R42_NEXT_ROUTE_INVALID")

    if owners != ["canonical/lico.py"]:
        blockers.append("LICO_CANONICAL_OWNER_NOT_UNIQUE")
    if contract.get("schema") != "q4r3_lico_market_stream_venue_health_contract_v1":
        blockers.append("LICO_R43_CONTRACT_SCHEMA_INVALID")
    if contract.get("canonical_owner") != "canonical/lico.py" or contract.get("venue") != "BingX":
        blockers.append("LICO_R43_CONTRACT_IDENTITY_INVALID")

    module = None
    authority_hits: list[str] = []
    if owner.is_file():
        authority_hits = authority_violations(owner)
        if authority_hits:
            blockers.append("LICO_FORBIDDEN_AUTHORITY_SURFACE")
        try:
            module = load_module(owner)
        except Exception as exc:
            blockers.append(f"LICO_IMPORT_FAILED:{type(exc).__name__}")
    else:
        blockers.append("LICO_CANONICAL_OWNER_MISSING")

    ready = False
    scenario_count = 0
    if module is not None:
        required = (
            "MarketStreamSnapshot", "VenueHealthPolicy", "VenueHealthEnvelope", "evaluate_market_stream"
        )
        if any(not hasattr(module, name) for name in required):
            blockers.append("LICO_MARKET_SURFACE_INCOMPLETE")
        if module.EXECUTION_AUTHORITY != "none" or not module.OBSERVER_ONLY:
            blockers.append("LICO_AUTHORITY_BOUNDARY_INVALID")
        if module.RUNTIME_ENABLED or module.ORDER_ENABLED:
            blockers.append("LICO_RUNTIME_OR_ORDER_ENABLED")
        ready = ready_scenario(module)
        if not ready:
            blockers.append("LICO_MARKET_STREAM_VENUE_NOT_READY")
        scenario_count = fail_closed_count(module)
        if scenario_count != 8:
            blockers.append("LICO_MARKET_FAIL_CLOSED_MATRIX_INCOMPLETE")

    state = "PASS" if not blockers else "HOLD"
    return {
        "schema": SCHEMA,
        "official_stage": "R4.3",
        "state": state,
        "verdict": "R43_LICO_MARKET_STREAM_VENUE_HEALTH_PASS" if state == "PASS" else "R43_LICO_MARKET_STREAM_VENUE_HEALTH_HOLD",
        "action": "hold",
        "authority": {
            "observer_only": True,
            "execution_authority": "none",
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
            "order_authority": "none",
        },
        "blockers": sorted(set(blockers)),
        "report": {
            "canonical_owner_count": len(owners),
            "market_stream_ready": ready,
            "venue_health_ready": ready,
            "bingx_public_only": True,
            "fail_closed_scenario_count": scenario_count,
            "forbidden_authority_hit_count": len(authority_hits),
            "closed_gap_count": 2 if state == "PASS" else 0,
            "remaining_gap_count": 7,
            "sgrade_ready": False,
            "runtime_binding": False,
            "next_route": "R4.4_LICO_EXECUTION_COST_REALISTIC_FILL",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--r42", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = validate(args.worktree.resolve(), args.r42.resolve(), args.contract.resolve())
    atomic_json(args.output.resolve(), payload)
    print(json.dumps({
        "state": payload["state"],
        "market_stream_ready": payload["report"]["market_stream_ready"],
        "venue_health_ready": payload["report"]["venue_health_ready"],
        "fail_closed_scenario_count": payload["report"]["fail_closed_scenario_count"],
        "remaining_gap_count": payload["report"]["remaining_gap_count"],
        "blocker_count": len(payload["blockers"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
