from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_campaign_v2 as campaign


def test_catalog_exact21_unique_current15m30m_identities() -> None:
    rows = campaign.candidates()
    identities = {row["identity"] for row in rows}
    assert len(rows) == len(identities) == 21
    assert {row["tf"] for row in rows} == {15, 30}
    assert sum(row["kind"] == "architecture_child" for row in rows) == 3
    assert sum(row["kind"] == "material_round1" for row in rows) == 4
    assert sum(row["kind"] == "material_control" for row in rows) == 4
    assert all(row["parent"] in identities for row in rows)
    assert not any(
        "broad30" in row["identity"] or "active5" in row["identity"] for row in rows
    )
    assert not any("micro" in row["identity"] for row in rows)


def test_frozen_file_write_is_idempotent_but_never_overwrites(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    campaign.write_json(path, {"a": 1})
    before = path.read_bytes()
    campaign.write_json(path, {"a": 1})
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="IMMUTABLE_ARTIFACT_CONFLICT"):
        campaign.write_json(path, {"a": 2})


def frozen_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    report = tmp_path / "report"
    report.mkdir()
    code = tmp_path / "code.py"
    code.write_text("pass\n")
    data = tmp_path / "data.json"
    data.write_text("{}\n")
    cost = tmp_path / "cost.json"
    cost.write_text("{}\n")
    contract = {
        "code_hashes": {"code.py": campaign.sha(code)},
        "data_hashes": {"data.json": campaign.sha(data)},
        "cost_sha256": campaign.sha(cost),
        "candidates": campaign.candidates(),
        "cost_path": "cost.json",
        "scope_key": campaign.SCOPE,
        "raw_history_start_ms": campaign.START,
        "raw_history_end_ms": campaign.END,
    }
    campaign.write_json(report / "CAMPAIGN_PREREGISTERED_V2.json", contract)
    monkeypatch.setattr(campaign, "ROOT", tmp_path)
    monkeypatch.setattr(campaign, "REPORT", report)
    monkeypatch.setattr(campaign, "COST_PATH", cost)
    return contract


def test_freeze_rejects_changed_code_without_running_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen_files(tmp_path, monkeypatch)
    (tmp_path / "code.py").write_text("changed\n")
    with pytest.raises(ValueError, match="FROZEN_SOURCE_CHANGED"):
        campaign.verify_freeze()


def test_freeze_rejects_changed_data_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen_files(tmp_path, monkeypatch)
    (tmp_path / "data.json").write_text('{"changed":true}')
    with pytest.raises(ValueError, match="FROZEN_SOURCE_CHANGED"):
        campaign.verify_freeze()


def test_freeze_rejects_changed_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen_files(tmp_path, monkeypatch)
    (tmp_path / "cost.json").write_text('{"cost":999}')
    with pytest.raises(ValueError, match="FROZEN_COST_CHANGED"):
        campaign.verify_freeze()


@pytest.mark.parametrize(
    "module_name",
    [
        "scalp7_positive_lanes_v2",
        "scalp7_parent_controls_v2",
        "scalp7_mr_formation_v2",
        "scalp7_materials_program_v2",
        "scalp7_rider_architecture_v2",
    ],
)
def test_signal_adapter_only_generates_requested_identity(
    module_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def generate(frames: Any, **kwargs: Any) -> list[dict[str, Any]]:
        calls.append((frames, kwargs))
        return [{"identity": "frozen_test"}]

    monkeypatch.setattr(
        campaign, "module", lambda name: SimpleNamespace(generate_signals=generate)
    )
    frames = {"BTC-USDT": pd.DataFrame()}
    costs = {"BTC-USDT": 14.0}
    result = campaign._signals(
        {"identity": "frozen_test", "module": module_name}, frames, costs
    )
    assert result == [{"identity": "frozen_test"}]
    assert len(calls) == 1 and calls[0][0] is frames
    options = calls[0][1]
    if module_name == "scalp7_positive_lanes_v2":
        assert options == {"costs": costs, "identities": ("frozen_test",)}
    elif module_name == "scalp7_rider_architecture_v2":
        assert options == {}
    else:
        assert options == {"identity": "frozen_test"}


def test_verify_saved_rejects_tampered_ledger_without_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = frozen_files(tmp_path, monkeypatch)
    contract["candidates"] = [{"identity": "synthetic"}]
    monkeypatch.setattr(campaign, "verify_freeze", lambda: contract)
    ledger = tmp_path / "ledger.gz"
    ledger.write_bytes(b"original")
    report: dict[str, Any] = {
        "freeze_sha256": campaign.sha(
            campaign.REPORT / "CAMPAIGN_PREREGISTERED_V2.json"
        ),
        "rows": {
            "synthetic": {
                "ledger_path": "ledger.gz",
                "ledger_sha256": campaign.sha(ledger),
            }
        },
    }
    (campaign.REPORT / "CAMPAIGN_RESULTS_V2.json").write_text(json.dumps(report))
    campaign.write_json(
        campaign.REPORT / "results" / "synthetic.json", report["rows"]["synthetic"]
    )
    ledger.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="LEDGER_HASH_MISMATCH"):
        campaign.verify_saved()


