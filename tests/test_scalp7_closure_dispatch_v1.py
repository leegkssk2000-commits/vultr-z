"""Actual new dispatcher-to-HG synthetic execution; never genuine history."""

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_closure_dispatch_v1 as d
from backend.research.rebuild import scalp7_hg_closure_v1 as hg


def inputs():
    candles = [(100, 100.2, 99.8, 100)] * 35
    candles += [(100 + i + 0.2, 101 + i + 0.2, 100 + i, 101 + i) for i in range(12)]
    candles += [(112, 112.2, 103, 108)]
    source = pd.DataFrame(
        [
            dict(
                open_ts_ms=i * hg.TF,
                close_ts_ms=(i + 1) * hg.TF,
                available_ts_ms=(i + 1) * hg.TF,
                segment_id="a",
                open=o,
                high=h,
                low=lo,
                close=c,
                volume=100.0,
            )
            for i, (o, h, lo, c) in enumerate(candles)
        ]
    )
    source.attrs["data_kind"] = "SYNTHETIC_FIXTURE"
    plan = hg.compile_model(hg.MODEL_ID, {"X": source}, {"tick_size": 0.01})["plans"][0]
    active = plan["order_active_ts_ms"]
    details = pd.DataFrame(
        [
            dict(
                symbol="X",
                open_ts_ms=active + i * 60000,
                close_ts_ms=active + (i + 1) * 60000,
                available_ts_ms=active + (i + 1) * 60000,
                segment_id="a",
                open=o,
                high=h,
                low=lo,
                close=c,
            )
            for i, (o, h, lo, c) in enumerate(
                [(110.0, 113.0, 110.0, 112.0), (108.0, 110.0, 100.0, 104.0)]
            )
        ]
    )
    details.attrs["data_kind"] = "SYNTHETIC_FIXTURE"
    return {"X": source}, {"X": details}


def test_dispatch_runs_raw_producer_and_existing_engine():
    frames, details = inputs()
    result = d.run_fixture(
        hg.MODEL_ID,
        frames,
        details,
        {"tick_size": 0.01},
        fixture_manifest={
            "data_kind": "SYNTHETIC_FIXTURE",
            "construction_reason": "hand-built qualification and protective stop",
        },
    )
    assert len(result["plans"]) == 1
    assert result["executions"][0]["state"] == "CLOSED"
    ledger = result["executions"][0]["ledger"]
    assert [row["effect"] for row in ledger] == ["OPEN", "CLOSE"]
    assert all(row["execution_evidence"] == "MODEL_NOT_OBSERVED" for row in ledger)
    assert result["new_full_runs"] == 0 and result["new_economics"] is None


@pytest.mark.parametrize("kind", ["GENUINE_RAW_HISTORY", None])
def test_new_dispatch_blocks_unapproved_history(kind):
    frames, details = inputs()
    with pytest.raises(PermissionError):
        d.run_fixture(
            hg.MODEL_ID,
            frames,
            details,
            {"tick_size": 0.01},
            fixture_manifest={"data_kind": kind, "construction_reason": "test"},
        )


def test_real_source_flag_blocks_relabelled_history():
    frames, details = inputs()
    frames["X"].attrs["source_rows_are_genuine"] = True
    with pytest.raises(PermissionError):
        d.run_fixture(
            hg.MODEL_ID,
            frames,
            details,
            {"tick_size": 0.01},
            fixture_manifest={
                "data_kind": "SYNTHETIC_FIXTURE",
                "construction_reason": "test",
            },
        )


def test_registry_preserves_original25_and_shared_gajjala_lineage():
    catalog = d.research_catalog()
    assert catalog["original25_count"] == len(set(catalog["original25_ids"])) == 25
    assert catalog["gajjala_alias_independent_model_count"] == 1
    assert len(catalog["new_research_models"]) == 3
    assert not catalog["original25_complete"] and not catalog["g4_complete"]
