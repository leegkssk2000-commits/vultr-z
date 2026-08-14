from __future__ import annotations

import json
from pathlib import Path

from backend.production import zel_production_a1_jump_liquidity_history_gate_v1 as m


def policy():
    return json.loads(Path('config/zel_production_a1_jump_liquidity_history_gate_v1.json').read_text())


def template():
    return json.loads(Path('config/zel_production_a1_jump_liquidity_source_template_v1.json').read_text())


def row(symbol: str, bucket: int, *, trade=1, kline=1):
    return {
        'schema_version': m.ROW_SCHEMA,
        'symbol': symbol,
        'bucket_start_ms': bucket,
        'bucket_end_ms': bucket + 5000,
        'depth_messages': 20,
        'trade_messages': trade,
        'kline_messages': kline,
        'execution_authority': 'NONE',
        'order_authority': 'BLOCKED',
        'live_trade_authority': 'BLOCKED',
        'exchange_order_submitted': False,
    }


def heartbeat(now: int):
    return {
        'schema_version': policy()['collector_heartbeat_schema'],
        'updated_at_ms': now,
        'parse_errors_total': 0,
        'source_sha256': 'SRC',
        'policy_sha256': 'POL',
        'streams': {
            'depth': {'messages': 10, 'normalized_messages': 10},
            'trade': {'messages': 10, 'normalized_messages': 10},
            'kline': {'messages': 10, 'normalized_messages': 10},
        },
        'depth_messages_total': 10,
        'trade_messages_total': 10,
        'kline_messages_total': 10,
        'execution_authority': 'NONE',
        'order_authority': 'BLOCKED',
        'live_trade_authority': 'BLOCKED',
        'exchange_order_submitted': False,
    }


def make_rows(elapsed_ms: int):
    out=[]
    for symbol in ['BTC-USDT','ETH-USDT']:
        for b in range(0, elapsed_ms, 5000):
            out.append(row(symbol,b+100_000))
    return out


def test_policy_binds_v2_collector_and_history():
    cfg=m.validate_policy(policy())
    assert cfg['history_path'].endswith('production_bingx_ws_microstructure_v2.jsonl')
    assert cfg['heartbeat_path'].endswith('production_bingx_ws_microstructure_heartbeat_v2.json')
    assert cfg['collector_source_path'].endswith('zel_production_bingx_ws_microstructure_v2.py')
    assert cfg['collector_policy_path'].endswith('zel_production_bingx_ws_microstructure_v2.json')
    assert cfg['collector_heartbeat_schema']=='zel.production_bingx_ws_microstructure_heartbeat.v2'


def test_accumulating_before_runtime_window():
    now=1_000_000
    receipt=m.evaluate(policy(),template(),heartbeat(now),make_rows(600_000),now_ms=now,runtime_source_sha256='SRC',runtime_policy_sha256='POL')
    assert receipt['state']=='HOLD_A1_JUMP_SOURCE_HISTORY_ACCUMULATING'
    assert receipt['template_ready'] is True
    assert receipt['source_ready'] is False
    assert receipt['economic_replay_allowed'] is False


def test_runtime_and_calibration_stages_do_not_enable_economic_replay():
    for elapsed, expected in ((900_000,'PASS_A1_JUMP_RUNTIME_SOURCE_READY'),(21_600_000,'PASS_A1_JUMP_CALIBRATION_SOURCE_READY')):
        last=100_000+elapsed
        receipt=m.evaluate(policy(),template(),heartbeat(last),make_rows(elapsed),now_ms=last,runtime_source_sha256='SRC',runtime_policy_sha256='POL')
        assert receipt['state']==expected
        assert receipt['source_ready'] is True
        assert receipt['economic_replay_allowed'] is False
        assert receipt['execution_authority']=='NONE'
        assert receipt['order_authority']=='BLOCKED'


def test_missing_trade_or_kline_rows_stays_accumulating():
    rows=[]
    elapsed=900_000
    for symbol in ['BTC-USDT','ETH-USDT']:
        for b in range(0,elapsed,5000): rows.append(row(symbol,b+100_000,trade=0,kline=0))
    last=100_000+elapsed
    receipt=m.evaluate(policy(),template(),heartbeat(last),rows,now_ms=last,runtime_source_sha256='SRC',runtime_policy_sha256='POL')
    assert receipt['state']=='HOLD_A1_JUMP_SOURCE_HISTORY_ACCUMULATING'
    assert receipt['source_ready'] is False


def test_heartbeat_unormalized_stream_is_integrity_hold():
    hb=heartbeat(1_000_000)
    hb['streams']['trade']['normalized_messages']=0
    receipt=m.evaluate(policy(),template(),hb,make_rows(900_000),now_ms=1_000_000,runtime_source_sha256='SRC',runtime_policy_sha256='POL')
    assert receipt['state']=='HOLD_A1_JUMP_SOURCE_INTEGRITY'
    assert any('HEARTBEAT_STREAM_NOT_NORMALIZED:trade' in x for x in receipt['integrity_defects'])


def test_duplicate_or_sha_drift_is_integrity_hold():
    rows=make_rows(900_000)
    rows.append(dict(rows[0]))
    now=1_000_000
    receipt=m.evaluate(policy(),template(),heartbeat(now),rows,now_ms=now,runtime_source_sha256='OTHER',runtime_policy_sha256='POL')
    assert receipt['state']=='HOLD_A1_JUMP_SOURCE_INTEGRITY'
    assert receipt['integrity_defects']
    assert receipt['source_ready'] is False


def test_template_has_exact_three_sources_and_no_signal_thresholds():
    t=m.validate_template(template())
    assert set(t['sources'])=={'l2_order_book','volume','ohlcv'}
    assert t['numeric_signal_thresholds_frozen'] is False
    assert t['economic_signal_enabled'] is False