def cached_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Path]:
    source = campaign.module("scalp7_source_data_v2")
    inventory = {"synthetic_raw.json": "a" * 64}
    witness = {"test_only": "synthetic_time_witness"}
    monkeypatch.setattr(source, "verify_time_witness", lambda path: witness)
    monkeypatch.setattr(source, "_inventory", lambda root, manifest: inventory)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("CACHE_HIT_MUST_NOT_RELOAD_OR_REPLAY_RAW_HISTORY")

    monkeypatch.setattr(source, "_load_verified_minutes", forbidden)
    key_data = {
        "source_inventory": inventory,
        "time_witness": witness,
        "code_sha256": source.sha_file(Path(source.__file__)),
        "timeframe_minutes": 15,
    }
    key = hashlib.sha256(source.json_bytes(key_data)).hexdigest()
    cache = tmp_path / "cache" / key
    cache.mkdir(parents=True)
    outputs = {}
    for symbol in source.SYMBOLS:
        frame = pd.DataFrame(
            {
                "open_ts_ms": [0],
                "close_ts_ms": [900_000],
                "available_ts_ms": [900_000],
                "open": [100.0],
                "high": [102.0],
                "low": [98.0],
                "close": [101.0],
                "segment_id": [0],
            }
        )
        raw = gzip.compress(frame.to_csv(index=False).encode(), mtime=0)
        (cache / (symbol + ".csv.gz")).write_bytes(raw)
        outputs[symbol] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "attrs": {"timeframe_minutes": 15, "test_only": True},
        }
    (cache / "RECEIPT.json").write_bytes(
        source.json_bytes({"key": key, "outputs": outputs})
    )
    return source, cache


def test_source_cache_hash_verified_without_raw_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, cache = cached_source(tmp_path, monkeypatch)
    frames = source.load_candles(tmp_path / "raw", 15, cache_dir=cache.parent)
    assert set(frames) == set(source.SYMBOLS)
    assert all(
        len(frame) == 1 and frame.attrs["test_only"] for frame in frames.values()
    )


def test_source_cache_corruption_rejected_without_regeneration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, cache = cached_source(tmp_path, monkeypatch)
    (cache / "BTC-USDT.csv.gz").write_bytes(b"tampered")
    with pytest.raises(source.SourceDataError):
        source.load_candles(tmp_path / "raw", 15, cache_dir=cache.parent)


def test_source_expected_inventory_mismatch_rejected_before_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, cache = cached_source(tmp_path, monkeypatch)
    with pytest.raises(source.SourceDataError, match="INVENTORY_MISMATCH"):
        source.load_candles(
            tmp_path / "raw",
            15,
            cache_dir=cache.parent,
            expected_source_hashes={"synthetic_raw.json": "b" * 64},
        )


def mock_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    day = 86_400_000
    spec = {
        "identity": "synthetic_test",
        "module": "synthetic_provider",
        "tf": 15,
        "lane": "synthetic",
        "parent": "synthetic_parent",
        "kind": "synthetic_mock",
    }
    windows = [
        {
            "label": "validation",
            "partition": "validation",
            "start_ms": 0,
            "end_ms": day,
        },
        {
            "label": "rolling_1",
            "partition": "rolling",
            "start_ms": day,
            "end_ms": 2 * day,
        },
    ]
    contract = {
        "candidates": [spec],
        "code_hashes": {"backend/research/rebuild/synthetic_provider.py": "a" * 64},
        "data_hashes": {},
        "cost_sha256": "b" * 64,
        "windows": windows,
        "rolling_interpretation": "SYNTHETIC_MOCK_ONLY",
    }
    report = tmp_path / "report"
    runtime = tmp_path / "runtime"
    cost = tmp_path / "cost.json"
    cost.write_text(json.dumps({"costs_bps": {"BTC-USDT": 10.0}}))
    campaign.write_json(report / "CAMPAIGN_PREREGISTERED_V2.json", contract)
    for name, value in (
        ("ROOT", tmp_path),
        ("REPORT", report),
        ("RUNTIME", runtime),
        ("COST_PATH", cost),
        ("END", 2 * day),
    ):
        monkeypatch.setattr(campaign, name, value)
    monkeypatch.setattr(campaign, "verify_freeze", lambda: contract)
    bars = pd.DataFrame(
        {
            "open_ts_ms": [-900_000, 0, day - 900_000, day, 2 * day - 900_000, 2 * day],
            "close_ts_ms": [0, 900_000, day, day + 900_000, 2 * day, 2 * day + 900_000],
        }
    )
    bars["segment_id"] = 0
    for tf in (15, 30):
        campaign.write_json(
            tmp_path
            / "research/campaigns/scalp7_20260915"
            / f"SOURCE_DATA_V2_{tf}M.json",
            {"symbols": {"BTC-USDT": {"bars": len(bars), "segments": 1, "attrs": {}}}},
        )
    calls: list[dict[str, Any]] = []

    def replay(signals: Any, frames: Any, **kwargs: Any) -> Any:
        raise AssertionError("POSITIONAL_COST_EXPECTED")

    def replay_mock(
        signals: Any, frames: Any, costs: Any, **kwargs: Any
    ) -> dict[str, Any]:
        call = {"signals": signals, "frames": frames, "kwargs": kwargs}
        calls.append(call)
        end = int(frames["BTC-USDT"]["close_ts_ms"].max())
        trades = (
            [
                {
                    "identity": "synthetic_test",
                    "lane": "synthetic",
                    "symbol": "BTC-USDT",
                    "side": 1,
                    "signal_ts_ms": int(signals[0]["signal_ts_ms"]),
                    "entry_ts_ms": int(signals[0]["signal_ts_ms"]),
                    "exit_ts_ms": end,
                    "outcome_available_ts_ms": end,
                    "gross_bps": 15.0,
                    "cost_bps": 10.0,
                    "net_bps": 5.0,
                }
            ]
            if signals
            else []
        )
        return {
            "trades": trades,
            "unresolved": [],
            "signal_count": len(signals),
            "rejections": {},
        }

    actual_module = campaign.module
    signals = [
        {"identity": "synthetic_test", "symbol": "BTC-USDT", "signal_ts_ms": value}
        for value in (-1, 0, day, 2 * day)
    ]
    mocks = {
        "scalp7_execution_v2": SimpleNamespace(replay=replay_mock),
        "scalp7_source_data_v2": SimpleNamespace(
            load_candles=lambda *args, **kwargs: {"BTC-USDT": bars.copy()}
        ),
        "scalp7_rolling_context_v2": SimpleNamespace(
            cross_features=lambda frames: pd.DataFrame(),
            bind_context=lambda frames, features, windows: (frames, []),
        ),
        "synthetic_provider": SimpleNamespace(
            generate_signals=lambda frames: signals, exit_update=lambda *args: {}
        ),
    }
    monkeypatch.setattr(
        campaign,
        "module",
        lambda name: mocks[name] if name in mocks else actual_module(name),
    )
    return contract, calls


