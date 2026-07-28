from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping

from backend.tools import r7a4d_strategy11_data_wait_pool_compute_v1 as w1
from backend.tools import r7a4d_strategy11_ema_repair_v2 as ema2
from backend.tools import r7a4d_strategy11_turtle_primary_w1_causal_replay_v1 as shared

VERSION = "R7A4D_STRATEGY11_EMA_PRIMARY_W1_CAUSAL_REPLAY_V1"
CAPABILITY_MARKER = "PRIMARY_W1_CAUSAL_REPLAY"
STRATEGY_ID = "ema_ribbon_scalp"

shared.VERSION = VERSION
shared.STRATEGY_ID = STRATEGY_ID

p = ema2.p
exact = ema2.exact
base = ema2.base


def strict_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def composite_surgery(baseline: Mapping[str, Any]) -> tuple[Any, ...]:
    original = p.surgery_from(baseline.get("surgery"))
    atr_gate = p.EvidenceSurgery(
        surgery_id="BLOCK_atr_pct_GE_0.538805",
        feature="atr_pct",
        kind="numeric",
        value=ema2.ATR_PCT_BLOCK_THRESHOLD,
        block_when="GE",
    )
    return tuple(item for item in (original, atr_gate) if item is not None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--baseline-summary", required=True)
    parser.add_argument("--ema-authority-root", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    source_root = Path(args.source_root).resolve()
    baseline_path = Path(args.baseline_summary).resolve()
    authority_root = Path(args.ema_authority_root).resolve()
    policy_path = Path(args.policy).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    source = strict_json(source_root / "status.json")
    if source.get("state") == "WAIT_DATA":
        payload = shared.wait_payload(source, source_run_id=args.source_run_id, source_head_sha=args.source_head_sha)
        payload["capability_marker"] = CAPABILITY_MARKER
        payload["strategy_id"] = STRATEGY_ID
        shared.atomic_json(out / "status.json", payload)
        shared.atomic_json(out / "summary.json", payload)
        print(json.dumps({"state": payload["state"], "missing": payload["missing_bars"]}, sort_keys=True))
        return 0
    if source.get("state") != "PASS" or source.get("blockers"):
        raise RuntimeError(f"W1_SOURCE_NOT_PASS:{source.get('state')}:{source.get('blockers')}")

    manifest_path = source_root / "data" / "manifest.json"
    manifest = strict_json(manifest_path)
    manifest_sha = shared.sha256(manifest_path)
    if manifest_sha != source.get("W1_manifest_sha256"):
        raise RuntimeError("W1_MANIFEST_SHA_MISMATCH")
    if manifest.get("state") != "PASS" or manifest.get("blockers"):
        raise RuntimeError("W1_MANIFEST_NOT_PASS")
    if manifest.get("window_id") != "W1" or int(manifest.get("evaluation_bars") or 0) != 480 or int(manifest.get("warmup_bars") or 0) != 220:
        raise RuntimeError("W1_BOUNDARY_CONTRACT_FAIL")
    if len(manifest.get("files") or []) != 5:
        raise RuntimeError("W1_SYMBOL_FILE_COUNT_FAIL")

    baseline = strict_json(baseline_path)
    authority = strict_json(authority_root / "summary.json")
    policy = strict_json(policy_path)
    if baseline.get("state") != "PASS" or baseline.get("strategy_id") != STRATEGY_ID:
        raise RuntimeError("EMA_BASELINE_AUTHORITY_INVALID")
    if authority.get("strategy_id") != STRATEGY_ID or authority.get("sealed_holdback_read") is not False:
        raise RuntimeError("EMA_CAUSAL_AUTHORITY_INVALID")

    required_ids = list(policy["source_candidate_ids"])
    if required_ids != ["INCUMBENT_CONTROL", "BLOCK_HIGH_ATR_PCT"]:
        raise RuntimeError("EMA_POLICY_VARIANTS_INVALID")
    authority_rows = {str(row["variant_id"]): row for row in authority.get("variants", [])}
    if any(candidate_id not in authority_rows for candidate_id in required_ids):
        raise RuntimeError("EMA_CAUSAL_VARIANT_MISSING")
    for candidate_id in required_ids:
        if not (authority_root / candidate_id / "replay-A.json").exists():
            raise RuntimeError(f"EMA_PRIOR_LEDGER_MISSING:{candidate_id}")

    candidate = baseline["candidate"]
    gate = exact._gate_from(candidate)
    base_exit = exact._exit_from(candidate)
    original_surgery = p.surgery_from(baseline.get("surgery"))
    surgeries = {
        "INCUMBENT_CONTROL": original_surgery,
        "BLOCK_HIGH_ATR_PCT": composite_surgery(baseline),
    }
    symbols = tuple(str(value) for value in baseline.get("symbols", []))
    registry = base._load_registry(root)
    registry_row = registry[STRATEGY_ID]
    strategy_source_sha = str(registry_row["canonical_engine"]["source_sha256"])
    strategy = base._load_canonical_strategy(root, STRATEGY_ID, registry_row)
    frames, features, funding = w1.load_window(source_root, manifest)

    rows: list[dict[str, Any]] = []
    for variant_id in required_ids:
        print(f"EMA_PRIMARY_W1_START variant={variant_id}", flush=True)
        row = shared.evaluate_w1_variant(
            variant_id=variant_id,
            exit_spec=base_exit,
            surgery=surgeries[variant_id],
            strategy=strategy,
            gate=gate,
            symbols=symbols,
            frames=frames,
            features=features,
            funding=funding,
            manifest=manifest,
            strategy_source_sha=strategy_source_sha,
            source_run_id=args.source_run_id,
            source_head_sha=args.source_head_sha,
            cap_r=float(policy["w1_gate"]["normal_worst_net_loss_R_min"]),
            authority_root=authority_root,
            out=out,
        )
        rows.append(row)
        print(f"EMA_PRIMARY_W1_END variant={variant_id}", flush=True)

    incumbent = rows[0]
    candidate_row = rows[1]
    gate_result = shared.confirmation_gate(candidate_row, incumbent, authority_rows["BLOCK_HIGH_ATR_PCT"], policy)
    candidate_row["W1_confirmation_gate"] = gate_result
    shared.atomic_json(out / "BLOCK_HIGH_ATR_PCT" / "summary.json", candidate_row)

    minimum = int(policy["w1_gate"]["minimum_w1_trades"])
    low_sample = int(incumbent["W1"].get("trade_count") or 0) < minimum
    active = ["BLOCK_HIGH_ATR_PCT"] if gate_result["pass"] else []
    state = "PASS_W1_PRIMARY_CAUSAL_REPLAY" if active else ("W1_LOW_SAMPLE_HOLD" if low_sample else "W1_REJECT_RETAIN_INCUMBENT")
    final = {
        "schema_version": "1.0",
        "version": VERSION,
        "capability_marker": CAPABILITY_MARKER,
        "state": state,
        "blockers": [],
        "strategy_id": STRATEGY_ID,
        "source_w1_run_id": args.source_run_id,
        "source_w1_head_sha": args.source_head_sha,
        "source_w1_manifest_sha256": manifest_sha,
        "source_ema_authority_run_id": "30282056363",
        "source_ema_authority_head_sha": "7416ced237c674474ebdaccf67b9a771723daee0",
        "baseline_summary_sha256": shared.sha256(baseline_path),
        "ema_authority_summary_sha256": shared.sha256(authority_root / "summary.json"),
        "policy_sha256": shared.sha256(policy_path),
        "active_candidate_queue": active,
        "variants": rows,
        "requires_new_sealed_holdback": bool(active),
        "sealed_holdback_read": False,
        "existing_sealed_reused": False,
        "promotion_authority": False,
        "next": "W1_NEW_SEALED_HOLDBACK_GENERATOR" if active else "EMA_RETAIN_INCUMBENT_OR_GEMINI_W1_DELTA",
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "execution_authority": "NONE",
        "paper_allowed": False,
        "live_allowed": False,
        "order_authority": "BLOCKED",
    }
    shared.atomic_json(out / "status.json", final)
    shared.atomic_json(out / "summary.json", final)
    print(json.dumps({"state": state, "active": active, "next": final["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
