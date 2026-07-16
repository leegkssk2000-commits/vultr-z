from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "canonical/lico.py"
spec = importlib.util.spec_from_file_location("canonical_lico_r42_test", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def policy(*, max_age_ms: int = 1000):
    return module.SourceConsensusPolicy(
        required_source_prefixes=("cf:", "sheets:"),
        required_metrics=("spread_bps",),
        max_age_ms=max_age_ms,
        numeric_tolerance_by_metric={"spread_bps": Decimal("0.1")},
        minimum_source_confidence=Decimal("0.8"),
        policy_refs=("cf:lico_policy", "sheets:lico_policy"),
        schema_version="r42-test",
    )


def observation(source_id: str, value: object, *, observed_at_ms: int = 9900, confidence: str = "0.9"):
    prefix = "cf:" if source_id.startswith("cf:") else "sheets:"
    return module.SourceObservation(
        source_id=source_id,
        metric_key="spread_bps",
        value=value,
        observed_at_ms=observed_at_ms,
        source_status="ready",
        source_confidence=Decimal(confidence),
        source_ref=f"{prefix}market:spread",
    )


def assert_hold(result, reason: str) -> None:
    assert result.state == "HOLD"
    assert result.action == "hold"
    assert result.fail_closed is True
    assert result.abstain is True
    assert result.execution_authority == "none"
    assert reason in result.reason_codes


def test_canonical_identity_and_authority_boundary() -> None:
    assert module.LICO_OWNER == "canonical/lico.py"
    assert module.LICO_MANIFEST["component"] == "Lico"
    assert module.OBSERVER_ONLY is True
    assert module.EXECUTION_AUTHORITY == "none"
    assert module.RUNTIME_ENABLED is False
    assert module.ORDER_ENABLED is False
    assert module.ALLOWED_ACTIONS == frozenset({"hold", "route_change"})


def test_cf_sheets_consensus_ready() -> None:
    result = module.evaluate_source_consensus(
        (observation("cf:market", "1.0"), observation("sheets:market", "1.0")),
        now_ms=10000,
        policy=policy(),
    )
    assert result.state == "READY"
    assert result.action == "hold"
    assert result.source_parity is True
    assert result.source_consensus is True
    assert result.source_status == "ready"
    assert result.source_disagreement == ()
    assert result.abstain is False
    assert result.source_registry["spread_bps"] == ("cf:market", "sheets:market")


def test_missing_sheets_source_holds() -> None:
    result = module.evaluate_source_consensus(
        (observation("cf:market", 1),),
        now_ms=10000,
        policy=policy(),
    )
    assert_hold(result, "SOURCE_PAIR_INCOMPLETE")


def test_stale_pair_holds() -> None:
    result = module.evaluate_source_consensus(
        (
            observation("cf:market", 1, observed_at_ms=1),
            observation("sheets:market", 1, observed_at_ms=1),
        ),
        now_ms=10000,
        policy=policy(),
    )
    assert_hold(result, "SOURCE_STALE")
    assert result.stale is True


def test_source_disagreement_holds() -> None:
    result = module.evaluate_source_consensus(
        (observation("cf:market", 1), observation("sheets:market", 3)),
        now_ms=10000,
        policy=policy(),
    )
    assert_hold(result, "SOURCE_DISAGREEMENT")
    assert result.source_disagreement == ("spread_bps",)


def test_duplicate_source_prefix_holds() -> None:
    result = module.evaluate_source_consensus(
        (
            observation("cf:market_a", 1),
            observation("cf:market_b", 1),
            observation("sheets:market", 1),
        ),
        now_ms=10000,
        policy=policy(),
    )
    assert_hold(result, "SOURCE_DUPLICATE_PREFIX")


def test_future_timestamp_holds() -> None:
    result = module.evaluate_source_consensus(
        (
            observation("cf:market", 1, observed_at_ms=10001),
            observation("sheets:market", 1),
        ),
        now_ms=10000,
        policy=policy(),
    )
    assert_hold(result, "SOURCE_TIMESTAMP_INVALID")


def test_low_confidence_holds() -> None:
    result = module.evaluate_source_consensus(
        (
            observation("cf:market", 1, confidence="0.7"),
            observation("sheets:market", 1, confidence="0.7"),
        ),
        now_ms=10000,
        policy=policy(),
    )
    assert_hold(result, "SOURCE_CONFIDENCE_BELOW_POLICY")


def test_contract_uses_ssot_references() -> None:
    contract = json.loads((ROOT / "config/q4r3_lico_source_consensus_contract_v1.json").read_text(encoding="utf-8"))
    source_policy = contract["source_policy"]
    assert source_policy["max_age_ms"] == "SSOT.DATA_STALE_MS"
    assert source_policy["numeric_tolerance_by_metric"] == "SSOT.LICO.CONSENSUS_TOLERANCE_BY_METRIC"
    assert source_policy["minimum_source_confidence"] == "SSOT.LICO.MIN_SOURCE_CONFIDENCE"
    assert contract["authority"]["execution_authority"] == "none"
    assert contract["authority"]["runtime_enabled"] is False
    assert contract["authority"]["order_enabled"] is False
