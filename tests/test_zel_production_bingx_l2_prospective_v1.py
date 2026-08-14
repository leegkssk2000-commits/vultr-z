from __future__ import annotations

import json
from pathlib import Path

from backend.production import zel_production_bingx_l2_prospective_v1 as m


def policy(tmp_path: Path):
    return {
        "schema_version": m.POLICY_SCHEMA,
        "state": "FROZEN_PAPER_PROSPECTIVE_HISTORY_ONLY",
        "mode": "PAPER",
        "role": "PROSPECTIVE_PUBLIC_MARKET_HISTORY_COLLECTOR_NOT_STRATEGY",
        "base_url": "https://open-api.bingx.com",
        "symbols": ["BTC-USDT", "ETH-USDT"],
        "kline_interval": "15m",
        "depth_limit": 20,
        "bucket_ms": 900000,
        "request_pause_ms": 0,
        "history_path": str(tmp_path / "history.jsonl"),
        "summary_path": str(tmp_path / "summary.json"),
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


def fake_fetch(url: str):
    if "/klines?" in url:
        return {
            "code": 0,
            "msg": "",
            "data": [
                {"time": 1000, "open": "100", "high": "102", "low": "99", "close": "101", "volume": "10"},
                {"time": 2000, "open": "101", "high": "103", "low": "100", "close": "102", "volume": "12"},
            ],
        }
    if "/depth?" in url:
        bids = [[str(101.9 - i * 0.1), str(2 + i)] for i in range(20)]
        asks = [[str(102.1 + i * 0.1), str(3 + i)] for i in range(20)]
        return {"code": 0, "msg": "", "data": {"bids": bids, "asks": asks, "T": 2100}}
    raise AssertionError(url)


def test_capture_is_raw_prospective_context_not_signal(tmp_path):
    rows = m.capture_snapshot(policy(tmp_path), fetcher=fake_fetch, sleep_fn=lambda _: None, now_ms=1_800_123)
    assert len(rows) == 2
    row = rows[0]
    assert row["capture_bucket_ms"] == 1_800_000
    assert row["symbol"] == "BTC-USDT"
    assert row["economic_signal_enabled"] is False
    assert row["history_gate_decision"] == "UNSET_BY_COLLECTOR"
    assert row["selection_authority"] is False
    assert row["promotion_authority"] is False
    assert row["execution_authority"] == "NONE"
    assert row["order_authority"] == "BLOCKED"
    assert row["live_trade_authority"] == "BLOCKED"
    assert row["exchange_order_submitted"] is False
    assert row["klines"][-1]["close"] == 102.0
    assert len(row["l2"]["bids"]) == 20
    assert len(row["l2"]["asks"]) == 20
    assert -1.0 <= row["l2"]["qty_imbalance_top20"] <= 1.0
    assert row["l2"]["spread_bps"] > 0


def test_append_is_bucket_deduplicated_and_summary_has_no_ready_decision(tmp_path):
    cfg = policy(tmp_path)
    rows = m.capture_snapshot(cfg, fetcher=fake_fetch, sleep_fn=lambda _: None, now_ms=1_800_123)
    first = m.append_rows(cfg, rows)
    second = m.append_rows(cfg, rows)
    assert first["appended_count"] == 2
    assert first["total_observation_count"] == 2
    assert first["observation_count_by_symbol"] == {"BTC-USDT": 1, "ETH-USDT": 1}
    assert second["appended_count"] == 0
    assert second["total_observation_count"] == 2
    assert second["history_gate_decision"] == "UNSET_BY_COLLECTOR"
    assert second["economic_signal_enabled"] is False
    assert len(Path(cfg["history_path"]).read_text().splitlines()) == 2
    persisted = json.loads(Path(cfg["summary_path"]).read_text())
    assert persisted["state"] == "PASS_BINGX_L2_PROSPECTIVE_HISTORY_ACCUMULATING"


def test_authority_or_signal_drift_fails_closed(tmp_path):
    for key, value in (("selection_authority", True), ("economic_signal_enabled", True), ("history_gate_decision", "PASS")):
        bad = policy(tmp_path)
        bad[key] = value
        try:
            m.validate_policy(bad)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"{key} drift must fail closed")


def test_frozen_policy_matches_contract():
    cfg = json.loads(Path("config/zel_production_bingx_l2_prospective_v1.json").read_text())
    assert m.validate_policy(cfg)["bucket_ms"] == 900000
    assert cfg["request_pause_ms"] >= 1000
    assert cfg["history_gate_decision"] == "UNSET_BY_COLLECTOR"
    assert cfg["economic_signal_enabled"] is False
