from __future__ import annotations

import json
from pathlib import Path

from backend.production import zel_production_bingx_ws_microstructure_v2 as m


def policy():
    return json.loads(Path('config/zel_production_bingx_ws_microstructure_v2.json').read_text())


def test_frozen_policy_is_research_only_and_stream_separated():
    cfg=m.validate_policy(policy())
    assert cfg['streams']=={
        'depth':'{symbol}@depth20@200ms',
        'trade':'{symbol}@trade',
        'kline':'{symbol}@kline_1m',
    }
    assert cfg['economic_signal_enabled'] is False
    assert cfg['selection_authority'] is False
    assert cfg['promotion_authority'] is False
    assert cfg['execution_authority']=='NONE'
    assert cfg['order_authority']=='BLOCKED'
    assert cfg['live_trade_authority']=='BLOCKED'
    assert cfg['exchange_order_submitted'] is False


def test_collector_builds_channels_per_stream_without_mixing():
    c=m.Collector(policy())
    assert c._channels('depth')==['BTC-USDT@depth20@200ms','ETH-USDT@depth20@200ms']
    assert c._channels('trade')==['BTC-USDT@trade','ETH-USDT@trade']
    assert c._channels('kline')==['BTC-USDT@kline_1m','ETH-USDT@kline_1m']
    assert set(c.stream_state)=={'depth','trade','kline'}


def test_heartbeat_requires_all_three_streams_seen(monkeypatch):
    c=m.Collector(policy())
    monkeypatch.setattr(m, '_sha', lambda _: 'SHA')
    h=c.heartbeat()
    assert h['state']=='HOLD_BINGX_WS_MICROSTRUCTURE_V2_CONNECTING'
    for name in ('depth','trade','kline'):
        c.stream_state[name]['messages']=1
        c.stream_state[name]['last_message_ms']=h['updated_at_ms']
    h2=c.heartbeat()
    assert h2['state']=='PASS_BINGX_WS_MICROSTRUCTURE_V2_ACCUMULATING'
    assert h2['economic_signal_enabled'] is False
    assert h2['execution_authority']=='NONE'
    assert h2['order_authority']=='BLOCKED'


def test_authority_drift_fails_closed():
    for key,value in [('economic_signal_enabled',True),('selection_authority',True),('order_authority','OPEN')]:
        cfg=policy(); cfg[key]=value
        try:m.validate_policy(cfg)
        except RuntimeError:pass
        else:raise AssertionError(f'{key} must fail closed')
