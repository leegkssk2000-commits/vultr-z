from backend.production.zel_production_pre_survivor_ai_value_audit_v1 import audit_tick, safety


def policy():
    return {
        "schema_version": "zel.production_pre_survivor_ai_value_audit_policy.v1",
        "mode": "PAPER",
        "value_role": "OBSERVER_ONLY_REALIZED_RESEARCH_VALUE_NOT_ROUTE",
        "next_hypothesis_path": "/tmp/n",
        "comparison_path": "/tmp/c",
        "incumbent_path": "/tmp/i",
        "history_path": "/tmp/h",
        "output_path": "/tmp/o",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_allowed": False,
        "self_modification_allowed": False,
    }


def fixtures(preferred=True):
    safe = safety()
    nxt = {
        "receipt_sha256": "n1",
        "provider": "GEMINI",
        "model": "fixture",
        "current_family_id": "reference",
        "ai_call_made": True,
        "ai_call_succeeded": True,
        "proposal_count": 2,
        "source_ready_count": 1,
        "template_ready_count": 1,
        **safe,
    }
    comp = {
        "receipt_sha256": "c1",
        "comparison_count": 1,
        "comparisons": [
            {
                "research_preference": "CHALLENGER_RESEARCH_PREFERRED" if preferred else "REFERENCE_RESEARCH_PREFERRED",
                "challenger_family_id": "challenger",
                "delta_challenger_minus_reference": {
                    "trade_count": 5,
                    "win_rate_pct": 2.0,
                    "net_expectancy": 0.1,
                    "profit_factor": 0.2,
                    "net_pnl": 1.5,
                    "max_dd_pct": -0.4,
                },
            }
        ],
        **safe,
    }
    inc = {"receipt_sha256": "i1", "family_id": "challenger", "generation": 3, **safe}
    return nxt, comp, inc


def test_positive_research_value_and_dedup():
    nxt, comp, inc = fixtures(True)
    out, event = audit_tick(policy(), next_hypothesis=nxt, comparison=comp, incumbent=inc, history=[])
    assert out["state"] == "PASS_PRE_SURVIVOR_AI_VALUE_POSITIVE_RESEARCH_SIGNAL"
    assert out["aggregate"]["preferred_challenger_count"] == 1
    assert out["aggregate"]["preferred_epoch_rate_pct"] == 100.0
    assert event is not None
    out2, event2 = audit_tick(policy(), next_hypothesis=nxt, comparison=comp, incumbent=inc, history=[event])
    assert event2 is None
    assert out2["aggregate"]["generation_count"] == 1


def test_no_preference_is_not_value_proof():
    nxt, comp, inc = fixtures(False)
    out, event = audit_tick(policy(), next_hypothesis=nxt, comparison=comp, incumbent=inc, history=[])
    assert event is not None
    assert out["state"] == "HOLD_PRE_SURVIVOR_AI_VALUE_NOT_YET_DEMONSTRATED"
    assert out["aggregate"]["preferred_challenger_count"] == 0


def test_authority_drift_fails_closed():
    nxt, comp, inc = fixtures(True)
    nxt["execution_authority"] = "LIVE"
    out, event = audit_tick(policy(), next_hypothesis=nxt, comparison=comp, incumbent=inc, history=[])
    assert event is None
    assert out["state"] == "HOLD_PRE_SURVIVOR_AI_VALUE_SOURCE_INVALID"
