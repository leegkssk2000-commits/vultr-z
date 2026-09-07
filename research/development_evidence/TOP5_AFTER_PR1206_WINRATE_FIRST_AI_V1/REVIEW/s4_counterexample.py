"""Bounded synthetic review only: no market replay, feature scan, or economics."""
from pathlib import Path
import hashlib
import json
from unittest.mock import patch

from backend.research.rebuild import top5_development_native_v1 as native
from backend.research.rebuild import trend_rider_wr80_us_chase_cooling_child_policy_v1 as primary

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).parent


def proposed_allow(rows, signal_index, side, enabled=True):
    if type(enabled) is not bool:
        raise ValueError("enabled must be bool")
    if not enabled:
        return True
    sign = {"long": 1, "short": -1}[side]
    row = rows[signal_index]
    return sign * (row["close"] - row["open"]) >= 0


def run():
    rows = []
    for i in range(69):
        opening = 100 + i * .04
        closing = opening + (-.02 if i in (66, 68) else .03)
        rows.append(dict(ts_ms=i * native.HOUR, ts=i * native.HOUR,
                         bar_open_ts=i * native.HOUR, bar_close_ts=(i + 1) * native.HOUR,
                         open=opening, close=closing, high=max(opening, closing) + .3,
                         low=min(opening, closing) - .3, volume=10.))
    cfg = primary.TrendRiderWR80USChaseCoolingConfig()
    cache = native.NativeFeatureCache(rows, cfg)
    with patch.object(native.native, "compute_trend_rider_feature", cache.feature):
        feature = primary.compute_trend_rider_feature(
            rows, symbol="BTC-USDT", now_ts_ms=rows[-1]["ts_ms"], config=cfg)
    intent = primary.build_trend_rider_intent(
        feature, policy_source_sha="a" * 40, verified_round_trip_cost_bps=20, config=cfg)
    assert intent.no_trade is False and intent.side == "long"
    assert feature.values["long_transition_fresh"] is True
    assert rows[-2]["close"] >= rows[-2]["open"]
    assert proposed_allow(rows, 68, "long") is False
    assert proposed_allow(rows, 68, "long", enabled=False) is True
    future = rows + [dict(rows[-1], open=1., close=999., high=1000., low=.1)]
    assert proposed_allow(future, 68, "long") == proposed_allow(rows, 68, "long")
    # A positive body inside prior range passes the proposed rule but fails the
    # already failed previous-high breakout predicate. Thus they are not equal.
    inside = [{"open": 100., "close": 101., "high": 102., "low": 99.},
              {"open": 101., "close": 101.2, "high": 101.5, "low": 100.8}]
    assert proposed_allow(inside, 1, "long") is True
    assert inside[1]["close"] < inside[0]["high"]
    # Mirrored short and exact doji boundary; no second fitted cutoff.
    assert proposed_allow([{"open": 100., "close": 101.}], 0, "short") is False
    assert proposed_allow([{"open": 100., "close": 100.}], 0, "short") is True
    assert proposed_allow([{"open": 100., "close": 100.}], 0, "long") is True
    paths = [
        "AGENTS.md",
        "backend/research/rebuild/top5_development_native_v1.py",
        "backend/research/rebuild/trend_policy_batch_v1.py",
        "backend/research/rebuild/trend_rider_transition_freshness_child_policy_v1.py",
        "backend/research/rebuild/trend_rider_wr80_us_chase_cooling_child_policy_v1.py",
        "backend/research/rebuild/top5_native_finite_runner_v1.py",
        "backend/research/rebuild/trend_primary_combined_v1.py",
        "backend/research/rebuild/top5_development_repair_v1.py",
        "backend/research/contracts/top5_development_repair_v1.json",
        "backend/research/contracts/top5_development_children_v1.json",
        "backend/research/contracts/top5_external_children_v1.json",
        "backend/research/contracts/top5_state_children_v1.json",
        "backend/research/contracts/top5_no_credit_exit_v1.json",
        "backend/research/rebuild/trend_rider_momentum_child_policy_v1.py",
        "backend/research/rebuild/trend_rider_multiscale_alignment_child_policy_v1.py",
        "backend/research/rebuild/trend_rider_atr_expansion_child_policy_v1.py",
        "backend/research/rebuild/trend_rider_wr8125_structural_consensus_child_policy_v1.py",
        "backend/research/rebuild/trend_rider_wr8125_peer_consensus_child_policy_v1.py",
    ]
    result = {
        "scope_key": "TOP5_AFTER_PR1206_WINRATE_FIRST_AI_V1", "role": "S4",
        "base_sha": "2646f818775caff88a97f81fe255b393eb9c141d",
        "hypothesis_from": "S1; root sole chooser; not yet implementation signoff",
        "proposed_rule": "Veto iff side_sign * (signal_close - signal_open) < 0; doji allowed",
        "validation": "PASS_BOUNDED_SYNTHETIC_PREDICATE_REVIEW",
        "checks": ["exact native Primary accepts adverse current candle", "freshness edge retained",
                   "veto disabled admits original event", "appended future does not alter fixed-index predicate",
                   "strict failed prior-extreme rule differs from current-body rule",
                   "long/short symmetry and doji equality"],
        "synthetic_native_example": {"side": intent.side, "signal_index": 68,
            "signal_open": rows[68]["open"], "signal_close": rows[68]["close"],
            "native_initial_stop": intent.sl, "chase_atr": feature.values["chase_atr"],
            "native_long_confirm": feature.values["long_confirm"],
            "prior_parent_long_confirm": feature.values["prior_parent_long_confirm"],
            "session": feature.values["session"], "body_filter_allowed": False},
        "inputs_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths},
        "authorizing_text_sha256": hashlib.sha256(Path(
            "/workspace/scratch/38836b99128d/upload/ZEL_AFTER_PR1206_WINRATE_FIRST_AI_WORK_V5(1).txt").read_bytes()).hexdigest(),
        "limits": {"market_replays": 0, "market_feature_passes": 0, "cutoff_scans": 0,
                   "stored_406_ledger_reaudits": 0, "historical_16_30_reaudits": 0,
                   "paid_api_calls": 0, "child_agents": 0, "economic_performance_claim": False,
                   "native_price_files_read": False, "actual_missed_winner_count": "DEPENDENT_ON_S1"},
    }
    result["review_code_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (OUT / "s4_counterexample_result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"validation": result["validation"], "synthetic_native_example": result["synthetic_native_example"]}))


if __name__ == "__main__":
    run()
