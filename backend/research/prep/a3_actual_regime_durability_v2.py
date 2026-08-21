from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
TAXONOMY = ROOT / "backend/research/prep/a3_regime_taxonomy_v1.json"
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
REQUIRED = ["trend_strength", "realized_vol_pct", "spread_bps", "depth_usdt", "funding_8h_pct", "oi_change_pct"]
AUTH = {"selection_authority":False,"promotion_authority":False,"execution_authority":"NONE","order_authority":"BLOCKED","live_trade_authority":"BLOCKED","protected_mutations":0,"action":"hold"}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def evaluate(a2: Mapping[str, Any], hardening: Mapping[str, Any]) -> dict[str, Any]:
    if a2.get("state") != "PASS_A2_COST_TURNOVER":
        raise RuntimeError("A2_PASS_REQUIRED")
    candidate_id = str(a2.get("candidate_id") or "")
    if not candidate_id or hardening.get("strategy_id") != candidate_id:
        raise RuntimeError("A2_A3_CANDIDATE_IDENTITY_MISMATCH")
    ledger, taxonomy = read(LEDGER), read(TAXONOMY)
    row = (ledger.get("strategies") or {}).get(candidate_id)
    if not isinstance(row, Mapping):
        raise RuntimeError("A1_LINEAGE_MISSING")
    if hardening.get("policy_sha") != row.get("policy_sha") or hardening.get("config_sha") != row.get("config_sha"):
        raise RuntimeError("A3_HARDENING_LINEAGE_MISMATCH")
    if hardening.get("boundary_utc") != row.get("prospective_boundary_utc"):
        raise RuntimeError("A3_BOUNDARY_LINEAGE_MISMATCH")

    # Historical exact25 screening did not capture all sealed A3 entry-time context.
    # This remains a prospective-only gate for every candidate; no current snapshot
    # may be backfilled onto an older trade.
    h5 = hardening.get("h5_receipt") if isinstance(hardening.get("h5_receipt"), Mapping) else {}
    available = ["symbol", "signal_ts", "entry_ts", "side", "gross_expectancy_bps", "net_expectancy_bps"]
    result = {
        "schema_version": "zel.a3.actual_regime_durability.v2", "stage": "A3", "candidate_id": candidate_id,
        "state": "HOLD_A3_ENTRY_CONTEXT_INCOMPLETE", "a2_receipt_sha256": a2.get("receipt_sha256"),
        "a1_policy_sha": row.get("policy_sha"), "a1_config_sha": row.get("config_sha"),
        "taxonomy_sha256": hashlib.sha256(json.dumps(taxonomy, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "taxonomy_required_inputs": list((taxonomy.get("input_contract") or {}).get("required") or []),
        "available_historical_trade_fields": available, "missing_entry_time_fields": list(REQUIRED),
        "outcome_defined_regime": False, "historical_backfill_from_current_snapshot_forbidden": True,
        "existing_h5_diagnostics": {
            "state": h5.get("state"), "dimensions": h5.get("dimensions"),
            "maximum_profit_share_by_dimension": h5.get("maximum_profit_share_by_dimension"),
            "failed_leave_one_group_out": h5.get("failed_leave_one_group_out"),
        },
        "entry_time_regime_owner": None, "owned_regime_net_positive": None,
        "fail_closed_outside_owned_regime": True, "global_durability_pass": False,
        "next_required_action": "FORWARD_A3_ENTRY_CONTEXT_CAPTURE",
        "note": "A3 entered candidate-agnostically. Existing H5 is diagnostic only; sealed A3 context must be captured prospectively at/preceding each signal without future data.",
        **AUTH,
    }
    result["receipt_sha256"] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return result


def self_test() -> int:
    tax = read(TAXONOMY)
    required = set((tax.get("input_contract") or {}).get("required") or [])
    assert set(REQUIRED).issubset(required), (REQUIRED, sorted(required))
    print("PASS_A3_ACTUAL_REGIME_DURABILITY_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a2", type=Path)
    ap.add_argument("--hardening", type=Path)
    ap.add_argument("--output", type=Path, default=Path("out/a3_actual_regime_durability_v2.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.a2 or not args.hardening:
        raise SystemExit("--a2 and --hardening required")
    result = evaluate(read(args.a2), read(args.hardening))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state":result["state"],"candidate_id":result["candidate_id"],"missing":result["missing_entry_time_fields"],"next":result["next_required_action"],"receipt_sha256":result["receipt_sha256"]},sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
