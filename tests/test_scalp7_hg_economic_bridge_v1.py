"""Actual source/adapter/portfolio call chain, generated prices only, no FULL."""
from __future__ import annotations
import copy
import hashlib
import json
import runpy
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import pytest
from backend.research.rebuild import scalp7_hg_economic_bridge_v1 as m
from backend.research.rebuild import scalp7_hg_closure_v1 as hg
from backend.research.rebuild import scalp7_exact25_model_runner_v1 as old

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = runpy.run_path(str(ROOT / "tests/test_scalp7_hg_closure_v1.py"))

def inputs_and_binding(detail=None):
    frame, default_detail = FIXTURES["lifecycle_fixture"]()
    if detail is None:
        detail = default_detail.copy(deep=True)
        # Separate normal fills from the frozen shared-capital gap-over-cap
        # rejection: do not weaken that guard just to reproduce standalone PnL.
        detail.loc[detail.index[0], "open"] = 112.21
        detail.loc[detail.index[0], "low"] = 112.0
    else:
        detail = detail.copy(deep=True)
    for value in (frame, detail):
        value.attrs.update(data_kind="SYNTHETIC_FIXTURE", source_rows_are_genuine=False)
    receipt = dict(kind="PRICE_GRID", symbol="X", venue="BINGX", product="USDT_M_PERPETUAL",
        evidence_class="SYNTHETIC_FIXTURE", unit="QUOTE_PRICE_INCREMENT", price_increment="0.01",
        valid_from_ms=0, valid_to_ms=10**12, available_ts_ms=0, source_ref="synthetic:test_fixture")
    sha = hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    config = {"price_grids": {"X": {"receipt": receipt, "canonical_receipt_sha256": sha}}}
    binding = m.freeze_binding(baseline_id="HG1997_DECLARED_MODE", changed_axis="CALLER_CONNECTION_ONLY",
        config=config, data_manifest={"data_kind": "SYNTHETIC_FIXTURE", "construction_reason": "Explicit old HG raw-price regression fixture"},
        cost={"kind": "REFERENCE_ALL_IN_RATE_EXCLUDING_FUNDING", "per_side_rate": 0.001, "funding_status": "UNKNOWN_NOT_ZERO"},
        windows=[dict(name="generated_fixture",kind="VALIDATION",start_ts_ms=0,end_ts_ms=int(frame.iloc[-1].close_ts_ms)+hg.MINUTE)],
        initial_cash_usdt=10000)
    return {"frames": {"X": frame}, "detail_frames": {"X": detail}}, binding

def run(inp, binding):
    return m.run_fixture(binding, inp, expected_binding_sha256=binding["binding_sha256"])

def test_reproduces_generic_adapter_omission_then_cancels_in_new_bridge():
    active = 48 * hg.TF + hg.MINUTE
    detail = pd.DataFrame([FIXTURES["minute"](active, low=102),
        FIXTURES["minute"](active+hg.MINUTE, o=112,h=114,low=111,c=113)])
    inp, binding = inputs_and_binding(detail)
    legacy_compiled = hg.compile_model(hg.MODEL_ID, inp["frames"], {"tick_size": .01})
    legacy = old._conditional(binding, hg, legacy_compiled, inp)
    assert any(x["effect"] == "OPEN" for x in legacy["ledger"])
    current = run(inp,binding)
    assert current["execution"]["ledger"] == []
    assert current["execution"]["executions"][0]["state"] == "CANCELLED"
    assert any(e["status"] == "HG_PREENTRY_SWING_INVALIDATED" for e in current["execution"]["executions"][0]["events"])

def test_normal_fills_equal_existing_hg_fixture_and_cost2_reuses_same_fills():
    inp, binding = inputs_and_binding()
    out = run(inp,binding)
    source = hg.run_synthetic_fixture(inp["frames"], inp["detail_frames"], {"tick_size": .01},
        dataset_kind="SYNTHETIC_FIXTURE",capital=10000,fee_rate=.001)
    actual = out["execution"]["ledger"]
    expected = source["executions"][0]["ledger"]
    fields = ("effect","ts_ms","fill_price","qty_base","fee_usdt")
    assert [{k:x[k] for k in fields} for x in actual] == [{k:x[k] for k in fields} for x in expected]
    assert [x["effect"] for x in actual] == ["OPEN","CLOSE"]
    one = out["cost_scenarios"]["1x"]["episodes"][0]
    two = out["cost_scenarios"]["2x"]["episodes"][0]
    assert one["gross_usdt"] == two["gross_usdt"]
    assert two["cost_usdt"] == pytest.approx(2*one["cost_usdt"])
    assert out["fresh_T"] == out["new_full_runs"] == 0
    assert not out["g4_complete"] and not out["exact_source_reproduction"]
    assert out["authority"] == m.AUTHORITY

