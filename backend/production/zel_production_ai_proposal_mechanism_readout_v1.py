from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_improvement_controller_v1 import read_json

SCHEMA = "zel.production_ai_proposal_layer.v1"
DEFAULT_PATH = Path("/home/z/z/ledger/production_ai_edge_proposals_v1.json")


def sanitized_mechanisms(row: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, Mapping) or row.get("schema_version") != SCHEMA:
        return {"state": "HOLD_AI_PROPOSAL_MECHANISM_READOUT_MISSING", "proposals": []}
    proposals = []
    for raw in row.get("proposals") or []:
        if not isinstance(raw, Mapping):
            continue
        proposals.append(
            {
                "proposal_id": str(raw.get("proposal_id") or ""),
                "family_id": str(raw.get("family_id") or ""),
                "proposal_type": str(raw.get("proposal_type") or ""),
                "required_sources": sorted(map(str, raw.get("required_sources") or [])),
                "economic_mechanism": str(raw.get("economic_mechanism") or ""),
                "causal_reason": str(raw.get("causal_reason") or ""),
                "falsification_test": str(raw.get("falsification_test") or ""),
                "expected_horizon": str(raw.get("expected_horizon") or ""),
            }
        )
    return {
        "state": "PASS_AI_PROPOSAL_MECHANISM_READOUT",
        "proposal_count": len(proposals),
        "proposals": proposals,
        "proposal_receipt_sha256": row.get("receipt_sha256"),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }


def main() -> int:
    print(json.dumps(sanitized_mechanisms(read_json(DEFAULT_PATH)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
