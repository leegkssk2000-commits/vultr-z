from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0 and new in text:
        return text
    if count != 1:
        raise RuntimeError(f"{label}_MATCH_COUNT_{count}")
    return text.replace(old, new, 1)


def main() -> None:
    audit_path = Path("backend/tools/zel_grid_neutral_source_lineage_audit_v1.py")
    audit = audit_path.read_text(encoding="utf-8")
    audit = replace_once(
        audit,
        '''    strategy_sources = [row for row in source_matches if "strategy_source" in row["roles"]]
    registry_refs = [row for row in source_matches if "registry_or_manifest" in row["roles"]]
    replay_refs = [row for row in source_matches if "replay_or_simulation" in row["roles"] or "terminal_pipeline_reference" in row["roles"]]
    no_unsafe_regime_candidates = [row for row in regime_candidates if row["static_no_lookahead"]]
    trade_ledger = analyze_grid_trades(terminal_root / "trades.jsonl.gz")
''',
        '''    strategy_sources = [row for row in source_matches if "strategy_source" in row["roles"]]
    registry_refs = [row for row in source_matches if "registry_or_manifest" in row["roles"]]
    replay_refs = [row for row in source_matches if "replay_or_simulation" in row["roles"] or "terminal_pipeline_reference" in row["roles"]]
    no_unsafe_regime_candidates = [row for row in regime_candidates if row["static_no_lookahead"]]
    trade_ledger = analyze_grid_trades(terminal_root / "trades.jsonl.gz")

    canonical_relative_path = "backend/strategies/grid_rebalance.py"
    canonical_sources = [row for row in strategy_sources if row["path"] == canonical_relative_path]
    unique_strategy_source_shas = sorted({row["sha256"] for row in strategy_sources})
    mirror_sources = [row for row in strategy_sources if row["path"] != canonical_relative_path]
    canonical_sha = canonical_sources[0]["sha256"] if len(canonical_sources) == 1 else None
    all_mirrors_content_identical = bool(canonical_sha) and all(row["sha256"] == canonical_sha for row in mirror_sources)
    required_binding_paths = {
        "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json",
        "backend/strategy25/canonical_strategy_registry_v1.json",
    }
    canonical_binding_refs = [row for row in registry_refs if row["path"] in required_binding_paths]
    active_owner_unique = (
        len(canonical_sources) == 1
        and len(unique_strategy_source_shas) == 1
        and all_mirrors_content_identical
        and {row["path"] for row in canonical_binding_refs} == required_binding_paths
    )
''',
        "SOURCE_CLASSIFICATION",
    )
    audit = replace_once(
        audit,
        '''    blockers: list[str] = []
    if len(strategy_sources) != 1:
        blockers.append("GRID_STRATEGY_SOURCE_NOT_UNIQUE")
''',
        '''    blockers: list[str] = []
    if not active_owner_unique:
        blockers.append("GRID_ACTIVE_OWNER_LINEAGE_UNRESOLVED")
''',
        "SOURCE_BLOCKER",
    )
    audit = replace_once(
        audit,
        '''        "source_match_count": len(source_matches),
        "strategy_source_count": len(strategy_sources),
        "registry_reference_count": len(registry_refs),
''',
        '''        "source_match_count": len(source_matches),
        "strategy_source_count": len(strategy_sources),
        "canonical_strategy_source_count": len(canonical_sources),
        "unique_strategy_source_sha_count": len(unique_strategy_source_shas),
        "mirror_strategy_source_count": len(mirror_sources),
        "canonical_strategy_source_path": canonical_relative_path,
        "canonical_strategy_source_sha256": canonical_sha,
        "all_mirrors_content_identical": all_mirrors_content_identical,
        "canonical_binding_reference_count": len(canonical_binding_refs),
        "active_owner_unique": active_owner_unique,
        "registry_reference_count": len(registry_refs),
''',
        "RECEIPT_SOURCE_PROOF",
    )
    audit_path.write_text(audit, encoding="utf-8")

    review_path = Path("backend/tools/zel_grid_neutral_lineage_gemini_review_v1.py")
    review = review_path.read_text(encoding="utf-8")
    review = replace_once(
        review,
        '''        "counts": {
            "strategy_source": audit.get("strategy_source_count"),
            "registry_reference": audit.get("registry_reference_count"),
            "replay_reference": audit.get("replay_reference_count"),
            "regime_candidate": audit.get("regime_candidate_count"),
            "static_no_lookahead_regime_candidate": audit.get("static_no_lookahead_regime_candidate_count"),
        },
        "blockers": audit.get("blockers"),
''',
        '''        "counts": {
            "strategy_source_paths": audit.get("strategy_source_count"),
            "canonical_strategy_source": audit.get("canonical_strategy_source_count"),
            "unique_strategy_source_sha": audit.get("unique_strategy_source_sha_count"),
            "mirror_strategy_source": audit.get("mirror_strategy_source_count"),
            "canonical_binding_reference": audit.get("canonical_binding_reference_count"),
            "registry_reference": audit.get("registry_reference_count"),
            "replay_reference": audit.get("replay_reference_count"),
            "regime_candidate": audit.get("regime_candidate_count"),
            "static_no_lookahead_regime_candidate": audit.get("static_no_lookahead_regime_candidate_count"),
        },
        "source_identity": {
            "canonical_path": audit.get("canonical_strategy_source_path"),
            "canonical_sha256": audit.get("canonical_strategy_source_sha256"),
            "active_owner_unique": audit.get("active_owner_unique"),
            "all_mirrors_content_identical": audit.get("all_mirrors_content_identical"),
        },
        "blockers": audit.get("blockers"),
''',
        "GEMINI_SOURCE_PROFILE",
    )
    review_path.write_text(review, encoding="utf-8")


if __name__ == "__main__":
    main()
