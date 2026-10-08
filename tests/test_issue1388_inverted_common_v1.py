"""Artificial integration only; no archive loading or economic activation.

The already authenticated real census is deliberately not replayed. The
integration fixture replaces that one evidence check, but independently tests
that arbitrary rehashed substitute proofs cannot satisfy its fixed identity.
"""
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from ops import issue1388_alpha_screen_v1 as common
from ops import issue1388_inverted_execution_v1 as lifecycle
from ops.issue1388_inverted_hammer_v1 import HOUR_MS as H, inverted_hammer_flags

_spec = importlib.util.spec_from_file_location(
    "ih_source_fixture_helpers", Path(__file__).with_name("test_issue1388_inverted_hammer_v1.py"))
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)


def artificial_market(kind="closed"):
    # Reuse the existing strict source-real body/gap/trend fixture. Every
    # funding timestamp in the frozen full development calendar is present.
    frame = _helpers.hammer(_helpers.artificial(190), t=175 if kind == "terminal" else 160)
    offset = common.END_MS - 190 * H if kind == "terminal" else common.START_MS
    for field in ("open_ts_ms", "close_ts_ms", "available_ts_ms"):
        frame[field] += offset
    if kind == "gap":
        frame = frame.drop(index=170).reset_index(drop=True)
    # Boundaries are explicitly supplied, not forward-filled. The long empty
    # interval is unoccupied in the closed fixture; occupied gaps quarantine.
    edge = frame.iloc[[0 if kind == "terminal" else -1]].copy()
    edge["segment_id"] = "BOUNDARY"
    edge["open_ts_ms"] = common.START_MS if kind == "terminal" else common.END_MS - H
    edge["close_ts_ms"] = edge.open_ts_ms + H
    edge["available_ts_ms"] = edge.close_ts_ms
    frame = pd.concat([edge, frame] if kind == "terminal" else [frame, edge], ignore_index=True)
    frame["volume"] = 1.0
    assert inverted_hammer_flags(frame).sum() == 1
    costs = {"BTC-USDT": 14.0, "ETH-USDT": 14.0, "SOL-USDT": 14.019991840065801,
             "XRP-USDT": 15.2464337863639, "LINK-USDT": 15.705017808034006,
             "DOGE-USDT": 16.73064726730116}
    return {"frames": {s: frame.copy(deep=True) for s in common.SYMBOLS}, "costs": costs,
            "six_funding": {s: [{"symbol": s, "fundingTime": t, "fundingRate": "0.0001",
                                  "markPrice": "100"}
                                 for t in range(common.START_MS, common.END_MS, 8 * H)]
                            for s in common.SYMBOLS}}


def activation(head="a" * 40):
    profile = common.PROFILES[common.INVERTED_HAMMER_ID]
    base = "research/campaigns/scalp7_20261007/issue1388_internet_alpha_v1/"
    files = {"ops/issue1388_alpha_screen_v1.py", "ops/issue1388_inverted_hammer_v1.py",
             "ops/issue1388_inverted_execution_v1.py", "ops/issue1388_inverted_audit_v1.py",
             "ops/issue1388_bband_rsi_v1.py", base + "INVERTED_EXECUTION_CONTRACT.json",
             base + "INVERTED_HAMMER_PRE_SCREEN_THESIS.json",
             base + "INVERTED_HAMMER_SOURCE_ATTRIBUTION.json", base + "TA_LIB_LICENSE.txt"}
    files.update(base + s.split("-")[0] + "_FUNDING_" + k + ".json"
                 for s in common.SYMBOLS for k in ("RAW", "RECEIPT"))
    return {"schema": "zel.issue1388.alpha_screen_activation.v1", "issue": 1388,
            "candidate_id": common.INVERTED_HAMMER_ID, "token": profile["activation_token"],
            "reviewed_source_sha": head, **common.source_binding(profile),
            "source_inventory_sha256": common.SOURCE_INVENTORY_SHA256,
            "cost_sha256": common.COST_SHA256, "period_ms": [common.START_MS, common.END_MS],
            "timeframe_min": 60, "global_heavy_group": common.GLOBAL_HEAVY_GROUP,
            "order_authority": "BLOCKED", "promotion": False,
            "funding_hashes": common.six_funding_hashes(),
            "execution_contract_sha256": common.INVERTED_CONTRACT_SHA256,
            "source_files_sha256": {n: common.file_sha256(common.ROOT / n) for n in files}}


