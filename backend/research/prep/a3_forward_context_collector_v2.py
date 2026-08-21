from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.research.prep import a3_forward_context_collector_v1 as v1

ROOT = Path(__file__).resolve().parents[3]
TAXONOMY = ROOT / "backend/research/prep/a3_regime_taxonomy_v1.json"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def evaluate(prior: dict[str, Any]) -> dict[str, Any]:
    result = v1.evaluate(prior)
    taxonomy = read(TAXONOMY)
    stale_after_ms = int((taxonomy.get("input_contract") or {}).get("stale_after_ms") or 0)
    if stale_after_ms <= 0:
        raise RuntimeError("A3_STALE_AFTER_MS_NOT_SEALED")
    result["schema_version"] = "zel.a3.forward_context.v2"
    result["taxonomy_sha256"] = v1.stable_sha(taxonomy)
    result["causal_contract"] = {
        "candidate_timestamp_semantics": {
            "signal_ts": "OPEN_TIMESTAMP_OF_THE_CLOSED_SIGNAL_BAR",
            "entry_ts": "NEXT_BAR_OPEN_AND_FIRST_EXECUTION_DECISION_TIME",
        },
        "snapshot_match_rule": "same symbol; capture_completed_at_ms <= candidate.entry_ts; choose latest eligible capture",
        "bar_feature_rule": "bar_feature_cutoff_ts_ms <= candidate.entry_ts",
        "maximum_snapshot_age_ms": stale_after_ms,
        "maximum_snapshot_age_source": "backend/research/prep/a3_regime_taxonomy_v1.json.input_contract.stale_after_ms",
        "legacy_rows_without_actual_capture_timestamp_are_ineligible": True,
        "current_snapshot_backfill_to_historical_trade_forbidden": True,
        "future_snapshot_attachment_forbidden": True,
        "outcome_defined_matching_forbidden": True,
    }
    # V1 rows may contain an older descriptive contract. The actual timestamps
    # remain valid; V2 is the authoritative interpretation for matching them.
    for row in result.get("new_rows") or []:
        if isinstance(row, dict):
            row["causal_match_contract_version"] = "A3_FORWARD_CONTEXT_V2"
            row["maximum_snapshot_age_ms"] = stale_after_ms
    result["receipt_sha256"] = v1.stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    return result


def self_test() -> int:
    taxonomy = read(TAXONOMY)
    assert int((taxonomy.get("input_contract") or {}).get("stale_after_ms") or 0) == 7_200_000
    print("PASS_A3_FORWARD_CONTEXT_COLLECTOR_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prior", type=Path)
    ap.add_argument("--output", type=Path, default=Path("out/a3_forward_context_v2.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    prior: dict[str, Any] = {}
    if args.prior and args.prior.exists():
        prior = read(args.prior)
    result = evaluate(prior)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "row_count": result["row_count"],
        "valid_row_count": result["valid_row_count"],
        "current_valid_count": result["current_valid_count"],
        "legacy_causal_ineligible_count": result.get("legacy_causal_ineligible_count", 0),
        "stale_after_ms": result["causal_contract"]["maximum_snapshot_age_ms"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
