from __future__ import annotations

import json
from pathlib import Path

from backend.production import zel_production_bingx_ws_microstructure_v1 as m


def policy(tmp_path: Path):
    return {
        "schema_version": m.POLICY_SCHEMA,
        "state": "FROZEN_PAPER_PROSPECTIVE_MICROSTRUCTURE_ONLY",
        "mode": "PAPER",
        "role": "PROSPECTIVE_PUBLIC_MICROSTRUCTURE_HISTORY_COLLECTOR_NOT_STRATEGY",
        "websocket_url": "wss://open-api-swap.bingx.com/swap-market",
        "symbols": ["BTC-USDT", "ETH-USDT"],
        "depth_level": 20,
        "depth_interval": "200ms",
        "kline_interval": "1m",
        "bucket_ms": 5000,
        "heartbeat_interval_ms": 5000,
        "stale_heartbeat_ms": 30000,
        "reconnect_after_sec": 21600,
        "reconnect_backoff_sec": 0,
        "history_path": str(tmp_path / "history.jsonl"),
        "heartbeat_path": str(tmp_path / "heartbeat.json"),
        "log_path": str(tmp_path / "collector.log"),
        "pid_path": str(tmp_path / "collector.pid"),
        "lock_path": str(tmp_path / "collector.lock"),
        "history_gate_decision": "UNSET_BY_COLLECTOR",
        "economic_signal_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_allowed": False,
        "self_modification_allowed": False,
    }


def depth_message(symbol="BTC-USDT", ts=10_001):
    bids = [[str(100 - i * 0.1), str(2 + i)] for i in range(20)]
    asks = [[str(100.2 + i * 0.1), str(3 + i)] for i in range(20)]
    return {"dataType": f"{symbol}@depth20@200ms", "data": {"T": ts, "bids": bids, "asks": asks}}


def test_policy_and_authority_fail_closed(tmp_path):
    cfg = policy(tmp_path)
    assert m.validate_policy(cfg)["depth_interval"] == "200ms"
    for key, value in (("selection_authority", True), ("economic_signal_enabled", True), ("order_authority", "OPEN")):
        bad = dict(cfg)
        bad[key] = value
        try:
            m.validate_policy(bad)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"{key} drift must fail closed")


def test_aggregator_writes_microstructure_without_economic_signal(tmp_path):
    cfg = policy(tmp_path)
    agg = m.Aggregator(cfg)
    agg.consume(depth_message(ts=10_001), 10_001)
    agg.consume({"dataType": "BTC-USDT@trade", "data": {"T": 10_100, "s": "BTC-USDT", "p": "100.1", "q": "0.5", "m": False}}, 10_100)
    agg.consume({"dataType": "BTC-USDT@kline_1m", "data": {"T": 10_200, "s": "BTC-USDT", "K": {"t": 0, "T": 60_000, "o": "99", "h": "101", "l": "98", "c": "100", "v": "123"}}}, 10_200)
    written = agg.flush_ready(Path(cfg["history_path"]), 15_001)
    assert written == 1
    row = json.loads(Path(cfg["history_path"]).read_text().splitlines()[0])
    assert row["schema_version"] == m.ROW_SCHEMA
    assert row["depth_messages"] == 1
    assert row["trade_messages"] == 1
    assert row["kline_messages"] == 1
    assert row["spread_bps_mean"] > 0
    assert -1 <= row["imbalance_top20_mean"] <= 1
    assert row["trade_imbalance"] == 1.0
    assert row["economic_signal_enabled"] is False
    assert row["history_gate_decision"] == "UNSET_BY_COLLECTOR"
    assert row["execution_authority"] == "NONE"
    assert row["order_authority"] == "BLOCKED"


def test_client_frame_is_masked_and_payload_roundtrips():
    payload = b'{"reqType":"sub"}'
    frame = m._client_frame(payload, opcode=1)
    assert frame[0] == 0x81
    assert frame[1] & 0x80
    length = frame[1] & 0x7F
    assert length == len(payload)
    mask = frame[2:6]
    encoded = frame[6:]
    decoded = bytes(byte ^ mask[i % 4] for i, byte in enumerate(encoded))
    assert decoded == payload


def test_frozen_repo_policy_matches_contract():
    cfg = json.loads(Path("config/zel_production_bingx_ws_microstructure_v1.json").read_text())
    validated = m.validate_policy(cfg)
    assert validated["bucket_ms"] == 5000
    assert validated["depth_level"] == 20
    assert validated["depth_interval"] == "200ms"
    assert validated["economic_signal_enabled"] is False
