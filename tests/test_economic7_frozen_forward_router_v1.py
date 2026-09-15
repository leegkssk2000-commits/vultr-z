from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from backend.research.rebuild.economic7_frozen_forward_router_v1 import (
    ARTIFACTS,
    FrozenForwardRouter,
    load_frozen_spec,
    digest,
)

T = 3_600_000
BINDINGS = {
    lane: {"rule_hash": lane + "-hash", "code_sha": "sealed-code"}
    for lane in ("KELTNER", "RIDER", "SQUEEZE", "MR")
}


@pytest.fixture
def spec(tmp_path: Path):
    maps = {}
    for lane in BINDINGS:
        maps[lane] = {
            "levels": [
                {
                    "columns": ["regime"],
                    "states": {
                        regime: {"risk": 1.0, "label": "GREEN"}
                        for regime in (
                            "PANIC_DISPERSION",
                            "TREND_DISPERSED",
                            "TREND_COHERENT",
                        )
                    },
                }
            ]
        }
    fixtures: dict[str, dict[str, Any]] = {
        "v1": {"chosen": "STATE_GATE_FAILOVER_1.00", "state_maps": maps},
        "v2": {"train_selected": True},
        "features": {
            "regime_thresholds_train_only": {
                "disp_q67": 0.01,
                "meanabs_q85": 0.03,
                "vol_q25": 0.8,
                "vol_q67": 1.1,
            }
        },
        "crowding": {
            "chosen": "CAP_1.0",
            "base_rider_weight_train_only": 0.7,
            "vol_q85_train_only": 1.5,
            "signal_load24_q85_train_only": 5,
        },
    }
    hashes = {}
    for key, name in ARTIFACTS.items():
        raw = json.dumps(dict(fixtures[key], cutoff_ts=1)).encode()
        (tmp_path / name).write_bytes(raw)
        hashes[key] = hashlib.sha256(raw).hexdigest()
    return load_frozen_spec(tmp_path, hashes, BINDINGS, 1800_000, 2)


def event(lane="SQUEEZE", ident="s1", at=T, vol=1.0):
    source = {"source": "fixture:closed-source", "content_hash": "fixture-hash"}
    features = dict(
        source,
        bar_open_ts_ms=at - 1800_000,
        bar_close_ts_ms=at,
        available_at_ms=at,
        mean_abs24=0.04,
        dispersion24=0.02,
        breadth=6,
        vol_ratio=vol,
        market_vol_delta3=-0.1,
        prior_signal_load24=0,
        ema21=2,
        ema55=1,
    )
    if lane == "RIDER":
        features.update(mean_abs24=0.01, dispersion24=0.001)
    payload = dict(
        source,
        lane=lane,
        symbol="BTC-USDT",
        side="long",
        setup_id=ident,
        rule_hash=BINDINGS[lane]["rule_hash"],
        code_sha="sealed-code",
        signal_ts_ms=at - 1800_000,
        decision_ts_ms=at,
        available_at_ms=at,
        features=features,
        setup_evidence=dict(source, valid=True, independent=True, available_at_ms=at),
    )

    for item in (payload["features"], payload["setup_evidence"], payload):
        item["content_hash"] = digest(
            {k: v for k, v in item.items() if k != "content_hash"}
        )
    return payload


def decide(router, events, at=T, exposure=None, closed=True):
    return router.decide(
        events,
        at,
        closed_cohort=closed,
        existing_rider_exposure=exposure or {"long": 0.0, "short": 0.0},
    )


def test_outcomes_never_change_decision(spec):
    first = event("KELTNER")
    other = copy.deepcopy(first)
    other.update(net_bps=-999999, future_mfe=99999, final_result="WIN")
    other["content_hash"] = digest(
        {k: v for k, v in other.items() if k != "content_hash"}
    )
    first_result = decide(FrozenForwardRouter(spec), [first])
    other_result = decide(FrozenForwardRouter(spec), [other])
    # The source fingerprint changes; every actual routing field must be equal.
    first_hash = first_result["decisions"][0].pop("event_content_hash")
    other_hash = other_result["decisions"][0].pop("event_content_hash")
    assert first_hash != other_hash
    assert first_result == other_result


def test_future_closed_bar_is_rejected_without_checkpoint_change(spec):
    router = FrozenForwardRouter(spec)
    row = event()
    row["features"]["bar_close_ts_ms"] += 1
    old = router.checkpoint()
    result = decide(router, [row])
    assert result["state"] == "HOLD"
    assert result["cash_fallback"] is True
    assert router.checkpoint() == old


def test_future_cohort_cannot_alter_current_squeeze(spec):
    router = FrozenForwardRouter(spec)
    early = decide(router, [event()])
    assert early["decisions"][0]["chosen_risk_multiplier"] == 1.0
    later = event(ident="s2", at=T + 900_000)
    second = decide(router, [later], at=T + 900_000)
    assert second["decisions"][0]["chosen_risk_multiplier"] == 0.25
    assert early["decisions"][0]["chosen_risk_multiplier"] == 1.0
    assert decide(router, [event()])["state"] == "HOLD"


