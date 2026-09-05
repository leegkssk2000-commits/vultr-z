"""Read-only remote-seal status; never generate hypotheses, replay, or trade."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from backend.research.alpha_proof import a1_alpha_proof_gate_v1 as alpha
from backend.research.architecture_factory import g5a_alpha_proof_preflight_v1 as preflight
from backend.research.rebuild import g5_forward_real_evidence_bridge_v1 as bridge

ROOT = Path(__file__).resolve().parents[3]
FACTORY = "backend/research/architecture_factory/g5a_alpha_factory_latest.json"
BUNDLE = "backend/research/architecture_factory/g5a_ma001_alpha_proof_bundle_v1.json"
LEDGER = "backend/research/prep/g5_economic_evidence_ledger_v1.jsonl"
BRIDGE_LEDGER = "backend/research/rebuild/g5_forward_real_evidence_ledger_v1.jsonl"
EFFECTIVE = "backend/research/rebuild/g5_clean_runner_contract_effective_v1.json"
ACTIVATION = "backend/research/rebuild/g5_forward_real_bridge_latest_v1.json"
POST3 = "backend/research/rebuild/g5_clean_runner_post_cutover_3bar_v1.json"


def read(path: str):
    return json.loads((ROOT / path).read_text())


def rows(path: str):
    return [json.loads(line) for line in (ROOT / path).read_text().splitlines() if line.strip()]


def build(source_master_sha: str) -> dict:
    bundle = read(BUNDLE)
    if bundle["bundle_sha256"] != alpha.sha({k: v for k, v in bundle.items() if k != "bundle_sha256"}):
        raise RuntimeError("BUNDLE_SHA_MISMATCH")
    factory = read(FACTORY)
    expected = preflight.build_partial_bundle(factory["next_experiment_candidate"])["candidate"]
    if bundle["candidate"] != expected:
        raise RuntimeError("BUNDLE_CURRENT_CANDIDATE_IDENTITY_MISMATCH")
    proof = alpha.evaluate_bundle(bundle)
    current = preflight.evaluate(factory)
    # Remote seal cannot create a new economic authorization, even from a fixture.
    if proof["p0_p6_passed"] or current["deterministic_replay_authorized"]:
        raise RuntimeError("REMOTE_SEAL_UNEXPECTED_ALPHA_PROMOTION")
    canonical, _ = bridge.merge_evidence(rows(LEDGER), [])
    forwarded, _ = bridge.merge_evidence(rows(BRIDGE_LEDGER), [])
    production = [r for r in canonical if r.get("production_grade") is True]
    forwarded_hashes = {r["evidence_row_sha256"] for r in forwarded}
    if any(r["economic_origin"] != "FORWARD_REAL" or r["evidence_row_sha256"] not in forwarded_hashes for r in production):
        raise RuntimeError("PRODUCTION_BRIDGE_LEDGER_PARITY_FAIL")
    effective = read(EFFECTIVE)
    activation = read(ACTIVATION)
    lanes = []
    for lane in effective["active_strategies"]:
        eligible = [r for r in production if r.get("child_id") == lane["child_id"] and r.get("strategy_id") == lane["strategy_id"]]
        # Reuse the bridge's production qualification and future-only boundary.
        for row in eligible:
            trade = row.get("trade") or {}
            if int(trade.get("signal_ts") or 0) <= int(activation["activation_ts_ms"]):
                raise RuntimeError("PREBOUNDARY_PRODUCTION_CREDIT")
        lanes.append({"lane": lane["strategy_id"], "current_child": lane["child_id"],
                      "config_sha": lane["config_sha"], "fresh_T": len(eligible)})
    inputs = [FACTORY, BUNDLE, LEDGER, BRIDGE_LEDGER, EFFECTIVE, ACTIVATION, POST3,
              "backend/research/contracts/g5a_g5b_lane_local_profit_roadmap_v1.json",
              "backend/research/prep/g5_production_economic_contract_v1.json"]
    result = {
        "schema_version": "zel.g5a_g5b.profit_remote_seal_status.v1",
        "source_master_sha": source_master_sha,
        "source_revision_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_files_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in inputs},
        "source_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "candidate_id": expected["candidate_id"], "candidate_sha256": expected["candidate_sha256"],
        "bundle_sha256": bundle["bundle_sha256"], "alpha_proof_receipt": proof,
        "P0_P6": {g["gate"]: "PASS" if g["passed"] else "HOLD" for g in proof["gates"] if g["gate"] != "P-IDENTITY"},
        "MA001_state": "SOURCE_BLOCKED" if current["current_source_semantic_blockers"] else "HOLD",
        "source_semantic_blockers": current["current_source_semantic_blockers"],
        "generation_complete": False, "G5B_operational_complete": False, "G5B_economic_terminal": False,
        "canonical_ledger_rows": len(canonical), "production_grade_ledger_rows": len(production),
        "bridge_evidence_rows": len(forwarded), "G5B_lanes": lanes,
        "G5B_fresh_T": sum(l["fresh_T"] for l in lanes), "MA001_fresh_T": 0,
        "duplicate_guard": "PASS", "receipt_parity": "PASS", "source_identity_parity": "PASS",
        "clean_runner_post3": read(POST3),
        "deterministic_replay_authorized": False, "G5B_entry_authorized": False,
        "G5B_fresh_boundary_created": False, "paid_AI_calls_for_this_remote_seal": 0,
        "selection_authority": False, "promotion_authority": False, "execution_authority": "NONE",
        "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED", "exchange_order_submitted": False,
        "action": "hold", "G5A_decision": "G5A_SOURCE_BLOCKED", "G5B_decision": "NO_NEW_BOUNDARY_NO_FORMAL_PASS",
        "scope": "REMOTE_SEAL_ONLY_NOT_ECONOMIC_REPLAY_OR_PROMOTION",
    }
    result["receipt_sha256"] = alpha.sha(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-master-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.source_master_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("MA001_state", "production_grade_ledger_rows", "G5B_fresh_T", "receipt_sha256")}))


if __name__ == "__main__":
    main()
