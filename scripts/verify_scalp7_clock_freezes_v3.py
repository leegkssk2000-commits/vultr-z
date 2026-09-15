"""Saved-only verification of the separately frozen V3 source-clock continuation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "research/campaigns/scalp7_20260915/broad_rebuild_v2"
CODE = ROOT / "backend/research/rebuild"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    return json.loads((REPORT / name).read_bytes())


def main():
    source = read("FRESH_SOURCE_CLOCK_REPAIR_PREREG_V3.json")
    config = read("OBSERVED_PAPER_CONFIG_V3.json")
    paper = read("OBSERVED_PAPER_FREEZE_V3.json")
    micro = read("MICRO_CLOCK_PRODUCER_FREEZE_V3.json")
    common = read("FRESH_COMMON_CONTINUATION_PREREG_V3.json")
    spec = read("OBSERVED_PAPER_CLOCK_TECHNICAL_SPEC_V3.json")
    for pin in source["code_pins"] + config["code_pins"]:
        path = Path(pin["path"])
        assert path.parent.name == "rebuild"
        assert sha(CODE / path.name) == pin["sha256"], path.name
    for name, expected in micro["code_sha256"].items():
        assert Path(name).name == name and sha(CODE / name) == expected, name
    preserved = spec["preserved_runtime"]
    assert sha(ROOT / preserved["path"]) == preserved["sha256"]
    assert paper["config_sha256"] == sha(REPORT / "OBSERVED_PAPER_CONFIG_V3.json")
    assert common["config_sha256"] == paper["config_sha256"]
    assert common["paper_freeze_sha256"] == sha(
        REPORT / "OBSERVED_PAPER_FREEZE_V3.json"
    )
    assert common["source_prereg_sha256"] == sha(
        REPORT / "FRESH_SOURCE_CLOCK_REPAIR_PREREG_V3.json"
    )
    assert config["fresh_config"]["sha256"] == sha(
        REPORT / "FRESH_FORWARD_CONFIG_V2.json"
    )
    names = {
        "FRESH_FORWARD": "FRESH_FORWARD_RUNTIME_FREEZE_EXACT_V2.json",
        "MICRO": "MICRO_CLOCK_PRODUCER_FREEZE_V3.json",
    }
    for item in config["signal_sources"]:
        assert item["freeze"]["sha256"] == sha(REPORT / names[item["kind"]])
    assert (
        common["common_economic_start_ms"]
        == config["fresh_start_ms"]
        == paper["fresh_start_ms"]
    )
    assert paper["initialized_at_ms"] < paper["fresh_start_ms"]
    assert common["frozen_at_ms"] < paper["fresh_start_ms"]
    for item in (source, config, paper, micro, common):
        assert item["order_authority"] == item["live_authority"] == "BLOCKED"
    assert source["historical_replays"] == common["historical_economic_replays"] == 0
    assert paper["promotion_authority"] is micro["historical_replay"] is False
    witness = read("FRESH_CLOCK_RUNTIME_WITNESS_V3.json")
    audit = REPORT / "fresh_clock_v3_witness"
    assert (
        sha(audit / "PAPER_STATE_AT_FIRST_REVIEW.json") == witness["paper_state_sha256"]
    )
    state = json.loads((audit / "PAPER_STATE_AT_FIRST_REVIEW.json").read_bytes())
    assert len(state["trades"]) == witness["paper_status"]["fresh_closed_trades"]
    assert len(state["positions"]) == witness["observed_open_positions"]
    for position in state["positions"].values():
        assert position["entry_ts_ms"] >= common["common_economic_start_ms"]
        for quote in position["entry_quote_receipts"].values():
            assert quote["requested_at_ms"] > position["signal"]["available_ts_ms"]
            assert position["entry_ts_ms"] >= quote["usable_at_ms"]
            assert quote["usable_at_ms"] >= max(
                quote["received_at_ms"], quote["source_ts_ms"] or 0
            )
            prefix = quote["quote_id"][:12]
            receipt_path = audit / (prefix + "." + Path(quote["receipt_path"]).name)
            clock_path = audit / (prefix + "." + Path(quote["clock_proof_path"]).name)
            assert sha(receipt_path) == quote["receipt_sha256"]
            assert sha(clock_path) == quote["clock_proof_sha256"]
            assert sha(audit / (prefix + ".body")) == quote["body_sha256"]
            assert (
                json.loads(clock_path.read_bytes())["clock_proof"]
                == quote["clock_proof"]
            )
    assert witness["order_authority"] == witness["live_authority"] == "BLOCKED"
    presentation = json.loads(
        (
            REPORT / "anatomy_binding_repair/readable/PRESENTATION_MANIFEST_V3.json"
        ).read_bytes()
    )
    for item in presentation["files"]:
        base = REPORT / "anatomy_binding_repair"
        assert sha(base / item["source"]) == item["source_sha256"]
        assert sha(base / item["presentation"]) == item["presentation_sha256"]
    print(
        json.dumps(
            {
                "state": "PASS_SEPARATE_V3_CLOCK_FREEZES",
                "common_start_ms": paper["fresh_start_ms"],
                "original_v2_preserved": True,
                "presentation_copies": len(presentation["files"]),
                "economic_replays": 0,
                "order_authority": "BLOCKED",
            }
        )
    )


if __name__ == "__main__":
    main()