def test_risk_conservation_and_independent_same_instant_receiver(spec):
    rows = [event(ident="s1"), event(ident="s2"), event("KELTNER", "k1")]
    result = decide(FrozenForwardRouter(spec), rows)
    assert result["state"] == "FROZEN_SHADOW_ROUTED"
    assert result["suppressed_risk"] == 1.5
    assert result["reallocated_risk"] == 1.0
    assert result["cash_risk"] == 0.5
    assert (
        sum(x["chosen_risk_multiplier"] for x in result["decisions"])
        + result["cash_risk"]
        == 3.0
    )
    assert all(x["receiver"] == "k1" for x in result["failover"])
    assert all(x["receiver_setup_evidence"]["independent"] for x in result["failover"])


def test_later_same_hour_receiver_cannot_receive_earlier_risk(spec):
    router = FrozenForwardRouter(spec)
    early = decide(router, [event(ident="s1"), event(ident="s2")])
    assert early["cash_risk"] == 1.5
    later = decide(router, [event("KELTNER", "k1", at=T + 900_000)], at=T + 900_000)
    assert later["reallocated_risk"] == 0
    assert later["decisions"][0]["chosen_risk_multiplier"] == 1.0


def test_rider_cap_includes_existing_exposure(spec):
    result = decide(
        FrozenForwardRouter(spec),
        [event("RIDER", "r1"), event("RIDER", "r2")],
        exposure={"long": 0.8, "short": 0.0},
    )
    assigned = sum(r["chosen_risk_multiplier"] for r in result["decisions"])
    assert assigned == pytest.approx(0.2)
    assert assigned + 0.8 <= 1.0 + 1e-12


@pytest.mark.parametrize(
    "fault", ["nan", "missing", "late_setup", "stale", "mixed", "unclosed"]
)
def test_integrity_failures_hold(spec, fault):
    row = event()
    if fault == "nan":
        row["features"]["vol_ratio"] = float("nan")
    elif fault == "missing":
        del row["features"]["content_hash"]
    elif fault == "late_setup":
        row["setup_evidence"]["available_at_ms"] += 1
    elif fault == "stale":
        row["features"].update(bar_open_ts_ms=0, bar_close_ts_ms=1, available_at_ms=1)
    elif fault == "mixed":
        row["decision_ts_ms"] += 1
    result = decide(FrozenForwardRouter(spec), [row], closed=fault != "unclosed")
    assert result["state"] == "HOLD"
    assert result["order_authority"] == "BLOCKED"


def test_checkpoint_resume_rejects_duplicate_close(spec):
    first = FrozenForwardRouter(spec)
    receipt = decide(first, [event("KELTNER")])
    resumed = FrozenForwardRouter(spec, receipt["checkpoint"])
    assert decide(resumed, [event("KELTNER")])["state"] == "HOLD"


def test_artifact_tamper_is_rejected(spec, tmp_path):
    path = tmp_path / ARTIFACTS["v2"]
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        load_frozen_spec(tmp_path, spec.hashes, BINDINGS, 1800_000, 2)


def test_checkpoint_checksum_rejects_state_corruption(spec):
    router = FrozenForwardRouter(spec)
    state = decide(router, [event("KELTNER")])["checkpoint"]
    state["squeeze_count"] = 99
    with pytest.raises(ValueError, match="CHECKSUM"):
        FrozenForwardRouter(spec, state)


def test_initial_hold_checkpoint_resumes(spec):
    router = FrozenForwardRouter(spec)
    state = decide(router, [event()], closed=False)["checkpoint"]
    resumed = FrozenForwardRouter(spec, state)
    assert decide(resumed, [event()])["state"] == "FROZEN_SHADOW_ROUTED"


def test_setup_dedup_survives_checkpoint_and_later_cohort(spec):
    router = FrozenForwardRouter(spec)
    state = decide(router, [event("KELTNER", "repeated")])["checkpoint"]
    resumed = FrozenForwardRouter(spec, state)
    duplicate = event("KELTNER", "repeated", at=T + 900_000)
    assert (
        decide(resumed, [duplicate], at=T + 900_000)["reason"]
        == "DUPLICATE_SETUP_PRIOR_COHORT"
    )


def test_changed_feature_payload_hash_is_rejected(spec):
    row = event("KELTNER")
    row["features"]["breadth"] = 4
    assert (
        decide(FrozenForwardRouter(spec), [row])["reason"]
        == "SOURCE_PAYLOAD_HASH_MISMATCH"
    )


@pytest.mark.parametrize(
    "field,value", [("setup_evidence", []), ("setup_evidence", "bad"), ("features", [])]
)
def test_invalid_nested_schema_holds(spec, field, value):
    row = event()
    row[field] = value
    assert decide(FrozenForwardRouter(spec), [row])["state"] == "HOLD"


@pytest.mark.parametrize("boundary", [0, 1])
def test_forward_boundary_cannot_include_training_cutoff(spec, tmp_path, boundary):
    with pytest.raises(
        ValueError, match="FORWARD_BOUNDARY_NOT_AFTER_FROZEN_TRAINING_CUTOFF"
    ):
        load_frozen_spec(tmp_path, spec.hashes, BINDINGS, 1800_000, boundary)


def test_forward_boundary_immediately_after_training_cutoff_is_valid(spec, tmp_path):
    cutoff = spec.artifacts["v1"]["cutoff_ts"]
    after = load_frozen_spec(tmp_path, spec.hashes, BINDINGS, 1800_000, cutoff + 1)
    assert after.forward_start_ts_ms == cutoff + 1
