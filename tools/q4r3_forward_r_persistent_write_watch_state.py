from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

CONTINUE_VERDICTS = {
    "NO_AUTHORITATIVE_OPEN_WRITE_EVENT_OBSERVED",
}
EVIDENCE_VERDICTS = {
    "RUNTIME_ENTRY_WRITER_OWNER_CONFIRMED",
    "RUNTIME_ENTRY_WRITER_OWNER_PROVISIONAL",
    "RUNTIME_ENTRY_WRITER_DISTRIBUTED",
    "AUTHORITATIVE_WRITE_EVENT_SEEN_OWNER_UNRESOLVED",
}
BLOCKED_VERDICTS = {
    "RUNTIME_WRITE_TRACE_BACKEND_UNAVAILABLE",
}


def classify_decision(payload: Dict[str, Any]) -> str:
    verdict = str(payload.get("verdict") or "").strip()
    if verdict in CONTINUE_VERDICTS:
        return "CONTINUE"
    if verdict in EVIDENCE_VERDICTS:
        return "EVIDENCE"
    if verdict in BLOCKED_VERDICTS:
        return "BLOCKED"
    return "UNKNOWN"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("decision", type=Path)
    args = parser.parse_args()

    if not args.decision.exists() or args.decision.stat().st_size <= 0:
        print(json.dumps({"classification": "MISSING", "verdict": None}))
        return

    payload = json.loads(args.decision.read_text(errors="ignore"))
    print(
        json.dumps(
            {
                "classification": classify_decision(payload),
                "verdict": payload.get("verdict"),
                "observed_event_count": payload.get("observed_event_count"),
                "observed_target_count": payload.get("observed_target_count"),
                "owner_counts": payload.get("owner_counts"),
                "target_owners": payload.get("target_owners"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
