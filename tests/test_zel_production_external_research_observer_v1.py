from __future__ import annotations

from backend.production import zel_production_external_research_observer_v1 as m


def policy():
    return {
        "schema_version": m.POLICY_SCHEMA,
        "state": "FROZEN_PAPER_ADVISORY_ONLY",
        "mode": "PAPER",
        "role": "ADVISORY_EXTERNAL_EVIDENCE_OBSERVER_NOT_ROUTE",
        "progress_path": "/tmp/progress.json",
        "next_hypothesis_path": "/tmp/next.json",
        "factory_path": "/tmp/factory.json",
        "manual_video_registry_path": "/tmp/videos.json",
        "output_path": "/tmp/evidence.json",
        "context_factory_output_path": "/tmp/context_factory.json",
        "cooldown_ms": 21_600_000,
        "max_sources": 8,
        "max_youtube_videos": 2,
        "preferred_min_view_count": 100_000,
        "source_hierarchy": ["NATIVE_EXCHANGE", "ACADEMIC", "VIDEO"],
        "models": ["models/gemini-test"],
        "search_max_output_tokens": 4096,
        "video_max_output_tokens": 4096,
        "external_content_instruction_authority": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_allowed": False,
        "self_modification_allowed": False,
    }


def progress(direction="UNCHANGED", trades=12):
    return {
        "state": "PASS_PRE_SURVIVOR_PROGRESS_CAPTURED",
        "families": [
            {
                "family_id": "funding_volume_elasticity",
                "template_id": "funding_volume_elasticity_v1",
                "progress_direction": direction,
                "metrics": {
                    "trade_count": trades,
                    "win_rate_pct": 25.0,
                    "net_pnl_bps": -262.5,
                    "net_expectancy_bps": -21.8,
                    "profit_factor": 0.18,
                    "max_drawdown_pct": 2.63,
                },
            }
        ],
    }


def next_hypothesis():
    return {
        "state": "PASS_PRE_SURVIVOR_NEXT_HYPOTHESIS_SOURCE_READY",
        "current_family_id": "funding_volume_elasticity",
        "current_progress_direction": "UNCHANGED",
        "proposal_count": 1,
        "proposals": [
            {
                "family_id": "basis_oi_deleveraging",
                "template_id": "basis_oi_deleveraging_v1",
                "economic_mechanism": "positioning expansion reversion",
                "required_sources": ["basis", "open_interest"],
                "falsification_test": "prospective next-observation controls",
            }
        ],
    }