def environment(monkeypatch):
    monkeypatch.setattr(common, "current_head", lambda: "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("ISSUE1388_GLOBAL_HEAVY_GROUP", common.GLOBAL_HEAVY_GROUP)


def rehash(value):
    value["result_sha256"] = common.digest({k: v for k, v in value.items() if k != "result_sha256"})
    return value


def test_actual_source_flags_six_ledgers_one_model_and_two_cost_summaries(monkeypatch):
    market = artificial_market()
    calls = []
    original = lifecycle.replay_inverted_hammer
    def count(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)
    monkeypatch.setattr(lifecycle, "replay_inverted_hammer", count)
    value = common.screen(market, common.PROFILES[common.INVERTED_HAMMER_ID])
    assert calls == list(common.SYMBOLS)  # 2x is accounting, never a second model.
    assert value["cost_1x"]["T"] == value["cost_2x"]["T"] == 6
    assert value["disposition"] == "REJECT_ECONOMIC_EARLY"
    assert value["cost_1x"] == common.summarize(value["trades"], 1)
    assert value["cost_2x"] == common.summarize(value["trades"], 2)
    assert value["source_replication"] is False
    assert value["paper_same_close_return_reproduced"] is False
    assert value["full_consumed"] == 0 and value["exchange_order_submitted"] is False
    for row in value["trades"]:
        assert row["cost_bps"] == market["costs"][row["symbol"]]
        assert row["exit_ts_ms"] - row["entry_ts_ms"] == 24 * H
        assert row["entry_ts_ms"] >= row["signal_available_ts_ms"]
    common.audit_inverted_result(value, market)


@pytest.mark.parametrize("kind,disposition", [
    ("gap", "BLOCKED_INPUT_GAP_WITH_OPEN_STATE"),
    ("terminal", "BLOCKED_TERMINAL_OUTCOME_UNRESOLVED")])
def test_gap_and_terminal_are_saved_as_unresolved_not_forced_profitable_close(kind, disposition):
    market = artificial_market(kind)
    value = common.screen(market, common.PROFILES[common.INVERTED_HAMMER_ID])
    assert value["disposition"] == disposition
    assert value["trades"] == [] and value["census"]["unresolved_end"] == 6
    assert value["census"]["missing_fill_evidence"] == (6 if kind == "gap" else 0)
    for accounting in value["symbol_accounting"].values():
        assert len(accounting["orders"]) == 1
        assert accounting["open_entry_cost_bps"] > 0
        assert accounting["account_nav"] is None
    common.audit_inverted_result(value, market)


@pytest.mark.parametrize("mutation", ["missing_symbol", "missing_timestamp", "wrong_symbol", "boolean_rate"])
def test_all_funding_rejected_before_any_source_signal(monkeypatch, mutation):
    market = artificial_market()
    symbol = common.SYMBOLS[-1]
    if mutation == "missing_symbol": del market["six_funding"][symbol]
    elif mutation == "missing_timestamp": market["six_funding"][symbol].pop()
    elif mutation == "wrong_symbol": market["six_funding"][symbol][0]["symbol"] = "INVALID"
    else: market["six_funding"][symbol][0]["fundingRate"] = True
    monkeypatch.setattr("ops.issue1388_inverted_hammer_v1.inverted_hammer_flags",
                        lambda *a: pytest.fail("source signal computed before all funding validation"))
    with pytest.raises(common.ScreenError):
        common.screen(market, common.PROFILES[common.INVERTED_HAMMER_ID])


@pytest.mark.parametrize("mutation", ["source", "cost", "gross", "funding", "identity", "clock", "summary"])
def test_coherent_outer_rehash_and_summary_recompute_do_not_hide_tampering(mutation):
    market = artificial_market()
    value = common.screen(market, common.PROFILES[common.INVERTED_HAMMER_ID])
    if mutation == "source": value["source_sha256"] = "0" * 64
    elif mutation == "summary": value["cost_1x"]["Net_bps"] += 100
    else:
        key = {"cost": "cost_bps", "gross": "gross_bps", "funding": "funding_bps",
               "identity": "entry_identity", "clock": "exit_ts_ms"}[mutation]
        # Alter both the flattened ledger and the matching symbol ledger,
        # preserving their equality and their recalculated outer summaries.
        symbol = value["trades"][0]["symbol"]
        for row in (value["trades"][0], value["symbol_accounting"][symbol]["trades"][0]):
            row[key] = "forged" if mutation == "identity" else row[key] + 1
        value["cost_1x"] = common.summarize(value["trades"], 1)
        value["cost_2x"] = common.summarize(value["trades"], 2)
    rehash(value)
    with pytest.raises((common.ScreenError, ValueError)):
        common.audit_inverted_result(value, market)


@pytest.mark.parametrize("field,value", [
    ("classification", "FRESH_OOS_QUALIFIED"),
    ("paper_same_close_return_reproduced", True),
    ("funding_actual_account_debit_certified", True),
    ("mark_account_NAV", 1000000.0),
    ("density_result_sha256", "0" * 64),
    ("sample_limitation", "ADEQUATE_DENSITY_CERTIFIED")])
def test_coherent_outer_rehash_cannot_promote_semantic_claims(field, value):
    market = artificial_market()
    result = common.screen(market, common.PROFILES[common.INVERTED_HAMMER_ID])
    result[field] = value
    rehash(result)
    with pytest.raises(common.ScreenError, match="SAVED_SOURCE_COST_CONTRACT_BINDING"):
        common.audit_inverted_result(result, market)


@pytest.mark.parametrize("proof", [None, {}, {"result_sha256": "cb43af27cfaae2783c1ddc37cce4a26ea8aab63ba524c39c78eafb582c6bb223"}])
def test_missing_or_forged_pinned_census_is_rejected(proof):
    value = activation()
    value["density_preflight"] = proof
    with pytest.raises(common.ScreenError, match="PREFLIGHT_PINNED_HASH"):
        common.validate_inverted_preflight(value, {})


def test_new_proof_outer_rehash_cannot_replace_completed_fixed_census():
    proof = {"economic_screen_consumed": 0, "order_authority": "BLOCKED",
             "candidates": {common.INVERTED_HAMMER_ID: {"pinned_translation_events": 43}}}
    proof["result_sha256"] = common.digest(proof)
    with pytest.raises(common.ScreenError, match="PREFLIGHT_PINNED_HASH"):
        common.validate_inverted_preflight({**activation(), "density_preflight": proof}, {})


def test_input_preflight_claim_model_result_save_independent_audit_then_persist(monkeypatch, tmp_path):
    market, sequence = artificial_market(), []
    environment(monkeypatch)
    path = tmp_path / "activation.json"
    path.write_text(json.dumps(activation()))
    def load(*args): sequence.append("input"); return market
    def preflight(*args): sequence.append("preflight")  # Only artificial input cannot match real census.
    original_screen, original_audit = common.screen, common.audit_inverted_result
    def model(*args): sequence.append("model"); return original_screen(*args)
    def audit(value, inputs):
        assert (tmp_path / "output/RESULT.json").exists()
        sequence.append("audit-after-result-save")
        original_audit(value, inputs)
    def record(ref, name, value, parent):
        if name == "STARTED.json":
            assert sequence == ["input", "preflight"]
            assert value["state"] == "STARTED_AFTER_INPUT_VALIDATION_BEFORE_SIGNAL_COMPUTE"
            sequence.append("start-claim")
        else:
            assert sequence == ["input", "preflight", "start-claim", "model", "audit-after-result-save"]
            sequence.append("persistent-result")
        return "b" * 40
    monkeypatch.setattr(common, "load_market", load)
    monkeypatch.setattr(common, "validate_inverted_preflight", preflight)
    monkeypatch.setattr(common, "screen", model)
    monkeypatch.setattr(common, "audit_inverted_result", audit)
    monkeypatch.setattr(common, "create_record", record)
    result = common.execute(Path("/ARTIFICIAL_ONLY"), path, tmp_path / "output")
    assert result["state"] == "COMPLETE_PERSISTED_AND_AUDITED"
    assert result["economic_table"]["1x"]["T"] == 6
    assert sequence[-1] == "persistent-result"
    assert (tmp_path / "output/PERSISTED.json").exists()
    assert all((tmp_path / "output" / (s.split("-")[0] + "_FUNDING_" + k + ".json")).exists()
               for s in common.SYMBOLS for k in ("RAW", "RECEIPT"))
    with pytest.raises(common.ScreenError, match="OUTPUT_DIRECTORY_ALREADY_EXISTS"):
        common.execute(Path("/ARTIFICIAL_ONLY"), path, tmp_path / "output")


@pytest.mark.parametrize("mutation", ["closure", "contract", "source", "preflight"])
def test_activation_failure_never_claims_or_computes(monkeypatch, tmp_path, mutation):
    environment(monkeypatch)
    value = activation()
    if mutation == "closure": value["source_files_sha256"].pop("ops/issue1388_inverted_audit_v1.py")
    elif mutation == "contract": value["source_files_sha256"]["research/campaigns/scalp7_20261007/issue1388_internet_alpha_v1/INVERTED_EXECUTION_CONTRACT.json"] = "0" * 64
    elif mutation == "source": value["source_sha256"] = "0" * 64
    else: value["density_preflight"] = {}
    path = tmp_path / "activation.json"; path.write_text(json.dumps(value))
    monkeypatch.setattr(common, "load_market", lambda *a: artificial_market())
    monkeypatch.setattr(common, "create_record", lambda *a: pytest.fail("must not claim"))
    monkeypatch.setattr(common, "screen", lambda *a: pytest.fail("must not calculate"))
    with pytest.raises(common.ScreenError):
        common.execute(Path("/ARTIFICIAL_ONLY"), path, tmp_path / "output")


@pytest.mark.parametrize("mutation", ["missing_symbol", "missing_timestamp", "invalid_rate"])
def test_loaded_funding_is_revalidated_before_permanent_start(monkeypatch, tmp_path, mutation):
    environment(monkeypatch)
    market = artificial_market()
    symbol = common.SYMBOLS[-1]
    if mutation == "missing_symbol": del market["six_funding"][symbol]
    elif mutation == "missing_timestamp": market["six_funding"][symbol].pop()
    else: market["six_funding"][symbol][0]["fundingRate"] = True
    path = tmp_path / "activation.json"; path.write_text(json.dumps(activation()))
    # Input loading is the integration boundary; no source indicators or
    # lifecycle are replaced. Its incomplete output must not consume a start.
    monkeypatch.setattr(common, "load_market", lambda *a: market)
    monkeypatch.setattr(common, "validate_inverted_preflight", lambda *a: None)
    monkeypatch.setattr(common, "create_record", lambda *a: pytest.fail("invalid funding consumed permanent start"))
    monkeypatch.setattr(common, "screen", lambda *a: pytest.fail("invalid funding reached model"))
    with pytest.raises(common.ScreenError):
        common.execute(Path("/ARTIFICIAL_ONLY"), path, tmp_path / "output")
