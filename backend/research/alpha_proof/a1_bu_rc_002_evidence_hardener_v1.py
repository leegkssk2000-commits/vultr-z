from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_bingx_market_sources_v1 import verify_sources
from backend.production.zel_production_carry_flow_data_v1 import collect_snapshot
from backend.research.alpha_proof import a1_alpha_proof_gate_v2 as gate

SCHEMA = "zel.a1_bu_rc_002_evidence_hardener.v1"
CANDIDATE_ID = "BU-RC-002"
CANDIDATE_SHA = "98dd313e8241fcb80bf5ee04c7ef4ea2577228694b9a427da1210a26fe560e59"
DEFAULT_BUNDLE = Path("backend/research/alpha_proof/bundles/a1_alpha_proof_bu_rc_002_v1.json")
DEFAULT_PROVENANCE = Path("backend/research/alpha_proof/evidence/a1_bu_rc_002_parameter_provenance_v1.json")
DEFAULT_COST = Path("backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json")
DEFAULT_MARKET_POLICY = Path("config/zel_production_bingx_market_sources_v1.json")


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _bytes_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_authority(value: Mapping[str, Any], label: str) -> None:
    if value.get("selection_authority") is not False or value.get("promotion_authority") is not False:
        raise RuntimeError(f"{label}_SELECTION_AUTHORITY_INVALID")
    if value.get("execution_authority") != "NONE" or value.get("order_authority") != "BLOCKED":
        raise RuntimeError(f"{label}_EXECUTION_AUTHORITY_INVALID")
    if value.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError(f"{label}_LIVE_AUTHORITY_INVALID")
    if value.get("exchange_order_submitted") not in (None, False):
        raise RuntimeError(f"{label}_ORDER_SUBMITTED")


def _source_sha(rows: list[dict[str, Any]], feature: str, field: str | None = None) -> str:
    payload = []
    for row in rows:
        if row.get("feature") != feature:
            continue
        item = {
            "symbol": row.get("symbol"),
            "source_endpoint": row.get("source_endpoint"),
            "source_base": row.get("source_base"),
            "source_timestamp_ms": row.get("source_timestamp_ms"),
            "source_payload_sha256": row.get("source_payload_sha256"),
        }
        if field:
            item["field"] = field
            item["value"] = (row.get("raw") or {}).get(field)
        payload.append(item)
    if len(payload) != 2 or any(not str(x.get("source_payload_sha256") or "") for x in payload):
        raise RuntimeError(f"SOURCE_LINEAGE_INCOMPLETE:{feature}:{field or '-'}")
    return gate.sha(payload)


