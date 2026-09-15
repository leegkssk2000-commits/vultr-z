from __future__ import annotations

from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import pandas as pd  # type: ignore[import-untyped]
import pytest

from backend.research.rebuild import scalp7_candle_anatomy_v2 as a

TF = 900_000
IDENTITY = "scalp7_break_15m_fixture_v2"


def fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, pd.DataFrame]]:
    frames = {
        "BTC-USDT": pd.DataFrame(
            [
                {
                    "open_ts_ms": i * TF,
                    "close_ts_ms": (i + 1) * TF,
                    "available_ts_ms": (i + 1) * TF,
                    "segment_id": "a",
                    "open": 100 + i - 0.2,
                    "high": 100 + i + 0.5,
                    "low": 100 + i - 0.5,
                    "close": 100 + i,
                    "volume": i,
                }
                for i in range(150)
            ]
        )
    }
    windows = [
        {
            "label": "v",
            "partition": "validation",
            "start_ms": 15 * TF,
            "end_ms": 60 * TF,
        },
        {"label": "r", "partition": "rolling", "start_ms": 60 * TF, "end_ms": 140 * TF},
    ]
    ledger: dict[str, Any] = {
        "trades": [],
        "unresolved": [],
        "window_receipts": [{"window": w} for w in windows],
    }
    nets = [10.0, 20.0, 30.0, 100.0, -10.0, -20.0, 0.0]
    mfes = [2.0, 3.0, 4.0, 6.0, 0.2, 1.2, 1.0]
    holds = [3, 4, 3, 5, 1, 2, 2]
    for partition, label, anchor in [("validation", "v", 20), ("rolling", "r", 75)]:
        for i, (net, mfe, hold) in enumerate(zip(nets, mfes, holds)):
            stamp = (anchor + i * 3) * TF
            ledger["trades"].append(
                {
                    "identity": IDENTITY,
                    "lane": "break_and_continue",
                    "symbol": "BTC-USDT",
                    "side": 1,
                    "timeframe_min": 15,
                    "signal_open_ts_ms": stamp,
                    "signal_ts_ms": stamp + TF,
                    "entry_ts_ms": stamp + TF,
                    "exit_ts_ms": stamp + (hold + 1) * TF,
                    "outcome_available_ts_ms": stamp + (hold + 1) * TF,
                    "gross_bps": net + 1,
                    "cost_bps": 1.0,
                    "net_bps": net,
                    "mfe_R": mfe,
                    "hold_bars": hold,
                    "reason": "TEST_FIXTURE",
                    "window_label": label,
                    "partition": partition,
                }
            )
    evidence = {
        "candidate": {"identity": IDENTITY, "lane": "break_and_continue", "tf": 15},
        "module_sha256": "a" * 64,
        "ledger_sha256": "b" * 64,
    }
    evidence["window_receipts"] = deepcopy(ledger["window_receipts"])
    return evidence, ledger, frames


def test_partitions_remain_separate_and_categories_are_descriptive() -> None:
    evidence, ledger, frames = fixture()
    report = a.build_anatomy(evidence, ledger, frames)
    assert report["economic_executions"] == 0
    assert report["outcome_labels_are_diagnostic_only"]
    for partition in ("validation", "rolling"):
        body = report["partitions"][partition]
        assert body["eligible_saved_trade_count"] == 7
        assert body["neutral_net_trade_count"] == 1
        counts = {k: v["category_count"] for k, v in body["categories"].items()}
        assert counts == {
            "winner": 4,
            "loss": 2,
            "immediate_fail": 2,
            "fat_winner": 1,
            "mfe_giveback": 2,
        }
        assert (
            body["categories"]["fat_winner"]["examples"][0]["saved_trade"]["net_bps"]
            == 100
        )
        assert all(
            e["saved_trade"]["partition"] == partition
            for c in body["categories"].values()
            for e in c["examples"]
        )


def test_first_two_chronological_examples_are_stable_under_input_order() -> None:
    evidence, ledger, frames = fixture()
    original = a.build_anatomy(evidence, ledger, frames)
    ledger["trades"].reverse()
    assert a.build_anatomy(evidence, ledger, frames) == original
    first = original["partitions"]["validation"]["categories"]["winner"]["examples"]
    assert [r["saved_trade"]["net_bps"] for r in first] == [10, 20]


