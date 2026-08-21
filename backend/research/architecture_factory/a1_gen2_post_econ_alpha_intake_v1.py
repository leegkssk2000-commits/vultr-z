#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.alpha_proof.a1_alpha_proof_gate_v2 import (
    CANDIDATE_IDENTITY_FIELDS,
    identity_payload,
    sha,
)

SCHEMA_VERSION = "zel.a1_gen2_post_econ_alpha_intake.v1"
AUTHORITY = {
    "research_only": True,
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
}

def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("OBJECT_REQUIRED")
    return value

def _candidate_index(swarm: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for key in ("global_queue", "causal_repairs"):
        for row in swarm.get(key) or []:
            if isinstance(row, Mapping) and row.get("candidate_id"):
                out[str(row["candidate_id"])] = row
    return out

def _pass_rows(swarm: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for key in ("development_economics", "causal_repair_development_economics"):
        block = swarm.get(key) or {}
        if isinstance(block, Mapping):
            for row in block.get("passes") or []:
                if isinstance(row, Mapping):
                    rows.append(row)
    return rows

def _intake_row(candidate: Mapping[str, Any], dev: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    payload: dict[str, Any] = {}
    candidate_sha = ""
    try:
        payload = identity_payload(candidate)
        candidate_sha = sha(payload)
    except Exception as exc:
        blockers.append(f"IDENTITY_INCOMPLETE:{type(exc).__name__}:{str(exc)[:200]}")

    metrics = dev.get("metrics")
    if not isinstance(metrics, Mapping):
        blockers.append("DEVELOPMENT_METRICS_MISSING")
        metrics = {}

    state = str(dev.get("state") or "")
    if state != "PASS_DEVELOPMENT_ECONOMICS":
        blockers.append(f"DEVELOPMENT_NOT_PASS:{state or 'MISSING'}")

    if candidate.get("development_economic_pass") is not True:
        blockers.append("CANDIDATE_PASS_FLAG_MISSING")

    return {
        "candidate_id": candidate.get("candidate_id"),
        "strategy_id": candidate.get("strategy_id"),
        "mode": candidate.get("mode"),
        "provider": candidate.get("provider"),
        "architecture_family": candidate.get("architecture_family"),
        "candidate_identity_sha256": candidate_sha or None,
        "candidate_identity_payload": payload or None,
        "development_state": state,
        "development_boundary": dev.get("boundary"),
        "development_metrics": dict(metrics),
        "development_only": dev.get("development_only") is True,
        "uses_data_strictly_before_gen1_boundary": dev.get("uses_data_strictly_before_gen1_boundary") is True,
        "alpha_proof_bundle_state": "REQUIRED_NOT_BUILT",
        "alpha_proof_gate_state": "REQUIRED_NOT_RUN",
        "required_alpha_proof_gates": [
            "P0_PRIMARY_EVIDENCE",
            "P1_FEATURE_CAUSAL_MAP",
            "P2_NUMERIC_PARAMETER_PROVENANCE",
            "P3_EMPIRICAL_MOVE_VS_COST",
            "P4_NEGATIVE_CONTROLS_ABLATION",
            "P5_MULTI_AI_ADVERSARIAL_REVIEW",
            "P6_SOURCE_IMPLEMENTATION_REALITY",
        ],
        "intake_ready": not blockers,
        "next_action": "BUILD_ALPHA_PROOF_BUNDLE" if not blockers else "HOLD_INTAKE_INCOMPLETE",
        "blockers": blockers,
        **AUTHORITY,
    }

def build(swarm: Mapping[str, Any]) -> dict[str, Any]:
    done = int(swarm.get("ledger_done_count") or 0)
    prep_only = swarm.get("prep_only")
    failures: list[str] = []
    if done != 25:
        failures.append(f"EXACT25_NOT_COMPLETE:{done}")
    if prep_only is not False:
        failures.append(f"POST25_MODE_NOT_ACTIVE:{prep_only}")

    candidates = _candidate_index(swarm)
    passes = _pass_rows(swarm)
    rows: list[dict[str, Any]] = []
    missing_candidates: list[str] = []

    for dev in passes:
        cid = str(dev.get("candidate_id") or "")
        candidate = candidates.get(cid)
        if not candidate:
            missing_candidates.append(cid or "<missing>")
            continue
        rows.append(_intake_row(candidate, dev))

    if missing_candidates:
        failures.append("PASS_CANDIDATE_NOT_FOUND:" + ",".join(sorted(set(missing_candidates))))

    ready = [x for x in rows if x["intake_ready"]]
    result = {
        "schema_version": SCHEMA_VERSION,
        "state": (
            "PASS_POST25_ALPHA_INTAKE_READY"
            if not failures and ready
            else "HOLD_POST25_ALPHA_INTAKE"
        ),
        "ledger_done_count": done,
        "prep_only": prep_only,
        "development_pass_count": len(passes),
        "intake_count": len(rows),
        "intake_ready_count": len(ready),
        "top_ready_candidate_ids": [str(x["candidate_id"]) for x in ready[:3]],
        "rows": rows,
        "failures": failures,
        "note": (
            "Intake only. This receipt does not assert Alpha-Proof PASS and does not create "
            "selection, promotion, execution, order, or live authority."
        ),
        **AUTHORITY,
    }
    result["receipt_sha256"] = sha(result)
    return result

def self_test() -> int:
    core = {
        "candidate_id": "c1",
        "provider": "openai",
        "mode": "NEW_ARCHITECTURE",
        "strategy_id": "NEW",
        "architecture_family": "fixture",
        "changed_axis": "x",
        "mechanism": "m",
        "payer": "p",
        "entry_event": "e",
        "direction_rule": "both",
        "native_horizon": "1d",
        "regime_owner": "r",
        "invalidation": "i",
        "exit_logic": "x",
        "time_stop_rationale": "t",
        "turnover_cost_budget": "b",
        "required_sources": ["ohlcv"],
        "evidence_ids": ["F1", "F2"],
        "expected_move_cost_multiple_target": 2.0,
        "falsification": "f",
        "forbidden_changes": ["fees"],
        "why_distinct": "d",
        "development_economic_pass": True,
    }
    swarm = {
        "ledger_done_count": 25,
        "prep_only": False,
        "global_queue": [core],
        "causal_repairs": [],
        "development_economics": {
            "passes": [{
                "candidate_id": "c1",
                "state": "PASS_DEVELOPMENT_ECONOMICS",
                "development_only": True,
                "uses_data_strictly_before_gen1_boundary": True,
                "boundary": "2026-08-16T18:45:01Z",
                "metrics": {"trades": 100, "profit_factor": 1.2, "net_expectancy_bps": 10.0},
            }]
        },
        "causal_repair_development_economics": {"passes": []},
    }
    r = build(swarm)
    assert r["state"] == "PASS_POST25_ALPHA_INTAKE_READY", r
    assert r["intake_ready_count"] == 1
    assert r["selection_authority"] is False
    assert set(CANDIDATE_IDENTITY_FIELDS).issubset(r["rows"][0]["candidate_identity_payload"])
    print("PASS_A1_GEN2_POST_ECON_ALPHA_INTAKE_V1_SELF_TEST")
    return 0

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--swarm", type=Path)
    ap.add_argument("--output", type=Path, default=Path("out/a1_gen2_post_econ_alpha_intake_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.swarm:
        raise SystemExit("--swarm required")
    result = build(_read(args.swarm))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "done": result["ledger_done_count"],
        "development_pass_count": result["development_pass_count"],
        "intake_ready_count": result["intake_ready_count"],
        "top_ready_candidate_ids": result["top_ready_candidate_ids"],
        "failures": result["failures"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0 if result["state"] == "PASS_POST25_ALPHA_INTAKE_READY" else 2

if __name__ == "__main__":
    raise SystemExit(main())
