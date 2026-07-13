from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RESOLVER_PATH = Path(__file__).resolve().parents[1] / "tools/q4r3_exact5_symbol_ssot_resolver.py"
WRITER_PATH = Path(__file__).resolve().parents[1] / "tools/q4r3_exact25_persistent_single_event_writer.py"
ADAPTER_PATH = Path(__file__).resolve().parents[1] / "tools/q4r3_exact25_single_event_measurement_adapter.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


resolver = load_module("resolver", RESOLVER_PATH)
writer = load_module("writer", WRITER_PATH)
adapter = load_module("adapter", ADAPTER_PATH)


def owner_manifest() -> dict:
    rows = []
    for index in range(25):
        rows.append({
            "strategy_id": f"strategy_{index:02d}",
            "owner_sha256": f"{index + 1:064x}",
        })
    return {"strategies": rows}


def close_row(event_id: str, *, symbol: str = "BTCUSDT", entry_ts: str = "2026-07-13T15:00:00+00:00") -> dict:
    return {
        "event_id": event_id,
        "position_id": event_id.removesuffix(":close"),
        "strategy_id": "strategy_00",
        "owner_sha256": f"{1:064x}",
        "symbol": symbol,
        "side": "long",
        "entry_ts": entry_ts,
        "exit_ts": "2026-07-13T15:10:00+00:00",
        "captured_at": "2026-07-13T15:10:01+00:00",
        "source": "q4r3_exact25_dedicated_shadow_producer",
        "epoch_id": "EXACT25_EDGE_V1",
        "measurement_namespace": "EXACT25_EDGE_V1",
        "mode": "shadow",
        "shadow": True,
        "status": "CLOSED",
        "closed": True,
        "initial_risk_usdt": 1.0,
        "realized_pnl_usdt": 1.8,
        "realized_R": 1.8,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
    }


def test_exact5_resolver_prefers_unique_ssot(tmp_path: Path) -> None:
    config = tmp_path / "backend" / "config"
    config.mkdir(parents=True)
    path = config / "EXACT5_SYMBOL_UNIVERSE_SSOT.json"
    path.write_text(json.dumps({
        "exact5_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
    }), encoding="utf-8")
    result = resolver.resolve(tmp_path)
    assert result["resolved"] is True
    assert result["symbols"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
    assert result["source_path"] == str(path)


def test_exact5_resolver_blocks_ambiguous_sets(tmp_path: Path) -> None:
    config = tmp_path / "backend" / "config"
    config.mkdir(parents=True)
    (config / "symbols_a.json").write_text(json.dumps({
        "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
    }), encoding="utf-8")
    (config / "symbols_b.json").write_text(json.dumps({
        "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT"]
    }), encoding="utf-8")
    result = resolver.resolve(tmp_path)
    assert result["resolved"] is False


def test_process_once_accepts_only_post_gate_exact5_event(tmp_path: Path) -> None:
    surface = tmp_path / "close_latest.json"
    ledger = tmp_path / "ledger.jsonl"
    surface.write_text(json.dumps({
        "rows": [
            close_row("old:close", entry_ts="2026-07-13T14:00:00+00:00"),
            close_row("new:close"),
        ]
    }), encoding="utf-8")
    owners = adapter.manifest_owner_map(owner_manifest())
    observed: set[str] = set()
    result = writer.process_once(
        adapter=adapter,
        close_surface=surface,
        owners=owners,
        ledger=ledger,
        allowed_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"),
        start_epoch=adapter.parse_time("2026-07-13T14:30:00+00:00"),
        observed_ids=observed,
    )
    assert result["accepted"] == 1
    assert result["skipped_prestart"] == 1
    assert adapter.count_valid_rows(ledger) == 1


def test_process_once_skips_non_universe_symbol(tmp_path: Path) -> None:
    surface = tmp_path / "close_latest.json"
    ledger = tmp_path / "ledger.jsonl"
    surface.write_text(json.dumps({"rows": [close_row("ada:close", symbol="ADAUSDT")]}), encoding="utf-8")
    owners = adapter.manifest_owner_map(owner_manifest())
    result = writer.process_once(
        adapter=adapter,
        close_surface=surface,
        owners=owners,
        ledger=ledger,
        allowed_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"),
        start_epoch=adapter.parse_time("2026-07-13T14:30:00+00:00"),
        observed_ids=set(),
    )
    assert result["accepted"] == 0
    assert result["skipped_symbol"] == 1
    assert adapter.count_valid_rows(ledger) == 0


def test_gate_requires_exact5_core4_superset(tmp_path: Path) -> None:
    gate = tmp_path / "gate.json"
    gate.write_text(json.dumps({
        "start_epoch": 1_700_000_000.0,
        "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "BNBUSDT"],
    }), encoding="utf-8")
    try:
        writer.gate_payload(gate)
    except RuntimeError as exc:
        assert "CORE4_MISSING:XRPUSDT" in str(exc)
    else:
        raise AssertionError("gate should have failed")
