from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MAP = ROOT / "backend/research/architecture_factory/a1_external_research_exact25_map_v1.json"
DEFAULT_LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
DEFAULT_INVENTORY = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
PRIMARY_TIERS = {"peer_reviewed", "primary_preprint", "working_paper"}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def metric_subset(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "completed_trades", "gross_expectancy_bps", "net_expectancy_bps", "net_pnl_bps",
        "profit_factor", "payoff", "win_rate", "drawdown_bps", "verified_pretrade_cost_bps",
    )
    return {key: row.get(key) for key in keys if key in row}


def build(mapping: Mapping[str, Any], ledger: Mapping[str, Any], inventory: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    strategy_order = list(ledger.get("strategy_order") or [])
    ledger_rows = ledger.get("strategies") or {}
    inventory_rows = inventory.get("strategies") or {}
    proposals = mapping.get("strategies") or {}
    sources = mapping.get("sources") or {}
    if len(strategy_order) != 25 or len(set(strategy_order)) != 25:
        raise RuntimeError("EXACT25_LEDGER_REQUIRED")
    if set(strategy_order) != set(proposals):
        missing = sorted(set(strategy_order) - set(proposals))
        extra = sorted(set(proposals) - set(strategy_order))
        raise RuntimeError(f"EXACT25_RESEARCH_MAP_MISMATCH:missing={missing}:extra={extra}")
    packets: list[dict[str, Any]] = []
    for strategy_id in strategy_order:
        proposal = dict(proposals[strategy_id])
        axis = str(proposal.get("axis") or "").strip()
        source_ids = [str(x) for x in (proposal.get("source_ids") or [])]
        if not axis or not source_ids or any(source_id not in sources for source_id in source_ids):
            raise RuntimeError(f"PROPOSAL_LINEAGE_INVALID:{strategy_id}")
        primary_ids = [source_id for source_id in source_ids if str(sources[source_id].get("tier")) in PRIMARY_TIERS]
        if not primary_ids:
            raise RuntimeError(f"PRIMARY_EVIDENCE_REQUIRED:{strategy_id}")
        if any(str(sources[source_id].get("tier")) == "youtube_hypothesis_only" for source_id in source_ids) and len(primary_ids) == 0:
            raise RuntimeError(f"YOUTUBE_CANNOT_DRIVE_AXIS:{strategy_id}")
        baseline = dict(ledger_rows.get(strategy_id) or {})
        inv = dict(inventory_rows.get(strategy_id) or {})
        packet = {
            "schema_version": "zel.a1_external_research_exact25_prep.v1",
            "state": "EARLY_AI_PREP_READY",
            "strategy_id": strategy_id,
            "classification": "OUTCOME_BLIND_EXTERNAL_EVIDENCE_ONE_AXIS_PREREG",
            "baseline_mutated": False,
            "baseline_observation_sha": baseline.get("receipt_sha") or baseline.get("evidence_sha"),
            "policy_owner": inv.get("policy_owner"),
            "evidence_packet": inv.get("evidence_packet"),
            "metrics": metric_subset(baseline),
            "fingerprint": {"primary": str(baseline.get("status") or "UNKNOWN_BASELINE_STATE"), "secondary": [str(baseline.get("terminal_reason") or "")] if baseline.get("terminal_reason") else []},
            "external_sources": [{"id": source_id, **dict(sources[source_id])} for source_id in source_ids],
            "top3_axes": [{
                "rank": 1,
                "axis": axis,
                "mechanism": str(proposal.get("mechanism") or ""),
                "source_ids": source_ids,
                "expected_metric_direction": dict(proposal.get("expected_metric_direction") or {}),
                "falsification": "Reject the new identity if frozen development economics fail, fixed-first25 hard causal controls fail, or any required source lacks timestamp-safe lineage.",
                "required_data": list(proposal.get("required_data") or []),
                "forbidden_collateral_changes": ["fees", "slippage", "stop", "target", "timeout", "position_size", "holdout_tuning", "additional_entry_filter"],
            }],
            "one_changed_axis": True,
            "source_lineage_complete": True,
            "primary_evidence_ids": primary_ids,
            "youtube_hypothesis_only": any(str(sources[source_id].get("tier")) == "youtube_hypothesis_only" for source_id in source_ids),
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "protected_mutations": 0,
            "action": "hold",
        }
        packet["packet_sha256"] = digest(packet)
        packets.append(packet)
    receipt = {
        "schema_version": "zel.a1_external_research_exact25_router.v1",
        "state": "PASS_EXACT25_EXTERNAL_RESEARCH_PREREG_READY",
        "strategy_count": len(packets),
        "strategy_ids": [row["strategy_id"] for row in packets],
        "axis_count": len({row["top3_axes"][0]["axis"] for row in packets}),
        "primary_source_count": sum(1 for row in sources.values() if str(row.get("tier")) in PRIMARY_TIERS),
        "youtube_source_count": sum(1 for row in sources.values() if str(row.get("tier")) == "youtube_hypothesis_only"),
        "one_changed_axis_all": all(row["one_changed_axis"] is True for row in packets),
        "lineage_complete_all": all(row["source_lineage_complete"] is True for row in packets),
        "holdout_outcomes_accessed": False,
        "canonical_strategy_files_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "action": "hold",
    }
    receipt["receipt_sha256"] = digest(receipt)
    return receipt, packets


def self_test() -> int:
    mapping = {"sources": {"P": {"tier": "peer_reviewed"}}, "strategies": {f"s{i}": {"axis": f"A{i}", "mechanism": "m", "source_ids": ["P"], "required_data": ["ohlcv"]} for i in range(25)}}
    order = [f"s{i}" for i in range(25)]
    ledger = {"strategy_order": order, "strategies": {sid: {"status": "TEST", "completed_trades": 1} for sid in order}}
    inventory = {"strategies": {sid: {"policy_owner": "x.py", "evidence_packet": "x.json"} for sid in order}}
    receipt, packets = build(mapping, ledger, inventory)
    assert receipt["state"] == "PASS_EXACT25_EXTERNAL_RESEARCH_PREREG_READY"
    assert receipt["strategy_count"] == 25 and len(packets) == 25
    assert all(len(row["top3_axes"]) == 1 for row in packets)
    print("PASS_A1_EXTERNAL_RESEARCH_EXACT25_ROUTER_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", type=Path, default=DEFAULT_MAP)
    ap.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    ap.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    ap.add_argument("--output-dir", type=Path, default=Path("out/exact25_external_research_prep"))
    ap.add_argument("--receipt", type=Path, default=Path("out/a1_external_research_exact25_router_v1.json"))
    ap.add_argument("--shard-count", type=int, default=1)
    ap.add_argument("--shard-index", type=int, default=0)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    receipt, packets = build(read(args.map), read(args.ledger), read(args.inventory))
    if args.shard_count <= 0 or not 0 <= args.shard_index < args.shard_count:
        raise SystemExit("INVALID_SHARD")
    selected = [row for idx, row in enumerate(packets) if idx % args.shard_count == args.shard_index]
    receipt["shard_count"] = args.shard_count
    receipt["shard_index"] = args.shard_index
    receipt["shard_strategy_count"] = len(selected)
    receipt["shard_strategy_ids"] = [row["strategy_id"] for row in selected]
    receipt["receipt_sha256"] = digest({key: value for key, value in receipt.items() if key != "receipt_sha256"})
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for old in args.output_dir.glob("*.json"):
        old.unlink()
    for row in selected:
        (args.output_dir / f"{row['strategy_id']}.json").write_text(json.dumps(row, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": receipt["state"], "strategy_count": receipt["strategy_count"], "shard_strategy_count": receipt["shard_strategy_count"], "axis_count": receipt["axis_count"], "receipt_sha256": receipt["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
