"""Issue1414 pre-automation proofs: generated prices/cache only, no market economics.

Fibonacci/candle arithmetic below is an INTERNAL_TRANSLATION fixture. It is
not an attribution of those ratios/inequalities to any cached video author.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from backend.research.architecture_factory import a1_youtube_diversity_scout_v1 as scout
from backend.research.rebuild import scalp7_economic_rider_v1 as rider
from backend.research.rebuild import scalp7_execution_v2 as execution
from backend.research.rebuild.economic7_campaign_registry_v1 import (
    CampaignLedger,
    CandidateIdentity,
)
from backend.research.rebuild.scalp7_source_data_v2 import aggregate_minutes

ROOT = Path(__file__).resolve().parents[1]
TF = 1_800_000


def bars(values, tf=TF):
    return pd.DataFrame(
        [
            dict(
                open_ts_ms=i * tf,
                close_ts_ms=(i + 1) * tf,
                available_ts_ms=(i + 1) * tf,
                segment_id="fixture",
                open=o,
                high=h,
                low=lo,
                close=c,
            )
            for i, (o, h, lo, c) in enumerate(values)
        ]
    )


def signal(**changes):
    value = dict(
        identity="ISSUE1414_FIXTURE_ONLY",
        lane="qa",
        symbol="BTC-USDT",
        timeframe_min=30,
        side=1,
        signal_open_ts_ms=0,
        signal_ts_ms=TF,
        segment_id="fixture",
        stop_price=95,
        max_hold_bars=1,
    )
    return {**value, **changes}


def replay(frame, signals=None, **kwargs):
    return execution.replay(
        signals or [signal()], {"BTC-USDT": frame}, {"BTC-USDT": 14}, **kwargs
    )


def context():
    return dict(
        blocker="KELTNER_27_WINNERS_COST2_KILLED",
        lane="keltner",
        candidate="issue1414_source_intake_only",
        failure_signature="COST_SENSITIVE_WINNERS_NOT_FRESH",
        required_sources=["completed_price_bars"],
        development_evidence_ref="research/campaigns/scalp7_20261006/issue1377_keltner_orthogonal_v1/REPORT.md",
        implementation_sha256="a" * 64,
        buckets=["fibonacci", "candlestick"],
    )


def test_fibonacci_anchors_only_exist_after_existing_pivot_confirmation():
    frame = bars(
        [
            (100, 104, 94, 100),
            (99, 101, 90, 98),
            (98, 106, 95, 105),
            (106, 115, 104, 110),
            (110, 112, 100, 102),
        ]
    )
    prefix = rider._features(frame.iloc[:4])
    full = rider._features(frame)
    assert prefix == full[:4]  # Future bars do not rewrite prior feature states.
    assert all(r["ctx_pivot_low"] is None for r in full[:2])
    a, b = full[2], full[4]
    assert a["ctx_pivot_low"] == 90 and a["ctx_pivot_available_ts_ms"] == 3 * TF
    assert all(r["ctx_pivot_high"] is None for r in full[:4])
    assert b["ctx_pivot_high"] == 115 and b["ctx_pivot_available_ts_ms"] == 5 * TF
    # 0.618 is a test constant, not a newly accepted source/native strategy rule.
    available = max(a["ctx_pivot_available_ts_ms"], b["ctx_pivot_available_ts_ms"])
    assert available > 4 * TF
    level = b["ctx_pivot_high"] - 0.618 * (b["ctx_pivot_high"] - a["ctx_pivot_low"])
    assert level == pytest.approx(99.55)


def test_candle_confirmation_context_and_next_open_never_same_close():
    frame = bars(
        [
            (101, 102, 98, 99),
            (98, 104, 97, 103),
            (107, 108, 106, 107),
            (108, 109, 107, 108),
        ]
    )
    previous, current = frame.iloc[0], frame.iloc[1]
    engulf = (
        previous.close < previous.open
        and current.close > current.open
        and current.open <= previous.close
        and current.close >= previous.open
    )
    assert engulf  # INTERNAL_TRANSLATION inequality, not a video reproduction.
    s = signal(signal_open_ts_ms=TF, signal_ts_ms=2 * TF)
    out = replay(frame, [s])
    assert out["trades"][0]["entry_ts_ms"] == 2 * TF
    assert out["trades"][0]["entry_prices"]["BTC-USDT"] == 107
    assert out["trades"][0]["entry_prices"]["BTC-USDT"] != current.close
    frame.loc[1, "available_ts_ms"] = 2 * TF + 1
    out = replay(frame, [dict(s, signal_ts_ms=2 * TF + 1)])
    assert out["rejections"]["LATE_OBSERVATION_NOT_HISTORICAL_OPEN_FILL"] == 1


def test_higher_timeframe_join_obeys_actual_completion_and_late_receipt():
    lower = bars([(100, 101, 99, 100)] * 6, tf=TF // 2)
    higher = bars([(100, 101, 99, 100)] * 3)
    higher.loc[0, "available_ts_ms"] = TF + 1
    enriched = rider.prepare_frames({"BTC-USDT": lower}, {"BTC-USDT": higher})[
        "BTC-USDT"
    ]
    assert not enriched.iloc[0].ctx_usable
    assert not enriched.iloc[1].ctx_usable
    assert enriched.iloc[2].ctx_usable
    assert enriched.iloc[2].ctx_available_ts_ms <= enriched.iloc[2].available_ts_ms


def test_revised_future_candle_cannot_change_already_available_context():
    frame = bars([(100, 101, 99, 100)] * 8)
    before = rider._features(frame)
    frame.loc[6:, ["open", "high", "low", "close"]] = [200, 205, 190, 202]
    assert rider._features(frame)[:6] == before[:6]


def test_generated_six_symbol_native_aggregation_has_unknown_volume_units():
    minute = pd.DataFrame(
        dict(
            timestamp_ms=range(0, 120 * 60_000, 60_000),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=1.0,
        )
    )
    for symbol in (
        "BTC-USDT",
        "ETH-USDT",
        "SOL-USDT",
        "XRP-USDT",
        "LINK-USDT",
        "DOGE-USDT",
    ):
        result = aggregate_minutes(minute, 30)
        assert len(result) == 4 and result.attrs["volume_units"] == "UNKNOWN"
        assert (
            result.attrs["availability_basis"]
            == "BAR_CLOSE_MODEL_NOT_OBSERVED_HISTORICAL_DELIVERY"
        )
        assert symbol  # This count is fixture coverage, never genuine historical signal density.


def test_no_filter_baseline_and_fat_winner_preserved_in_full_fixture_chronology():
    frame = bars(
        [
            (100, 101, 99, 100),
            (100, 110, 98, 108),
            (110, 112, 109, 111),
            (111, 112, 110, 111),
            (111, 112, 110, 111),
        ]
    )
    s = signal()
    baseline = replay(frame, [s])
    noop_child = replay(frame, [dict(s)])
    assert baseline == noop_child
    assert baseline["trades"][0]["gross_bps"] == pytest.approx(1000)
    assert baseline["signal_count"] == 1 and not baseline["unresolved"]
    # Later overlapping opportunity remains in census and is rejected by ownership.
    overlapping = dict(s, signal_open_ts_ms=TF, signal_ts_ms=2 * TF)
    owned = replay(frame, [signal(max_hold_bars=3), overlapping])
    assert owned["signal_count"] == 2
    assert owned["rejections"]["POSITION_ALREADY_OWNED"] == 1


def test_adverse_stop_first_and_missing_fill_have_separate_terminal_states():
    stopped = replay(
        bars([(100, 101, 99, 100), (100, 112, 94, 108), (108, 109, 107, 108)]),
        [signal(take_profit_r=2)],
    )
    assert stopped["trades"][0]["reason"] == "STOP_FIRST"
    missing = bars([(100, 101, 99, 100)] * 3).drop(index=1).reset_index(drop=True)
    out = replay(missing)
    assert not out["trades"] and out["rejections"]["ENTRY_GAP"] == 1


def test_existing_btc_long_funding_preserves_sign_and_adverse_boundary():
    from ops.issue1388_alpha_screen_v1 import funding_for_btc_trade

    trade = dict(entry_ts_ms=100, exit_ts_ms=300, entry_price=100)
    rows = [
        dict(fundingTime=100, fundingRate=-0.001, markPrice=100),
        dict(fundingTime=200, fundingRate=-0.002, markPrice=100),
        dict(fundingTime=300, fundingRate=0.001, markPrice=100),
    ]
    debit, count = funding_for_btc_trade(trade, rows)
    assert debit == pytest.approx(-10) and count == 2
    # Existing function is LONG BTC only: no claim of general short/pair support.
    assert "side" not in trade


def test_existing_registry_rejects_cross_owner_without_real_claim(tmp_path):
    ledger = CampaignLedger(tmp_path / "fixture-only.db")
    owner = "CLOUD_WORK_COORDINATOR_ISSUE1358_V1"
    ledger.create_scope("FIXTURE_ONLY", owner, 0, 0, {"economic_enabled": False})
    ident = CandidateIdentity("fixture", "qa", "qa", "ONE_AXIS", *(["a" * 64] * 4))
    with pytest.raises(PermissionError, match="SINGLE_OWNER_REQUIRED"):
        ledger.reserve("FIXTURE_ONLY", "ISSUE1414_NOT_ECONOMIC_OWNER", ident)
    assert ledger.status("FIXTURE_ONLY")["executions_started"] == 0


def test_unverified_popularity_never_becomes_observed_economic_evidence():
    rows = scout._normalize_search_rows(
        {
            "videos": [
                dict(
                    bucket="candlestick",
                    url="https://www.youtube.com/watch?v=abcdefghijk",
                    channel="fixture",
                    claimed_view_count=9999999,
                )
            ]
        },
        {},
    )
    assert rows[0]["observed_views"] is None
    assert not rows[0]["view_count_verified"]
    review = dict(
        creator_claims=["I earn one million"],
        reproducible_mechanisms=[
            dict(mechanism="hypothesis", local_test_needed="falsify")
        ],
    )
    source = scout._accepted_source(rows[0], review, "UNUSED_FIXTURE")
    assert source["accepted_for_hypothesis_only"] is True
    assert (
        source["selection_authority"] is False
        and source["promotion_authority"] is False
    )
    assert source["source_rule_readiness"] == "SOURCE_RULE_INCOMPLETE"
    assert source["screening_eligible"] is False


@pytest.mark.parametrize("anchor", ["EX_POST", "DISCRETIONARY"])
def test_subjective_or_retrospective_anchor_is_vetoed(anchor):
    out = scout._source_rule_readiness({"source_rule": {"anchor_selection": anchor}})
    assert out["source_rule_readiness"] == "UNIMPLEMENTABLE_DISCRETIONARY"
    assert out["screening_eligible"] is False


def test_cached_native_scout_non_economic_dry_run_never_calls_provider(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    def forbidden(*args, **kwargs):
        pytest.fail("NO_PAID_OR_NETWORK_PROVIDER_CALL_ALLOWED")

    monkeypatch.setattr(scout, "call_gemini_search", forbidden)
    monkeypatch.setattr(scout, "call_gemini_video", forbidden)
    value = scout.run(
        tmp_path / "cache-dry-run.json",
        ROOT / scout.DEFAULT_EXISTING,
        ROOT / scout.DEFAULT_REGISTRY,
        context=context(),
    )
    assert (
        value["execution_authority"] == "NONE" and value["order_authority"] == "BLOCKED"
    )
    assert value["promotion_authority"] is False
    assert value["request_audit"]["requests"] == []
    assert value["request_audit"]["generation_requests"] == 0
    assert value["request_audit"]["cost_usd"] == 0
    assert json.loads((tmp_path / "cache-dry-run.json").read_text()) == value
