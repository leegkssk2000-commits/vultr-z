from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.production.zel_production_economic_edge_router_v1 import enrich_factory_dynamic_state, route_tick


def policy() -> dict:
    return json.loads(Path("config/zel_production_economic_edge_router_v1.json").read_text())


def bootstrap() -> dict:
    return {
        "schema_version": "zel.production_performance_bootstrap.v1",
        "state": "HOLD_BOOTSTRAP_ADMISSION_REJECTED_ROUTE_CHANGE",
        "action": "hold",
        "exchange_order_submitted": False,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def factory(tmp_path: Path) -> dict:
    f = json.loads(Path("config/zel_production_alpha_factory_v1.json").read_text())
    f = copy.deepcopy(f)
    f["families"]["carry_positioning"]["dynamic_event_study_path"] = str(tmp_path / "event.json")
    return f


def evidence(state: str, *, coverage_ready: bool, candidate: bool = False) -> dict:
    return {
        "schema_version": "zel.carry_positioning.event_study.v1",
        "family": "carry_positioning",
        "strategy_id": "carry_positioning_crowding_unwind_v1",
        "state": state,
        "coverage_ready": coverage_ready,
        "economic_candidate": candidate,
        "survivor_authority": False,
        "receipt_sha256": "b" * 64,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }


def write(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_pending_receipt_keeps_history_source_unbound(tmp_path: Path) -> None:
    f = factory(tmp_path)
    write(tmp_path / "event.json", evidence("HOLD_CARRY_POSITIONING_HISTORY_COVERAGE_PENDING", coverage_ready=False))
    enriched = enrich_factory_dynamic_state(f)
    r = route_tick(policy(), factory=enriched, bootstrap=bootstrap(), now_ms=1)
    by = {x["family_id"]: x for x in r["blockers"]}
    assert r["state"] == "HOLD_EDGE_ACQUISITION_CATALOG_EXHAUSTED"
    assert by["carry_positioning"]["classification"] == "SOURCE_UNBOUND"
    assert by["carry_positioning"]["missing_source_fields"] == ["history_coverage_bound"]


def test_event_study_pass_stops_at_authority_binding(tmp_path: Path) -> None:
    f = factory(tmp_path)
    write(tmp_path / "event.json", evidence("PASS_CARRY_POSITIONING_EVENT_STUDY_CANDIDATE_AUTHORITY_BLOCKED", coverage_ready=True, candidate=True))
    enriched = enrich_factory_dynamic_state(f)
    r = route_tick(policy(), factory=enriched, bootstrap=bootstrap(), now_ms=2)
    assert r["state"] == "HOLD_EDGE_CANDIDATE_AUTHORITY_BINDING_REQUIRED"
    assert r["candidate"]["family_id"] == "carry_positioning"
    assert r["acquisition_queue"] == []
    assert r["next"] == "BIND_RISK_DD_RETENTION_AUTHORITY_BEFORE_BOOTSTRAP_CANDIDATE"
    assert r["selection_authority"] is False
    assert r["promotion_authority"] is False
    assert r["execution_authority"] == "NONE"
    assert r["order_authority"] == "BLOCKED"


def test_event_study_reject_terminalizes_family_and_continues_route(tmp_path: Path) -> None:
    f = factory(tmp_path)
    write(tmp_path / "event.json", evidence("REJECT_CARRY_POSITIONING_EVENT_STUDY_DURABILITY", coverage_ready=True))
    enriched = enrich_factory_dynamic_state(f)
    r = route_tick(policy(), factory=enriched, bootstrap=bootstrap(), now_ms=3)
    by = {x["family_id"]: x for x in r["blockers"]}
    assert by["carry_positioning"]["classification"] == "TERMINAL_REJECT"
    assert by["carry_flow"]["classification"] == "SOURCE_UNBOUND"
    assert by["carry_flow"]["missing_source_fields"] == ["flow_source_bound"]
    assert r["state"] == "HOLD_EDGE_ACQUISITION_CATALOG_EXHAUSTED"
    assert r["order_authority"] == "BLOCKED"
