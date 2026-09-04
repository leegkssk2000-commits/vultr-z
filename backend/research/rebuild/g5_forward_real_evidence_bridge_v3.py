#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.rebuild import g5_forward_real_evidence_bridge_v1 as base
from backend.research.rebuild import g5_forward_real_evidence_bridge_v2 as v2

ROOT = base.ROOT
POST_CUTOVER_PATH = v2.POST_CUTOVER_PATH


def retry_safe_open_index(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Index bridge positions without permanently killing a signal on transient entry capture failure.

    The v1 append-only log used OPEN_REJECTED for every entry capture exception.  A network/API
    failure is not a deterministic strategy rejection and must not consume the only future signal.
    We preserve the old append-only event but classify ENTRY_PROVENANCE_CAPTURE_FAILED rows as
    retryable when building the current index.  Permanent contract/identity rejections remain terminal.
    """
    opens: dict[str, dict[str, Any]] = {}
    terminal: set[str] = set()
    for row in rows:
        kind = str(row.get("kind") or "")
        payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
        tid = str(payload.get("trade_id") or "")
        if not tid:
            continue
        if kind == "OPENED_PROVENANCE":
            opens[tid] = dict(payload)
            continue
        if kind in {"CLOSED_PRODUCTION", "CLOSED_FAIL_CLOSED"}:
            terminal.add(tid)
            continue
        if kind == "OPEN_REJECTED":
            reason = str(payload.get("reason") or "")
            if reason.startswith("ENTRY_PROVENANCE_CAPTURE_FAILED:"):
                continue
            terminal.add(tid)
    return {tid: row for tid, row in opens.items() if tid not in terminal}, terminal


def run_process(**kwargs: Any):
    original = base.open_index
    base.open_index = retry_safe_open_index
    try:
        return base.process(**kwargs)
    finally:
        base.open_index = original


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--source-state", default=str(base.STATE_PATH))
    parser.add_argument("--bridge-state", default=str(base.BRIDGE_STATE_PATH))
    parser.add_argument("--bridge-ledger", default=str(base.BRIDGE_LEDGER_PATH))
    parser.add_argument("--canonical-ledger", default=str(base.CANONICAL_LEDGER_PATH))
    parser.add_argument("--out-dir", default="out")
    args = parser.parse_args()

    contract = base.read_json(base.CONTRACT_PATH)
    base.validate_contract(contract)
    post = base.read_json(POST_CUTOVER_PATH)
    view = v2.durable_cutover_view(post)
    if args.self_test:
        if view["production_ready"] is not True:
            raise RuntimeError("DURABLE_POST_CUTOVER_AUTHORITY_NOT_READY")
        probe = [
            {
                "kind": "OPEN_REJECTED",
                "payload": {"trade_id": "retry", "reason": "ENTRY_PROVENANCE_CAPTURE_FAILED:RuntimeError:timeout"},
            },
            {
                "kind": "OPEN_REJECTED",
                "payload": {"trade_id": "terminal", "reason": "SIGNAL_CHILD_NOT_CURRENT_EFFECTIVE_OWNER"},
            },
        ]
        _, terminal = retry_safe_open_index(probe)
        if "retry" in terminal or "terminal" not in terminal:
            raise RuntimeError("RETRY_SAFE_INDEX_SELF_TEST_FAIL")
        print("PASS_G5_FORWARD_REAL_BRIDGE_V3_RETRY_SAFE_SELF_TEST")
        return 0

    effective = base.read_json(base.EFFECTIVE_PATH)
    stale = base.read_json(base.STALE_PATH)
    cost = base.read_json(base.COST_PATH)
    source_rows = base.read_jsonl(Path(args.source_state))
    bridge_rows = base.read_jsonl(Path(args.bridge_state))
    bridge_evidence = base.read_jsonl(Path(args.bridge_ledger))
    canonical_evidence = base.read_jsonl(Path(args.canonical_ledger))
    current = base.now_ms()

    bridge_rows, bridge_evidence, canonical_evidence, status = run_process(
        source_rows=source_rows,
        bridge_rows=bridge_rows,
        bridge_evidence=bridge_evidence,
        canonical_evidence=canonical_evidence,
        effective=effective,
        cutover=view,
        stale=stale,
        cost=cost,
        provider=base.PublicBingXProvider(),
        current_ms=current,
        fee_authority_sha=base.git_blob_sha(base.COST_PATH),
    )
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base.write_jsonl(out / "g5_forward_real_bridge_state_v1.jsonl", bridge_rows)
    base.write_jsonl(out / "g5_forward_real_evidence_ledger_v1.jsonl", bridge_evidence)
    base.write_jsonl(out / "g5_economic_evidence_ledger_v1.jsonl", canonical_evidence)
    status["generated_at_ms"] = current
    status["generated_at_utc"] = base.iso_ms(current)
    status["contract_blob_sha"] = base.git_blob_sha(base.CONTRACT_PATH)
    status["effective_contract_blob_sha"] = base.git_blob_sha(base.EFFECTIVE_PATH)
    status["cost_authority_blob_sha"] = base.git_blob_sha(base.COST_PATH)
    status["post_cutover_authority_blob_sha"] = base.git_blob_sha(POST_CUTOVER_PATH)
    status["post_cutover_authority_ready"] = view["production_ready"]
    status["post_cutover_source_receipt_sha256"] = view["source_receipt_sha256"]
    status["entry_capture_retry_safe"] = True
    status["receipt_sha256"] = base.stable(status)
    base.write_json(out / "g5_forward_real_bridge_latest_v1.json", status)
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
