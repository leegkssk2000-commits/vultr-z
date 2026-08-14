from __future__ import annotations

from backend.production import zel_production_research_source_attribution_v1 as m


def policy():
    return {
        "schema_version": m.POLICY_SCHEMA,
        "mode": "PAPER",
        "role": "OBSERVER_ONLY_SOURCE_ATTRIBUTION_NOT_ROUTE",
        "external_evidence_path": "/tmp/external.json",
        "next_hypothesis_path": "/tmp/next.json",
        "comparison_path": "/tmp/comparison.json",
        "history_path": "/tmp/history.ndjson",
        "output_path": "/tmp/output.json",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_allowed": False,
        "self_modification_allowed": False,
    }


def fixtures(*, evidence_ready=True, refs=True, preferred=True):
    safe = m.safety()
    paper_url = "https://example.org/basis-paper"
    video_url = "https://www.youtube.com/watch?v=sourcevideo1"
    external = {
        "receipt_sha256": "e1",
        "state": m.PASS_EXTERNAL if evidence_ready else "HOLD_EXTERNAL_RESEARCH_CALL_FAILED",
        "error_class": "RuntimeError" if not evidence_ready else "",
        "error_code": "EXTERNAL_RESEARCH_SEARCH_FAILED" if not evidence_ready else "",
        "search_sources": [
            {
                "url": paper_url,
                "title": "Basis dislocation paper",
                "publisher": "Research",
                "source_kind": "ACADEMIC",
                "credibility_tier": 2,
                "mechanism": "basis and positioning dislocations can mean revert",
                "local_test_needed": "prospective falsification",
            }
        ],
        "youtube_extracts": [
            {
                "url": video_url,
                "title": "Microstructure architecture",
                "channel": "Quant Research",
                "status": "USE",
                "view_count_verified": True,
                "observed_views": 250000,
                "reproducible_mechanisms": [
                    {
                        "mechanism": "separate positioning context from trigger",
                        "architecture_layer": "context",
                        "local_test_needed": "layer ablation",
                        "limitations": "creator sample not authoritative",
                    }
                ],
            }
        ],
        "hypothesis_directions": [
            {
                "family_id": "basis_oi_deleveraging",
                "mechanism": "basis/OI positioning reversion",
                "required_sources": ["basis", "open_interest"],
                "falsification_test": "prospective controls",
                "distinct_from_current": "positioning state rather than funding elasticity",
                "evidence_urls": [paper_url, video_url] if refs else [],
            }
        ],
        **safe,
    }
    nxt = {
        "receipt_sha256": "n1",
        "proposals": [
            {
                "proposal_id": "p1",
                "proposal_type": "NEW_ECONOMIC_FAMILY",
                "family_id": "basis_oi_deleveraging",
                "economic_mechanism": "basis/OI positioning reversion",
                "required_sources": ["basis", "open_interest"],
                "template_id": "basis_open_interest_v1",
            }
        ],
        **safe,
    }
    comparison = {
        "receipt_sha256": "c1",
        "comparison_count": 1,
        "comparisons": [
            {
                "challenger_family_id": "basis_oi_deleveraging",
                "research_preference": m.PREFERRED if preferred else m.REFERENCE,
                "delta_challenger_minus_reference": {
                    "trade_count": 4,
                    "win_rate_pct": 8.0,
                    "net_expectancy": 3.2,
                    "profit_factor": 0.31,
                    "net_pnl": 45.0,
                    "max_dd_pct": -0.8,
                },
            }
        ],
        **safe,
    }
    return external, nxt, comparison


def test_exact_external_sources_and_native_inputs_are_attributed():
    external, nxt, comparison = fixtures()
    out, event = m.attribution_tick(
        policy(),
        external_evidence=external,
        next_hypothesis=nxt,
        comparison=comparison,
        history=[],
    )
    assert out["state"] == "PASS_RESEARCH_SOURCE_ATTRIBUTION_POSITIVE_SIGNAL_CAPTURED"
    assert event is not None
    assert event["attributed_comparison_count"] == 1
    assert event["attributed_source_count"] == 2
    assert event["attributions"][0]["joint_evidence_association"] is True
    aggregate = out["aggregate"]
    assert aggregate["preferred_attributed_count"] == 1
    assert aggregate["native_source_breakdown"]["basis"]["delta_average"]["net_pnl"] == 45.0
    assert aggregate["native_source_breakdown"]["open_interest"]["delta_average"]["profit_factor"] == 0.31
    source_rows = list(aggregate["source_breakdown"].values())
    assert len(source_rows) == 2
    assert any(row["source_type"] == "YOUTUBE" and row["observed_views"] == 250000 for row in source_rows)


def test_missing_explicit_evidence_link_holds_without_guessing():
    external, nxt, comparison = fixtures(refs=False)
    out, event = m.attribution_tick(
        policy(),
        external_evidence=external,
        next_hypothesis=nxt,
        comparison=comparison,
        history=[],
    )
    assert event is not None
    assert out["state"] == "HOLD_RESEARCH_SOURCE_ATTRIBUTION_EXPLICIT_LINK_NOT_READY"
    assert out["current"]["attributed_comparison_count"] == 0
    assert out["current"]["unattributed"]["missing_explicit_evidence_ref_family_ids"] == ["basis_oi_deleveraging"]


def test_external_call_failure_is_visible_and_fail_closed():
    external, nxt, comparison = fixtures(evidence_ready=False)
    out, event = m.attribution_tick(
        policy(),
        external_evidence=external,
        next_hypothesis=nxt,
        comparison=comparison,
        history=[],
    )
    assert event is not None
    assert out["state"] == "HOLD_RESEARCH_SOURCE_ATTRIBUTION_EXTERNAL_EVIDENCE_NOT_READY"
    assert out["current"]["external_evidence_error_code"] == "EXTERNAL_RESEARCH_SEARCH_FAILED"


def test_dedup_and_authority_drift_fail_closed():
    external, nxt, comparison = fixtures()
    out, event = m.attribution_tick(
        policy(),
        external_evidence=external,
        next_hypothesis=nxt,
        comparison=comparison,
        history=[],
    )
    assert event is not None
    out2, event2 = m.attribution_tick(
        policy(),
        external_evidence=external,
        next_hypothesis=nxt,
        comparison=comparison,
        history=[event],
    )
    assert event2 is None
    assert out2["aggregate"]["generation_count"] == 1

    bad = dict(nxt)
    bad["execution_authority"] = "LIVE"
    held, rejected = m.attribution_tick(
        policy(),
        external_evidence=external,
        next_hypothesis=bad,
        comparison=comparison,
        history=[],
    )
    assert rejected is None
    assert held["state"] == "HOLD_RESEARCH_SOURCE_ATTRIBUTION_SOURCE_INVALID"
