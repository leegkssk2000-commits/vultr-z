"""Read retained source metadata only; never calculate a signal, fill or PnL."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
HERE = Path(__file__).resolve().parent
READINESS = (
    ROOT
    / "research/campaigns/scalp7_20260920/model_closure_v1/audits/DATA_AUTHORITY_READINESS.json"
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    prior = json.loads(READINESS.read_bytes())
    witnesses = []
    for witness in prior["canonical_history"]["raw_schema_samples"]:
        path = Path(witness["path"])
        actual = sha(path)
        if actual != witness["file_sha256"]:
            raise ValueError("RETAINED_SOURCE_METADATA_SAMPLE_CHANGED")
        payload = json.loads(path.read_bytes())
        rows = payload["data"]
        if not rows or any(not isinstance(row, dict) for row in rows):
            raise ValueError("SAVED_OBJECT_SCHEMA_REQUIRED")
        fields = sorted(set().union(*(row.keys() for row in rows)))
        witnesses.append(
            {
                "path": str(path),
                "sha256": actual,
                "rows_schema_inspected_only": len(rows),
                "row_fields": fields,
                "source_volume_field": "volume" if "volume" in fields else None,
                "quote_volume_field_present": any(
                    "quote" in key.lower() and "vol" in key.lower() for key in fields
                ),
                "unit_authority_in_row_fields": any(
                    key in fields
                    for key in ("volumeUnit", "volume_unit", "unit", "contractSize")
                ),
                "matches_retained_readiness_schema": fields == witness["row_keys"],
            }
        )
    receipt = {
        "schema": "g4.measurement_exact25.volume_source_contract.v1",
        "scope_key": "G4_MEASUREMENT_REPAIR_AND_EXACT25_CLOSURE_AFTER_PR1345_V1",
        "method": "Retained payload hash and object field schema inspection only",
        "prior_readiness": {
            "path": str(READINESS.relative_to(ROOT)),
            "sha256": sha(READINESS),
        },
        "source_schema_witnesses": witnesses,
        "actual_canonical_volume_unit": "UNKNOWN",
        "actual_canonical_quote_volume": "ABSENT",
        "delivery_clock": "BAR_CLOSE_MODEL_NOT_OBSERVED_HISTORICAL_DELIVERY",
        "historical_object_volume_unit_repaired": False,
        "actual_schema_unit_authority_pending": True,
        "price_times_unknown_volume_quote_synthesis": False,
        "freshness": False,
        "strategy_history_rows_evaluated": 0,
        "new_full_runs": 0,
        "synthetic_test_contract": {
            "test_file": "tests/test_scalp7_volume_contract_v1.py",
            "execution_evidence_path": "synthetic_tests.txt",
            "scope": "Artificial source fields, dimensions, causal clocks and existing components",
        },
    }
    for row in witnesses:
        if (
            not row["matches_retained_readiness_schema"]
            or row["quote_volume_field_present"]
            or row["unit_authority_in_row_fields"]
        ):
            raise ValueError("VOLUME_PENDING_CONCLUSION_NEEDS_REVIEW")
    (HERE / "SOURCE_CONTRACT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                "saved": str(HERE / "SOURCE_CONTRACT.json"),
                "retained_witnesses": len(witnesses),
                "new_full_runs": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