def test_mock_campaign_exact_window_ends_excluded_and_completed_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, calls = mock_run(tmp_path, monkeypatch)
    report = campaign.run()
    evidence = report["rows"]["synthetic_test"]
    assert [receipt["cost1x"]["T"] for receipt in evidence["window_receipts"]] == [0, 0]
    assert evidence["rolling1x"]["T"] == 0
    assert evidence["rolling2x"]["T"] == 0
    assert len(calls) == 2
    assert [call["signals"][0]["signal_ts_ms"] for call in calls] == [0, 86_400_000]
    assert all(
        int(call["frames"]["BTC-USDT"]["close_ts_ms"].max()) <= end
        for call, end in zip(calls, (86_400_000, 2 * 86_400_000))
    )
    campaign.run()
    assert len(calls) == 2


def test_mock_campaign_completed_receipt_tamper_does_not_trigger_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, calls = mock_run(tmp_path, monkeypatch)
    campaign.run()
    path = campaign.REPORT / "results" / "synthetic_test.json"
    value = json.loads(path.read_text())
    value["fresh_T"] = 999
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="SAVED_EVIDENCE_HASH_MISMATCH"):
        campaign.run()
    assert len(calls) == 2


def test_mock_campaign_running_claim_never_reexecutes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract, calls = mock_run(tmp_path, monkeypatch)
    registry = campaign.module("economic7_campaign_registry_v1")
    campaign.RUNTIME.mkdir(parents=True)
    ledger = registry.CampaignLedger(campaign.RUNTIME / "campaign.sqlite3")
    ledger.create_scope(campaign.SCOPE, campaign.OWNER, 1, 1, contract)
    spec = contract["candidates"][0]
    claim = registry.CandidateIdentity(
        candidate_id=spec["identity"],
        strategy_id=spec["lane"],
        baseline_id=spec["parent"],
        changed_axis=spec["kind"] + ":" + spec["identity"],
        rule_sha256=campaign.digest(
            {"code": contract["code_hashes"], "identity": spec}
        ),
        data_sha256=campaign.digest(contract["data_hashes"]),
        cost_sha256=contract["cost_sha256"],
        window_sha256=campaign.digest(contract["windows"]),
    )
    ledger.reserve(campaign.SCOPE, campaign.OWNER, claim)
    ledger.start(claim.key, campaign.OWNER)
    with pytest.raises(ValueError, match="NO_AUTOMATIC_RERUN"):
        campaign.run()
    assert calls == []


def test_mock_campaign_loaded_cache_must_match_frozen_source_attributes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, calls = mock_run(tmp_path, monkeypatch)
    path = tmp_path / "research/campaigns/scalp7_20260915/SOURCE_DATA_V2_15M.json"
    value = json.loads(path.read_text())
    value["symbols"]["BTC-USDT"]["attrs"] = {"time_witness": "different"}
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="SOURCE_ATTRIBUTE_BINDING_DRIFT"):
        campaign.run()
    assert calls == []