def test_signal_features_never_depend_on_outcome_candle_suffix() -> None:
    evidence, ledger, frames = fixture()
    before = a.build_anatomy(evidence, ledger, frames)
    changed = frames["BTC-USDT"].copy()
    changed.loc[21:, ["open", "high", "low", "close"]] *= 2
    after = a.build_anatomy(evidence, ledger, {"BTC-USDT": changed})
    left = before["partitions"]["validation"]["categories"]["winner"]["examples"][0]
    right = after["partitions"]["validation"]["categories"]["winner"]["examples"][0]
    assert left["causal_features_at_signal"] == right["causal_features_at_signal"]
    assert left["candles"] != right["candles"]
    assert all(
        c["feature_role"] == "OUTCOME_OR_OTHER_SEGMENT_DIAGNOSTIC_ONLY"
        for c in right["candles"]
        if c["relative_bar"] > 0 and not c["missing"]
    )


def test_actual_gap_stays_missing_without_ohlc_or_volume_fill() -> None:
    evidence, ledger, frames = fixture()
    frames["BTC-USDT"] = frames["BTC-USDT"].drop(index=19)
    report = a.build_anatomy(evidence, ledger, frames)
    example = report["partitions"]["validation"]["categories"]["winner"]["examples"][0]
    missing = next(c for c in example["candles"] if c["relative_bar"] == -1)
    assert missing["missing"] and missing["missing_kind"] == "SOURCE_GAP"
    assert missing["synthetic_fill"] is False
    assert "open" not in missing and "volume" not in missing
    assert example["causal_features_at_signal"]["contiguous_prior_bar_count"] == 0
    assert example["causal_features_at_signal"]["signal_range_atr14"] is None


def test_available_after_signal_rejected_instead_of_becoming_feature() -> None:
    evidence, ledger, frames = fixture()
    frames["BTC-USDT"].loc[19, "available_ts_ms"] = 22 * TF
    with pytest.raises(ValueError, match="BEFORE_CAUSAL_FEATURE_AVAILABILITY"):
        a.build_anatomy(evidence, ledger, frames)


def test_exact_window_end_outcome_excluded_like_scoreboard() -> None:
    evidence, ledger, frames = fixture()
    ledger["trades"][0]["exit_ts_ms"] = 60 * TF
    ledger["trades"][0]["outcome_available_ts_ms"] = 60 * TF
    report = a.build_anatomy(evidence, ledger, frames)
    assert report["excluded_counts"] == {"OUTSIDE_COMPLETE_WINDOW_EVIDENCE": 1}
    assert report["partitions"]["validation"]["eligible_saved_trade_count"] == 6


def test_duplicate_trade_wrong_identity_and_partition_rejected() -> None:
    evidence, ledger, frames = fixture()
    changed = deepcopy(ledger)
    changed["trades"].append(changed["trades"][0])
    with pytest.raises(ValueError, match="DUPLICATE_TRADE"):
        a.build_anatomy(evidence, changed, frames)
    changed = deepcopy(ledger)
    changed["trades"][0]["identity"] = "legacy_1h"
    with pytest.raises(ValueError, match="CURRENT_REBUILD"):
        a.build_anatomy(evidence, changed, frames)
    changed = deepcopy(ledger)
    changed["trades"][0]["partition"] = "rolling"
    with pytest.raises(ValueError, match="PARTITION_RECEIPT"):
        a.build_anatomy(evidence, changed, frames)


def test_legacy_timeframe_rejected() -> None:
    evidence, ledger, frames = fixture()
    evidence["candidate"]["tf"] = 60
    with pytest.raises(ValueError, match="CURRENT_15M30M"):
        a.build_anatomy(evidence, ledger, frames)


def test_no_trade_partitions_still_have_explicit_zero_examples() -> None:
    evidence, ledger, frames = fixture()
    ledger["trades"] = []
    report = a.build_anatomy(evidence, ledger, frames)
    assert set(report["partitions"]) == {"validation", "rolling"}
    assert all(
        p["eligible_saved_trade_count"] == 0 for p in report["partitions"].values()
    )
    assert "No examples" in a.render_svg(report, "rolling")


