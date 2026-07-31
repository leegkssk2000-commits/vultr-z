from __future__ import annotations

import json
import tempfile
from pathlib import Path

from backend.contracts.zel_event_sourced_shadow_v1 import AppendOnlyShadowEventStore, deterministic_event_id
from backend.contracts.zel_strategy_lifecycle_v1 import validate_registry
from backend.research.zel_oms_state_machine_v1 import SqliteOmsStore
from backend.research.zel_promotion_gates_v1 import PromotionGateError, evaluate_completion, fixture_evidence
from backend.research.zel_strategy_lifecycle_registry_v1 import REGISTRY
from backend.tools.zel_pipeline_bottleneck_cleanup_audit_v1 import audit

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/zel_completion_foundation_v1"


def event(position_id: str, sequence: int, event_type: str, parent: str) -> dict:
    event_id = deterministic_event_id(position_id, sequence, event_type)
    return {
        "event_id": event_id,
        "parent_event_id": parent,
        "decision_id": "decision.fixture.001",
        "position_id": position_id,
        "strategy_id": "trend_ma_macd",
        "strategy_source_sha256": "04d98299bd3bd869c379585ba3aed364e2448e180cacaaf21277a4f88a63ec94",
        "method_id": "TF_EMA",
        "skill_set": [],
        "team_id": "ALPHA",
        "symbol": "BTCUSDT",
        "side": "LONG",
        "market_snapshot_sha256": "1" * 64,
        "risk_snapshot_sha256": "2" * 64,
        "sequence_no": sequence,
        "event_ts": f"2026-07-31T17:{sequence:02d}:00Z",
        "idempotency_key": f"fixture:{position_id}:{sequence}:{event_type}",
        "event_type": event_type,
        "payload": {"fixture_only": True},
        "source_ids": ["runtime:fixture"],
    }


def oms_command(target: str, sequence: int, filled: float, reduce_only: bool = False) -> dict:
    return {
        "order_intent_id": "oms.fixture.001",
        "client_order_id": "client.fixture.001",
        "decision_id": "decision.fixture.001",
        "position_id": "position.fixture.001",
        "strategy_id": "trend_ma_macd",
        "symbol": "BTCUSDT",
        "side": "LONG",
        "mode": "SIMULATION",
        "target_state": target,
        "quantity": 1.0,
        "filled_quantity": filled,
        "reduce_only": reduce_only,
        "risk_snapshot_sha256": "2" * 64,
        "event_ts": f"2026-07-31T18:{sequence:02d}:00Z",
        "idempotency_key": f"oms.fixture.001:{sequence}:{target}",
        "reason_codes": ["FIXTURE_ONLY"],
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    registry = validate_registry(REGISTRY)
    assert len(registry["entries"]) == 25
    assert sum(int(row["observer_allowed"]) for row in registry["entries"]) == 25
    assert sum(int(row["capital_allowed"]) for row in registry["entries"]) == 0

    store = AppendOnlyShadowEventStore()
    position_id = "shadow.fixture.001"
    parent = ""
    types = [
        "strategy_signal_emitted", "admission_decided", "shadow_open_requested",
        "shadow_open_confirmed", "shadow_managed", "shadow_close_requested",
        "shadow_closed", "formal_ledger_joined",
    ]
    for sequence, event_type in enumerate(types):
        result = store.append(event(position_id, sequence, event_type, parent))
        assert result.replayed is False
        parent = result.event["event_id"]
    coverage = store.validate()
    assert coverage["pass"] is True
    assert coverage["lineage_coverage_pct"] == 100.0

    with tempfile.TemporaryDirectory(prefix="zel_oms_fixture_") as directory:
        oms = SqliteOmsStore(Path(directory) / "oms.sqlite3")
        states = [
            ("INTENT_CREATED", 0.0, False), ("RISK_APPROVED", 0.0, False),
            ("SENT", 0.0, False), ("ACKNOWLEDGED", 0.0, False),
            ("PARTIALLY_FILLED", 0.4, False), ("FILLED", 1.0, False),
            ("CLOSE_SENT", 1.0, True), ("CLOSED", 1.0, True),
        ]
        final = {}
        for sequence, (target, filled, reduce_only) in enumerate(states):
            final = oms.apply(oms_command(target, sequence, filled, reduce_only))
        assert final["to_state"] == "CLOSED"
        assert oms.event_count("oms.fixture.001") == len(states)

    fixture_rejected = False
    try:
        evaluate_completion(fixture_evidence())
    except PromotionGateError as exc:
        fixture_rejected = str(exc) == "REAL_EVIDENCE_REQUIRED"
    assert fixture_rejected is True

    cleanup = audit(ROOT)
    result = {
        "state": "PASS_ZEL_COMPLETION_FOUNDATION_FIXTURE",
        "fixture_only": True,
        "strategy_count": 25,
        "observer_allowed_count": 25,
        "capital_allowed_count": 0,
        "event_lineage_coverage_pct": coverage["lineage_coverage_pct"],
        "oms_terminal_state": final["to_state"],
        "oms_event_count": len(states),
        "real_completion_fixture_rejected": fixture_rejected,
        "cleanup_baseline_state": cleanup["state"],
        "cleanup_finding_count": cleanup["finding_count"],
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "runtime_bound": False,
        "paper_allowed": False,
        "live_allowed": False,
    }
    (OUT / "fixture_result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "cleanup_baseline.json").write_text(json.dumps(cleanup, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
