#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "zel.a1.common_source_semantic_guard.v1"
COMMON_READY = {"ohlcv", "volume"}
FORBIDDEN_COMMON_SEMANTICS = (
    "aggressive-side",
    "aggressive side",
    "aggressor",
    "taker buy",
    "taker sell",
    "buy volume",
    "sell volume",
    "signed volume",
    "volume delta",
    "delta volume",
    "cumulative volume delta",
    "cvd",
    "order flow",
    "trade flow",
    "order book",
    "orderbook",
    "bid/ask",
    "bid ask",
    "footprint",
)
TEXT_FIELDS = (
    "architecture_family",
    "changed_axis",
    "mechanism",
    "payer",
    "entry_event",
    "direction_rule",
    "regime_owner",
    "invalidation",
    "exit_logic",
    "time_stop_rationale",
    "turnover_cost_budget",
    "falsification",
    "why_distinct",
)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _semantic_blockers(candidate: Mapping[str, Any]) -> list[str]:
    required = {str(x).strip().lower() for x in (candidate.get("required_sources") or []) if str(x).strip()}
    if not required or not required <= COMMON_READY:
        return []
    text = " ".join(str(candidate.get(k) or "") for k in TEXT_FIELDS).lower()
    hits = sorted({term for term in FORBIDDEN_COMMON_SEMANTICS if term in text})
    return [f"COMMON_SOURCE_UNOBSERVABLE_SEMANTIC:{term}" for term in hits]


def apply(receipt: Mapping[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(dict(receipt)))
    ready_in = [dict(x) for x in (out.get("new_architecture_ready_queue") or []) if isinstance(x, Mapping)]
    ready: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    blockers_by_id: dict[str, list[str]] = {}

    for row in ready_in:
        blockers = _semantic_blockers(row)
        if blockers:
            row["mechanism_first_guard_pass"] = False
            row["source_preflight_state"] = "HOLD_SOURCE_SEMANTICS"
            row["source_preflight_blockers"] = sorted(set(list(row.get("source_preflight_blockers") or []) + blockers))
            row["common_source_semantic_guard_pass"] = False
            blockers_by_id[str(row.get("candidate_id") or "")] = blockers
            held.append(row)
        else:
            row["common_source_semantic_guard_pass"] = True
            ready.append(row)

    diagnostics = []
    for raw in out.get("candidate_guard_diagnostics") or []:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        cid = str(row.get("candidate_id") or "")
        blockers = blockers_by_id.get(cid)
        if blockers:
            row["guard_pass"] = False
            row["source_preflight_state"] = "HOLD_SOURCE_SEMANTICS"
            row["source_preflight_blockers"] = sorted(set(list(row.get("source_preflight_blockers") or []) + blockers))
            row["common_source_semantic_guard_pass"] = False
        elif row.get("source_preflight_state") == "READY_COMMON":
            row["common_source_semantic_guard_pass"] = True
        diagnostics.append(row)

    out["candidate_guard_diagnostics"] = diagnostics
    out["new_architecture_ready_queue"] = ready
    out["new_architecture_ready_count"] = len(ready)
    out["new_architecture_semantic_hold_queue"] = held
    out["new_architecture_semantic_hold_count"] = len(held)
    out["next_experiment_candidate"] = ready[0] if ready else None
    out["common_source_semantic_guard"] = {
        "schema_version": SCHEMA,
        "state": "PASS_COMMON_SOURCE_SEMANTIC_GUARD" if not held else "HOLD_UNOBSERVABLE_COMMON_SOURCE_SEMANTICS",
        "common_ready_sources": sorted(COMMON_READY),
        "forbidden_semantics": list(FORBIDDEN_COMMON_SEMANTICS),
        "blocked_candidate_ids": [str(x.get("candidate_id") or "") for x in held],
        "blocked_count": len(held),
        "thresholds_changed": False,
        "source_authority_relaxed": False,
    }
    out["state"] = (
        "PASS_MECHANISM_FIRST_NEW_ARCHITECTURE_READY"
        if ready
        else "HOLD_MECHANISM_FIRST_NO_SOURCE_READY_NEW_ARCHITECTURE"
    )
    out["receipt_sha256"] = _sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out


def run(inp: Path, out: Path) -> dict[str, Any]:
    guarded = apply(_read(inp))
    if guarded.get("selection_authority") is not False or guarded.get("promotion_authority") is not False:
        raise RuntimeError("AUTHORITY_BOUNDARY_VIOLATION")
    if guarded.get("execution_authority") != "NONE" or guarded.get("order_authority") != "BLOCKED" or guarded.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("EXECUTION_BOUNDARY_VIOLATION")
    if int(guarded.get("protected_mutations") or 0) != 0:
        raise RuntimeError("PROTECTED_MUTATION_VIOLATION")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(guarded, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return guarded


def self_test() -> int:
    base = {
        "state": "PASS_MECHANISM_FIRST_NEW_ARCHITECTURE_READY",
        "new_architecture_ready_queue": [
            {
                "candidate_id": "bad",
                "required_sources": ["ohlcv", "volume"],
                "entry_event": "aggressive-side volume surge at session overlap",
            },
            {
                "candidate_id": "good",
                "required_sources": ["ohlcv", "volume"],
                "entry_event": "completed-bar close breaks prior range while total volume expands",
            },
        ],
        "candidate_guard_diagnostics": [
            {"candidate_id": "bad", "source_preflight_state": "READY_COMMON", "guard_pass": True},
            {"candidate_id": "good", "source_preflight_state": "READY_COMMON", "guard_pass": True},
        ],
        "new_architecture_ready_count": 2,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    guarded = apply(base)
    assert guarded["new_architecture_ready_count"] == 1
    assert guarded["next_experiment_candidate"]["candidate_id"] == "good"
    assert guarded["new_architecture_semantic_hold_count"] == 1
    assert guarded["new_architecture_semantic_hold_queue"][0]["candidate_id"] == "bad"
    assert _semantic_blockers({"required_sources": ["funding", "basis"], "entry_event": "order flow"}) == []
    print("PASS_A1_COMMON_SOURCE_SEMANTIC_GUARD_V1_SELF_TEST")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.input is None or args.output is None:
        raise SystemExit("--input and --output are required")
    result = run(args.input, args.output)
    print(json.dumps({
        "state": result.get("state"),
        "ready": result.get("new_architecture_ready_count"),
        "semantic_hold": result.get("new_architecture_semantic_hold_count"),
        "next": (result.get("next_experiment_candidate") or {}).get("candidate_id"),
        "receipt": result.get("receipt_sha256"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