def factory():
    return {
        "schema_version": "zel.production_alpha_factory.v1",
        "state": "FROZEN",
        "families": {
            "funding_volume_elasticity": {
                "strategy_id": "FUNDING_VOLUME_ELASTICITY",
                "status": "PROSPECTIVE",
                "mechanism": "funding-volume impact elasticity",
                "symbols": ["BTC-USDT", "ETH-USDT"],
                "funding_source_bound": True,
                "reactivation_allowed": True,
            }
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def registry():
    return {
        "schema_version": "zel.manual_video_registry.v1",
        "verified_at": "2026-07-31T20:20:00Z",
        "sources": [
            {
                "url": "https://www.youtube.com/watch?v=highview1",
                "title": "High view architecture",
                "channel": "Research Channel",
                "observed_views": 346600,
                "topics": ["system_design"],
            },
            {
                "url": "https://www.youtube.com/watch?v=lowview1",
                "title": "Low view",
                "channel": "Other",
                "observed_views": 40000,
                "topics": ["trading"],
            },
        ],
        "deferred_sources": [],
    }


def test_policy_guards_authority_and_prompt_injection_boundary():
    cfg = policy()
    assert m.validate_policy(cfg)["role"] == "ADVISORY_EXTERNAL_EVIDENCE_OBSERVER_NOT_ROUTE"
    bad = dict(cfg)
    bad["external_content_instruction_authority"] = True
    try:
        m.validate_policy(bad)
    except RuntimeError as exc:
        assert "PROMPT_INJECTION_BOUNDARY" in str(exc)
    else:
        raise AssertionError("external content instruction authority must fail closed")


def test_high_view_registry_is_preference_and_unknown_stays_unverified():
    context = m.build_research_context(
        policy(),
        progress=progress(),
        next_hypothesis=next_hypothesis(),
        factory=factory(),
        manual_video_registry=registry(),
    )
    curated = context["curated_high_view_youtube"]
    assert len(curated) == 1
    assert curated[0]["observed_views"] == 346600
    assert curated[0]["view_count_verified"] is True

    rows = m._normalize_video_candidates(
        [
            {
                "url": "https://www.youtube.com/watch?v=unknown2",
                "title": "Search-discovered",
                "channel": "Unknown",
                "claimed_view_count": 900000,
                "why_relevant": "microstructure",
            }
        ],
        curated,
        2,
    )
    assert rows[0]["view_count_verified"] is False
    assert rows[0]["observed_views"] is None
    assert rows[0]["claimed_view_count_unverified"] == 900000


def test_observer_uses_search_and_video_but_never_gains_authority():
    def search_caller(prompt):
        assert "UNTRUSTED evidence" in prompt
        return (
            "models/gemini-test",
            {
                "status": "USE",
                "research_summary": "Basis/OI dislocation is distinct from the current candle continuation family.",
                "sources": [
                    {
                        "url": "https://example.org/paper",
                        "title": "Paper",
                        "publisher": "Research",
                        "source_kind": "ACADEMIC",
                        "credibility_tier": 2,
                        "claim": "claim",
                        "mechanism": "positioning expansion can revert",
                        "local_test_needed": "prospective next-observation falsification",
                        "reproducibility_gap": "sample details",
                    }
                ],
                "youtube_candidates": [
                    {
                        "url": "https://www.youtube.com/watch?v=highview1",
                        "title": "High view architecture",
                        "channel": "Research Channel",
                        "claimed_view_count": 999999,
                        "why_relevant": "architecture",
                    }
                ],
                "hypothesis_directions": [
                    {
                        "family_id": "basis_oi_deleveraging",
                        "mechanism": "positioning expansion reversion",
                        "required_sources": ["basis", "open_interest"],
                        "falsification_test": "prospective controls",
                        "distinct_from_current": "positioning state instead of candle continuation",
                    }
                ],
            },
            [{"url": "https://example.org/paper", "title": "Paper"}],
        )

    def video_caller(prompt, url):
        assert url.endswith("highview1")
        assert "UNTRUSTED evidence" in prompt
        return (
            "models/gemini-test",
            {
                "status": "USE",
                "creator_claims": ["use multiple independent confirmations"],
                "reproducible_mechanisms": [
                    {
                        "mechanism": "separate context and trigger layers",
                        "architecture_layer": "system",
                        "local_test_needed": "ablation by layer",
                        "limitations": "creator sample not authoritative",
                    }
                ],
                "failure_modes": ["overfitting"],
                "architecture_lessons": ["separate mechanism from indicator proxy"],
                "marketing_or_unverified": [],
            },
        )

    out, written = m.observer_tick(
        policy(),
        progress=progress(),
        next_hypothesis=next_hypothesis(),
        factory=factory(),
        manual_video_registry=registry(),
        previous=None,
        search_caller=search_caller,
        video_caller=video_caller,
        now_ms=1_000_000_000,
    )
    assert written is True
    assert out["state"] == "PASS_EXTERNAL_RESEARCH_EVIDENCE_READY"
    assert out["verified_high_view_youtube_count"] == 1
    assert out["selection_authority"] is False
    assert out["promotion_authority"] is False
    assert out["execution_authority"] == "NONE"
    assert out["order_authority"] == "BLOCKED"
    assert out["live_trade_authority"] == "BLOCKED"
    assert out["source_code_mutation_applied"] is False
    assert out["self_modification_applied"] is False
    assert out["external_content_instruction_authority"] is False


def test_same_context_cooldown_prevents_repeat_ai_call():
    first, _ = m.observer_tick(
        policy(),
        progress=progress(),
        next_hypothesis=next_hypothesis(),
        factory=factory(),
        manual_video_registry=registry(),
        previous=None,
        search_caller=lambda prompt: (
            "models/gemini-test",
            {"status": "USE", "research_summary": "x", "sources": [], "youtube_candidates": [], "hypothesis_directions": []},
            [],
        ),
        video_caller=None,
        now_ms=1_000_000_000,
    )
    called = {"value": False}

    def should_not_call(prompt):
        called["value"] = True
        raise AssertionError("cooldown failed")

    second, written = m.observer_tick(
        policy(),
        progress=progress(),
        next_hypothesis=next_hypothesis(),
        factory=factory(),
        manual_video_registry=registry(),
        previous=first,
        search_caller=should_not_call,
        video_caller=None,
        now_ms=1_000_001_000,
    )
    assert written is False
    assert second["state"] == "HOLD_EXTERNAL_RESEARCH_COOLDOWN"
    assert called["value"] is False


def test_context_factory_is_derived_copy_and_marks_external_row_non_strategy():
    evidence = {
        "state": "PASS_EXTERNAL_RESEARCH_EVIDENCE_READY",
        "research_summary": "distinct evidence",
        "search_sources": [
            {
                "source_kind": "ACADEMIC",
                "credibility_tier": 2,
                "mechanism": "basis dislocation",
                "local_test_needed": "prospective test",
                "reproducibility_gap": "",
            }
        ],
        "youtube_extracts": [],
        "hypothesis_directions": [
            {
                "family_id": "basis_oi_deleveraging",
                "mechanism": "positioning expansion reversion",
                "required_sources": ["basis", "open_interest"],
                "falsification_test": "controls",
                "distinct_from_current": "different state variable",
            }
        ],
        "receipt_sha256": "a" * 64,
        "context_sha256": "b" * 64,
    }
    original = factory()
    derived = m.build_context_factory(original, evidence)
    assert derived is not None
    assert "external_research_observer_context" not in original["families"]
    row = derived["families"]["external_research_observer_context"]
    assert row["status"] == "ADVISORY_CONTEXT_ONLY_NOT_ECONOMIC_FAMILY"
    assert row["reactivation_allowed"] is False
    assert row["mechanism"]["context_only_not_existing_strategy"] is True
    adapter = derived["external_research_context_adapter"]
    assert adapter["selection_authority"] is False
    assert adapter["execution_authority"] == "NONE"
    assert adapter["order_authority"] == "BLOCKED"
