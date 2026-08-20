#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import backend.research.architecture_factory.a1_strategy_architecture_factory_v1 as factory_v1
import backend.research.architecture_factory.a1_strategy_architecture_factory_v3 as factory_v3
from backend.research.architecture_factory.a1_strategy_architecture_factory_v2 import sha

BASE_EVIDENCE = Path("backend/research/architecture_factory/a1_free_evidence_sweep_v1.json")
YOUTUBE_EVIDENCE_DEFAULT = Path("backend/research/architecture_factory/a1_youtube_evidence_latest.json")


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _youtube_path() -> Path:
    raw = os.environ.get("A1_YOUTUBE_EVIDENCE_PATH", "").strip()
    return Path(raw) if raw else YOUTUBE_EVIDENCE_DEFAULT


def _terminal_only_targets(ledger: Mapping[str, Any], limit: int = 25) -> list[dict[str, Any]]:
    """Use all already-terminal GEN1 outcomes for GEN2 PREP; never unfinished outcomes."""
    rows = factory_v1.target_rows(ledger, limit=25)
    terminal = [dict(x) for x in rows if bool(x.get("terminal"))]
    return terminal[: max(0, int(limit))]


def merge_evidence(base: Mapping[str, Any], youtube: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    merged = dict(base)
    base_sources = [dict(x) for x in (base.get("sources") or []) if isinstance(x, Mapping)]
    yt_sources: list[dict[str, Any]] = []
    for raw in youtube.get("sources") or []:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        if not bool(row.get("view_snapshot_verified")):
            continue
        if not bool(row.get("accepted_for_hypothesis_only")):
            continue
        if int(row.get("view_count_snapshot") or 0) < 30_000:
            continue
        if not str(row.get("claim") or "").strip():
            continue
        yt_sources.append(row)

    seen: set[str] = set()
    sources: list[dict[str, Any]] = []
    for row in [*base_sources, *yt_sources]:
        source_id = str(row.get("id") or "").strip()
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        sources.append(row)
    merged["sources"] = sources

    coverage = dict(base.get("coverage") or {})
    coverage["verified_youtube"] = len(yt_sources)
    merged["coverage"] = coverage
    policy = dict(base.get("policy") or {})
    policy["youtube_verified_items_accepted"] = len(yt_sources)
    merged["policy"] = policy
    merged["youtube_sidecar_state"] = str(youtube.get("state") or "MISSING")

    summary = {
        "state": str(youtube.get("state") or "MISSING"),
        "accepted_count": len(yt_sources),
        "preferred_100k_count": sum(1 for x in yt_sources if int(x.get("view_count_snapshot") or 0) >= 100_000),
        "fallback_30k_count": sum(1 for x in yt_sources if 30_000 <= int(x.get("view_count_snapshot") or 0) < 100_000),
        "factory_blocking": False,
        "hypothesis_only": True,
        "source_ids": [str(x.get("id") or "") for x in yt_sources],
    }
    return merged, summary


def run(output: Path) -> dict[str, Any]:
    base = _read(BASE_EVIDENCE)
    youtube_path = _youtube_path()
    youtube = _read(youtube_path)
    merged, youtube_summary = merge_evidence(base, youtube)

    ledger = factory_v1.read_json(factory_v1.LEDGER)
    terminal_targets = _terminal_only_targets(ledger, limit=25)
    done_count = int(ledger.get("done_count") or 0)

    with tempfile.TemporaryDirectory(prefix="a1-factory-v4-evidence-") as td:
        merged_path = Path(td) / "merged_evidence.json"
        merged_path.write_text(json.dumps(merged, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        old_v1_evidence = factory_v1.EVIDENCE
        old_v3_evidence = factory_v3.EVIDENCE
        old_v1_targets = factory_v1.target_rows
        old_v3_targets = factory_v3.target_rows
        try:
            factory_v1.EVIDENCE = merged_path
            factory_v3.EVIDENCE = merged_path
            # All generators see the same complete terminal-only GEN1 distribution.
            factory_v1.target_rows = _terminal_only_targets
            factory_v3.target_rows = _terminal_only_targets
            inner_path = Path(td) / "v3.json"
            result = factory_v3.run(inner_path)
        finally:
            factory_v1.EVIDENCE = old_v1_evidence
            factory_v3.EVIDENCE = old_v3_evidence
            factory_v1.target_rows = old_v1_targets
            factory_v3.target_rows = old_v3_targets

    result = dict(result)
    result["schema_version"] = "zel.a1_strategy_architecture_factory.v4"
    result["youtube_evidence"] = youtube_summary
    result["external_evidence_count"] = len(merged.get("sources") or [])
    result["youtube_evidence_factory_blocking"] = False
    result["youtube_can_promote_candidate"] = False
    result["gen2_prep_failure_distribution"] = {
        "generation": int(ledger.get("generation") or 0),
        "done_count": done_count,
        "terminal_count_used": len(terminal_targets),
        "terminal_strategy_ids": [str(x.get("strategy_id")) for x in terminal_targets],
        "unfinished_outcomes_used": False,
        "all_terminal_outcomes_used": len(terminal_targets) == done_count,
        "purpose": "GEN2_PREP_ONLY",
    }
    result["prep_only"] = done_count < 25
    result["fresh_prospective_boundary_created"] = False
    result["heavy_gen2_launch_started"] = False
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    base = {
        "sources": [{"id": "F1", "claim": "base"}],
        "coverage": {"peer_reviewed": 1, "verified_youtube": 0},
        "policy": {"youtube_verified_items_accepted": 0},
    }
    youtube = {
        "state": "PASS_YOUTUBE_EVIDENCE_READY",
        "sources": [
            {"id": "YT:ok", "claim": "x", "view_snapshot_verified": True, "accepted_for_hypothesis_only": True, "view_count_snapshot": 120000},
            {"id": "YT:low", "claim": "x", "view_snapshot_verified": True, "accepted_for_hypothesis_only": True, "view_count_snapshot": 29999},
            {"id": "YT:bad", "claim": "x", "view_snapshot_verified": False, "accepted_for_hypothesis_only": True, "view_count_snapshot": 900000},
        ],
    }
    merged, summary = merge_evidence(base, youtube)
    assert [x["id"] for x in merged["sources"]] == ["F1", "YT:ok"]
    assert merged["coverage"]["verified_youtube"] == 1
    assert merged["policy"]["youtube_verified_items_accepted"] == 1
    assert summary["accepted_count"] == 1 and summary["factory_blocking"] is False
    fake = {
        "strategies": {
            "done": {"status": "A1_ECONOMIC_FAIL", "completed_trades": 3, "net_expectancy_bps": -1.0},
            "open": {"status": "UNTESTED", "completed_trades": 9, "net_expectancy_bps": 99.0},
        }
    }
    targets = _terminal_only_targets(fake, 25)
    assert [x["strategy_id"] for x in targets] == ["done"]
    print("PASS_A1_STRATEGY_ARCHITECTURE_FACTORY_V4_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_strategy_architecture_factory_v4.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output)
    print(json.dumps({
        "state": result["state"],
        "done_count": result.get("gemini", {}).get("done_count"),
        "terminal_count_used": result.get("gen2_prep_failure_distribution", {}).get("terminal_count_used"),
        "generated_after_dedup": result.get("generated_after_dedup"),
        "alpha_proof_ready_count": result.get("alpha_proof_ready_count"),
        "youtube_evidence": result.get("youtube_evidence"),
        "gemini_generator": result.get("gemini", {}).get("generator"),
        "top3": [{"id": x.get("candidate_id"), "provider": x.get("provider"), "family": x.get("architecture_family"), "score": x.get("score"), "evidence": x.get("evidence_ids")} for x in result.get("top3") or []],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