def test_same_minute_trigger_stop_stays_unresolved():
    active=48*hg.TF+hg.MINUTE
    inp,b=inputs_and_binding(pd.DataFrame([FIXTURES["minute"](active,h=114,low=102)]))
    out=run(inp,b)
    assert out["unknown_execution_count"]==1 and out["execution"]["ledger"]==[]
    assert out["cost_scenarios"]["1x"]["windows"][0]["net_complete_reference_usdt"] is None

def test_gap_preserves_unresolved_position_without_invented_close():
    inp,b=inputs_and_binding()
    inp["detail_frames"]["X"]=inp["detail_frames"]["X"].drop(index=3).reset_index(drop=True)
    out=run(inp,b)
    assert out["unknown_execution_count"]==1
    assert [x["effect"] for x in out["execution"]["ledger"]]==["OPEN"]

@pytest.mark.parametrize("field,value",[("available_ts_ms",10**11),("valid_to_ms",1),("symbol","WRONG"),("product","SPOT")])
def test_invalid_or_unavailable_grid_rejected(field,value):
    inp,b=inputs_and_binding()
    config=copy.deepcopy(b["config"])
    record=config["price_grids"]["X"]
    record["receipt"][field]=value
    record["canonical_receipt_sha256"]=hashlib.sha256(json.dumps(record["receipt"],sort_keys=True,separators=(",", ":")).encode()).hexdigest()
    with pytest.raises(ValueError): m.compile_model(m.MODEL_ID,inp["frames"],config)

def test_receipt_hash_tampering_rejected():
    inp,b=inputs_and_binding(); cfg=copy.deepcopy(b["config"])
    cfg["price_grids"]["X"]["receipt"]["price_increment"]="0.02"
    with pytest.raises(ValueError,match="HASH_MISMATCH"):m.compile_model(m.MODEL_ID,inp["frames"],cfg)

def test_no_synthetic_metadata_in_genuine_binding():
    inp,b=inputs_and_binding()
    with pytest.raises(PermissionError,match="OBSERVED_HISTORICAL_GRID"):
        m.freeze_binding(baseline_id="fixture",changed_axis="fixture",config=b["config"],
            data_manifest={"data_kind":"GENUINE_RAW_HISTORY","symbols":["X"]},
            cost=b["cost"],windows=b["windows"],initial_cash_usdt=10000)

def test_genuine_loader_is_not_called_without_existing_approval(tmp_path):
    inp,b=inputs_and_binding(); b=copy.deepcopy(b)
    b["data_manifest"]["data_kind"]="GENUINE_RAW_HISTORY"
    missing=tmp_path/"missing.sqlite"
    with patch.object(m,"_replay_inputs",side_effect=AssertionError("REPLAY_FORBIDDEN")) as replay:
        with pytest.raises(PermissionError,match="NEW_FULL_ALLOCATION_ABSENT"):
            m.run_authorized(b,expected_binding_sha256=b["binding_sha256"],registry_path=missing,
                scope="no-approval",owner="no-owner",output_path=tmp_path/"out.json")
        replay.assert_not_called()
    assert not missing.exists() and not (tmp_path/"out.json").exists()

@pytest.mark.parametrize("group",["frames","detail_frames"])
def test_genuine_flag_cannot_enter_synthetic_gateway(group):
    inp,b=inputs_and_binding();inp[group]["X"].attrs["source_rows_are_genuine"]=True
    with pytest.raises(PermissionError,match="MARKET_HISTORY_NOT_A_FIXTURE"):run(inp,b)

def test_foreign_binding_cannot_enter_bridge():
    inp,b=inputs_and_binding();b=copy.deepcopy(b);b["model_id"]="OTHER"
    with pytest.raises(ValueError,match="EXACT_HG_BRIDGE"):run(inp,b)

def test_retuning_is_not_an_accepted_config():
    inp,b=inputs_and_binding();cfg=copy.deepcopy(b["config"]);cfg["be_arm_r"]=1
    with pytest.raises(ValueError,match="EXACT_HG_PRICE_GRID"):m.compile_model(m.MODEL_ID,inp["frames"],cfg)


def test_gap_above_reserved_notional_is_explicitly_rejected_not_repriced():
    _, original_detail = FIXTURES["lifecycle_fixture"]()
    inp, binding = inputs_and_binding(original_detail)
    out = run(inp, binding)
    assert out["execution"]["ledger"] == []
    assert out["unknown_execution_count"] == 0
    assert any(x["status"] == "CANCELLED" for x in out["execution"]["statuses"])
    # The standalone HG fixture does not impose this shared-capital reserve.
    # This test preserves rather than silently removes the execution difference.
