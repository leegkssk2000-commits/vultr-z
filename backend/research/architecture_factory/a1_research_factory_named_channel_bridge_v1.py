#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_research_factory_v1 as factory

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_NAMED = ROOT / "backend/research/architecture_factory/a1_named_channel_gemini_latest.json"


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _named_sources(named: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in named.get("accepted_sources") or []:
        if not isinstance(raw, Mapping):
            continue
        if raw.get("accepted_for_hypothesis_only") is not True:
            continue
        if raw.get("channel_identity_verified_by_direct_analysis") is not True:
            continue
        mechanisms = [x for x in (raw.get("reproducible_mechanisms") or []) if isinstance(x, Mapping)]
        mapped: set[str] = set()
        mechanism_text: list[str] = []
        tags: set[str] = set()
        for mech in mechanisms:
            mechanism_text.extend([
                str(mech.get("mechanism") or ""),
                str(mech.get("market_and_timeframe_context") or ""),
                str(mech.get("entry_logic") or ""),
                str(mech.get("exit_logic") or ""),
                str(mech.get("risk_and_drawdown_control") or ""),
                str(mech.get("position_or_exposure_logic") or ""),
                " ".join(str(x) for x in (mech.get("regime_conditions") or [])),
                " ".join(str(x) for x in (mech.get("entry_time_features") or [])),
            ])
            tags.add(str(mech.get("architecture_layer") or ""))
            for m in mech.get("candidate_strategy_mappings") or []:
                if isinstance(m, Mapping) and m.get("strategy_id"):
                    mapped.add(str(m["strategy_id"]))
        claim = " ".join(
            x.strip()
            for x in [str(raw.get("concise_video_summary") or ""), *mechanism_text]
            if x and x.strip()
        )[:12000]
        if not claim or not mapped:
            continue
        out.append({
            "id": str(raw.get("id") or f"YTNAMED:{raw.get('video_id','')}"),
            "tier": "named_channel_direct_gemini_hypothesis",
            "source_type": "YouTube",
            "source_origin": "named_channel_gemini",
            "identifier": str(raw.get("url") or raw.get("video_id") or ""),
            "title": str(raw.get("title") or ""),
            "claim": claim,
            "mapped_strategy_ids": sorted(mapped),
            "extractable_axes": sorted(x for x in tags if x),
            "target_channel": raw.get("target_channel"),
            "actual_channel": raw.get("actual_channel"),
            "video_id": raw.get("video_id"),
            "accepted_for_hypothesis_only": True,
            "promotion_authority": False,
            "limitations": "Direct Gemini video analysis; hypothesis-only. Creator thresholds are not imported. Local causal replay and fresh/OOS proof remain mandatory.",
        })
    return out


def run(
    output: Path,
    *,
    named_path: Path = DEFAULT_NAMED,
    network: bool = False,
    ai: bool = True,
    ai_strategy_limit: int = factory.AI_STRATEGY_LIMIT,
) -> dict[str, Any]:
    named = _read(named_path)
    named_sources = _named_sources(named)
    original_normalize = factory.normalize_static_sources
    original_backlog = factory.build_axis_backlog

    def normalize_with_named(mapping: Mapping[str, Any], free: Mapping[str, Any], youtube: Mapping[str, Any]) -> list[dict[str, Any]]:
        base_sources = original_normalize(mapping, free, youtube)
        return factory.dedup_sources(base_sources + named_sources)

    def backlog_with_strategy_mapping(
        strategy_id: str,
        proposal: Mapping[str, Any],
        sources: list[dict[str, Any]],
        context: str,
    ) -> list[dict[str, Any]]:
        scoped: list[dict[str, Any]] = []
        for src in sources:
            mapped = [str(x) for x in (src.get("mapped_strategy_ids") or [])]
            if src.get("source_origin") == "named_channel_gemini" and mapped and strategy_id not in mapped:
                continue
            scoped.append(src)
        return original_backlog(strategy_id, proposal, scoped, context)

    try:
        factory.normalize_static_sources = normalize_with_named
        factory.build_axis_backlog = backlog_with_strategy_mapping
        result = factory.run(output, network=network, ai=ai, ai_strategy_limit=ai_strategy_limit)
    finally:
        factory.normalize_static_sources = original_normalize
        factory.build_axis_backlog = original_backlog

    mapped_ids = sorted({sid for src in named_sources for sid in (src.get("mapped_strategy_ids") or [])})
    result["named_channel_gemini_bridge"] = {
        "state": "PASS_NAMED_CHANNEL_HYPOTHESES_CONSUMED" if named_sources else "HOLD_NO_NAMED_CHANNEL_SOURCE_READY",
        "named_receipt_sha256": named.get("receipt_sha256"),
        "accepted_named_source_count": len(named_sources),
        "mapped_strategy_count": len(mapped_ids),
        "mapped_strategy_ids": mapped_ids,
        "consumer": "A1_RESEARCH_FACTORY_BACKLOG_AND_MULTI_AI_REVIEW",
        "creator_threshold_imported": False,
        "local_replay_required": True,
        "fresh_oos_required": True,
        "selection_authority": False,
        "promotion_authority": False,
    }
    result["receipt_sha256"] = factory.sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    fake = {
        "accepted_sources": [{
            "id": "YTNAMED:AAAAAAAAAAA",
            "video_id": "AAAAAAAAAAA",
            "url": "https://www.youtube.com/watch?v=AAAAAAAAAAA",
            "title": "mean reversion example",
            "target_channel": "T",
            "actual_channel": "T",
            "accepted_for_hypothesis_only": True,
            "channel_identity_verified_by_direct_analysis": True,
            "concise_video_summary": "mean reversion after volatility extension",
            "reproducible_mechanisms": [{
                "mechanism": "mean reversion after volatility extension",
                "architecture_layer": "entry",
                "candidate_strategy_mappings": [{"strategy_id": "vwap_revert"}],
            }],
        }]
    }
    rows = _named_sources(fake)
    assert len(rows) == 1, rows
    assert rows[0]["mapped_strategy_ids"] == ["vwap_revert"], rows
    assert rows[0]["promotion_authority"] is False
    print("PASS_A1_RESEARCH_FACTORY_NAMED_CHANNEL_BRIDGE_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_research_factory_named_channel_bridge_latest.json"))
    ap.add_argument("--named", type=Path, default=DEFAULT_NAMED)
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--ai-strategy-limit", type=int, default=factory.AI_STRATEGY_LIMIT)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(
        args.output,
        named_path=args.named,
        network=not args.no_network,
        ai=not args.no_ai,
        ai_strategy_limit=max(0, args.ai_strategy_limit),
    )
    print(json.dumps({
        "state": result.get("state"),
        "bridge": result.get("named_channel_gemini_bridge"),
        "queue": result.get("experiment_queue_count"),
        "next": result.get("next_experiment_candidate"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
