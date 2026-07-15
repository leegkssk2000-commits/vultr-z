#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from canonical.zlice.outcome_join import read_formal_ledger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = read_formal_ledger(args.ledger)
    blockers = []
    if not result.outcomes:
        blockers.append("NO_OUTCOME_ROWS")
    if result.parse_errors:
        blockers.append("PARSE_ERROR")
    if result.rejected_rows:
        blockers.append("IDENTITY_GAP")
    if result.duplicate_close_event_ids:
        blockers.append("DUPLICATE_CLOSE_EVENT_ID")
    if result.duplicate_ledger_row_ids:
        blockers.append("DUPLICATE_LEDGER_ROW_ID")
    total = len(result.outcomes)
    lineage = sum(row.lineage_complete for row in result.outcomes)
    realized = sum(row.realized_r is not None for row in result.outcomes)
    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "q4r3_r11_outcome_join_v1",
        "official_stage": "R1.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "blockers": blockers,
        "row_count": total,
        "lineage_count": lineage,
        "realized_r_count": realized,
        "file_sha256": result.file_sha256,
        "runtime_binding": False,
        "next_route": "R1.2_ZICO_MINIMAL_FSM"
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": state, "rows": total, "blockers": len(blockers)}, sort_keys=True))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