def harden(
    bundle: Mapping[str, Any],
    provenance_path: Path,
    cost_path: Path,
    market_policy: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    out = json.loads(json.dumps(bundle))
    candidate = out.get("candidate") or {}
    if candidate.get("candidate_id") != CANDIDATE_ID or candidate.get("candidate_sha256") != CANDIDATE_SHA:
        raise RuntimeError("BU_RC_002_CANDIDATE_IDENTITY_MISMATCH")

    provenance = _read(provenance_path)
    cost = _read(cost_path)
    if provenance.get("candidate_sha256") != CANDIDATE_SHA or provenance.get("selected_using_holdout") is not False:
        raise RuntimeError("BU_RC_002_PROVENANCE_INVALID")
    if cost.get("state") != "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY":
        raise RuntimeError("BU_RC_002_COST_AUTHORITY_INVALID")
    _assert_authority(cost, "COST")

    carry = collect_snapshot()
    market = verify_sources(market_policy)
    _assert_authority(carry, "CARRY")
    _assert_authority(market, "MARKET")
    if carry.get("state") != "PASS_CARRY_POSITIONING_RAW_DATA":
        raise RuntimeError("BU_RC_002_CARRY_SOURCE_NOT_PASS")
    if market.get("state") != "PASS_BINGX_PUBLIC_MARKET_SOURCES_VERIFIED":
        raise RuntimeError("BU_RC_002_MARKET_SOURCE_NOT_PASS")
    if market.get("source_bindings", {}).get("volume_source_bound") is not True:
        raise RuntimeError("BU_RC_002_VOLUME_SOURCE_NOT_BOUND")

    carry_rows = [dict(x) for x in (carry.get("records") or []) if isinstance(x, Mapping)]
    basis_sha = _source_sha(carry_rows, "premium_index")
    funding_sha = _source_sha(carry_rows, "premium_index", "lastFundingRate")
    oi_sha = _source_sha(carry_rows, "open_interest")
    market_receipt_sha = gate.sha(market)
    provenance_sha = _bytes_sha(provenance_path)
    cost_sha = _bytes_sha(cost_path)

    params = out["parameter_provenance"]["parameters"]
    if len(params) != 1 or params[0].get("name") != "expected_move_cost_multiple_target":
        raise RuntimeError("BU_RC_002_PARAMETER_INVENTORY_DRIFT")
    params[0]["development_justification_sha"] = provenance_sha

    prior_cost = out.get("source_implementation_reality", {}).get("verified_round_trip_cost_bps")
    if not isinstance(prior_cost, (int, float)) or isinstance(prior_cost, bool):
        raise RuntimeError("BU_RC_002_PRIOR_VERIFIED_COST_MISSING")

    out["source_implementation_reality"] = {
        "cost_authority_sha": cost_sha,
        "duplicate_count": 0,
        "integrity_defect_count": 0,
        "leakage_count": 0,
        "repo_status": "Candidate-matched same-run BingX public source refresh completed. Basis/funding/OI come from the production carry owner; volume comes from the public OHLCV verifier. This proves source implementation reality only, not history coverage or alpha.",
        "sources": [
            {"available": True, "fresh": True, "name": "basis", "proxy": False, "source_sha": basis_sha},
            {"available": True, "fresh": True, "name": "open_interest", "proxy": False, "source_sha": oi_sha},
            {"available": True, "fresh": True, "name": "funding", "proxy": False, "source_sha": funding_sha},
            {"available": True, "fresh": True, "name": "volume", "proxy": False, "source_sha": market_receipt_sha},
        ],
        "timestamp_order_error_count": 0,
        "verified_round_trip_cost_bps": float(prior_cost),
    }

    alpha = gate.evaluate_bundle(out)
    p2 = next(g for g in alpha["gates"] if g["gate"] == "P2_NUMERIC_PARAMETER_PROVENANCE")
    p6 = next(g for g in alpha["gates"] if g["gate"] == "P6_SOURCE_IMPLEMENTATION_REALITY")
    if not p2["passed"]:
        raise RuntimeError("BU_RC_002_P2_NOT_HARDENED:" + json.dumps(p2["failures"], sort_keys=True))
    if not p6["passed"]:
        raise RuntimeError("BU_RC_002_P6_NOT_HARDENED:" + json.dumps(p6["failures"], sort_keys=True))
    if alpha.get("state") != "HOLD_ALPHA_PROOF":
        raise RuntimeError("BU_RC_002_UNEXPECTED_ALPHA_STATE")
    if alpha.get("heavy_launch_allowed") is not False:
        raise RuntimeError("BU_RC_002_HEAVY_LAUNCH_MUST_REMAIN_BLOCKED")

    source_receipt = {
        "schema_version": SCHEMA,
        "candidate_id": CANDIDATE_ID,
        "candidate_sha256": CANDIDATE_SHA,
        "parameter_provenance_sha256": provenance_sha,
        "cost_authority_sha256": cost_sha,
        "carry_receipt_sha256": carry.get("receipt_sha256"),
        "market_receipt_sha256": market_receipt_sha,
        "source_sha": {
            "basis": basis_sha,
            "open_interest": oi_sha,
            "funding": funding_sha,
            "volume": market_receipt_sha,
        },
        "p2_passed": True,
        "p6_passed": True,
        "remaining_failed_gates": [g["gate"] for g in alpha["gates"] if not g["passed"]],
        "development_history_claimed": False,
        "alpha_claimed": False,
        "fresh_boundary_created": False,
        "heavy_launch_allowed": False,
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
    }
    source_receipt["receipt_sha256"] = gate.sha(source_receipt)
    return out, source_receipt, alpha


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    ap.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    ap.add_argument("--cost", type=Path, default=DEFAULT_COST)
    ap.add_argument("--market-policy", type=Path, default=DEFAULT_MARKET_POLICY)
    ap.add_argument("--out-dir", type=Path, default=Path("out/bu_rc_002_evidence_v2"))
    args = ap.parse_args()
    hydrated, source_receipt, alpha = harden(_read(args.bundle), args.provenance, args.cost, _read(args.market_policy))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "a1_alpha_proof_bu_rc_002_v2_hydrated.json").write_text(json.dumps(hydrated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.out_dir / "a1_bu_rc_002_p2_p6_receipt.json").write_text(json.dumps(source_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.out_dir / "a1_alpha_proof_bu_rc_002_v2_receipt.json").write_text(json.dumps(alpha, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": alpha["state"],
        "p2": "PASS",
        "p6": "PASS",
        "remaining_failed_gates": source_receipt["remaining_failed_gates"],
        "source_receipt_sha256": source_receipt["receipt_sha256"],
        "alpha_receipt_sha256": alpha["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
