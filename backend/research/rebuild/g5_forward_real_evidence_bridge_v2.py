#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.research.rebuild import g5_forward_real_evidence_bridge_v1 as base

ROOT = base.ROOT
POST_CUTOVER_PATH = ROOT / "backend/research/rebuild/g5_clean_runner_post_cutover_3bar_v1.json"


def durable_cutover_view(post: dict) -> dict:
    ready = (
        post.get("schema_version") == "zel.g5.clean_runner.post_cutover_3bar.v1"
        and post.get("state") == "POST_CUTOVER_3BAR_PASS"
        and post.get("cutover_executed") is True
        and post.get("post_cutover_3bar_pass") is True
        and post.get("production_ready") is True
        and int(post.get("duplicate") or 0) == 0
        and int(post.get("lookahead") or 0) == 0
        and post.get("source_parity") is True
        and post.get("child_parity") is True
    )
    return {
        "production_ready": ready,
        "clean_runner_authority": ready,
        "authority_source": "DURABLE_POST_CUTOVER_3BAR_RECEIPT",
        "source_receipt_sha256": post.get("receipt_sha256"),
    }


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
    view = durable_cutover_view(post)
    if args.self_test:
        if view["production_ready"] is not True:
            raise RuntimeError("DURABLE_POST_CUTOVER_AUTHORITY_NOT_READY")
        print("PASS_G5_FORWARD_REAL_BRIDGE_V2_DURABLE_CUTOVER_SELF_TEST")
        return 0

    effective = base.read_json(base.EFFECTIVE_PATH)
    stale = base.read_json(base.STALE_PATH)
    cost = base.read_json(base.COST_PATH)
    source_rows = base.read_jsonl(Path(args.source_state))
    bridge_rows = base.read_jsonl(Path(args.bridge_state))
    bridge_evidence = base.read_jsonl(Path(args.bridge_ledger))
    canonical_evidence = base.read_jsonl(Path(args.canonical_ledger))
    current = base.now_ms()

    bridge_rows, bridge_evidence, canonical_evidence, status = base.process(
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
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
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
    status["receipt_sha256"] = base.stable(status)
    base.write_json(out / "g5_forward_real_bridge_latest_v1.json", status)
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