def test_vector_chart_is_valid_xml_and_preserves_gap_annotation() -> None:
    evidence, ledger, frames = fixture()
    frames["BTC-USDT"] = frames["BTC-USDT"].drop(index=19)
    report = a.build_anatomy(evidence, ledger, frames)
    svg = a.render_svg(report, "validation")
    assert ET.fromstring(svg).tag.endswith("svg")
    assert 'stroke-dasharray="4 3"' in svg
    assert "outcome anatomy only" in svg
    assert "saved results only; no economic rerun" in svg


def saved_result(tmp_path: Path) -> tuple[Path, dict[str, pd.DataFrame]]:
    evidence, ledger, frames = fixture()
    raw = gzip.compress(json.dumps(ledger).encode(), mtime=0)
    path = tmp_path / "results" / "saved.trades.json.gz"
    path.parent.mkdir()
    path.write_bytes(raw)
    evidence["ledger_path"] = "results/saved.trades.json.gz"
    evidence["ledger_sha256"] = hashlib.sha256(raw).hexdigest()
    result = tmp_path / "results" / "saved.json"
    result.write_text(json.dumps(evidence))
    return result, frames


def test_saved_extraction_binds_hashes_and_is_idempotent(tmp_path: Path) -> None:
    result, frames = saved_result(tmp_path)
    report = a.extract_saved(result, frames, tmp_path / "anatomy", repo_root=tmp_path)
    assert (
        report["source_evidence_sha256"]
        == hashlib.sha256(result.read_bytes()).hexdigest()
    )
    assert len(list((tmp_path / "anatomy").glob("*"))) == 3
    before = {p.name: p.read_bytes() for p in (tmp_path / "anatomy").iterdir()}
    assert (
        a.extract_saved(result, frames, tmp_path / "anatomy", repo_root=tmp_path)
        == report
    )
    assert before == {p.name: p.read_bytes() for p in (tmp_path / "anatomy").iterdir()}


def test_changed_saved_ledger_fails_before_artifact_write(tmp_path: Path) -> None:
    result, frames = saved_result(tmp_path)
    ledger = tmp_path / "results" / "saved.trades.json.gz"
    ledger.write_bytes(ledger.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="SAVED_LEDGER_HASH_MISMATCH"):
        a.extract_saved(result, frames, tmp_path / "anatomy", repo_root=tmp_path)
    assert not (tmp_path / "anatomy").exists()


def test_missing_result_never_runs_an_economics_fallback(tmp_path: Path) -> None:
    _, _, frames = fixture()
    with pytest.raises(FileNotFoundError):
        a.extract_saved(
            tmp_path / "missing.json", frames, tmp_path / "anatomy", repo_root=tmp_path
        )
    assert not (tmp_path / "anatomy").exists()


def test_stored_output_cannot_be_overwritten_with_changed_chart(tmp_path: Path) -> None:
    result, frames = saved_result(tmp_path)
    a.extract_saved(result, frames, tmp_path / "anatomy", repo_root=tmp_path)
    changed = frames["BTC-USDT"].copy()
    changed["volume"] += 1
    with pytest.raises(ValueError, match="OUTPUT_EXISTS_WITH_DIFFERENT_CONTENT"):
        a.extract_saved(
            result, {"BTC-USDT": changed}, tmp_path / "anatomy", repo_root=tmp_path
        )


def test_trade_lane_must_match_the_candidate_lane() -> None:
    evidence, ledger, frames = fixture()
    ledger["trades"][0]["lane"] = "supertrend_pullback"
    with pytest.raises(ValueError, match="CURRENT_REBUILD"):
        a.build_anatomy(evidence, ledger, frames)


def test_evidence_windows_must_match_the_hash_bound_ledger() -> None:
    evidence, ledger, frames = fixture()
    evidence["window_receipts"][0]["window"]["end_ms"] += TF
    with pytest.raises(ValueError, match="EVIDENCE_LEDGER_WINDOWS_MISMATCH"):
        a.build_anatomy(evidence, ledger, frames)


def test_binding_repair_cohort_is_explicit_in_each_artifact() -> None:
    evidence, ledger, frames = fixture()
    evidence["source_binding_repair_sha256"] = "c" * 64
    report = a.build_anatomy(evidence, ledger, frames)
    assert report["source_result_cohort"] == "SOURCE_BINDING_REPAIR"
    assert report["source_binding_repair_sha256"] == "c" * 64
