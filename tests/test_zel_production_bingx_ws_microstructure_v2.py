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


def test_actual_runtime_payload_shapes_normalize_into_aggregator():
    c=m.Collector(policy())
    depth={'dataType':'BTC-USDT@depth20@200ms','data':{'bids':[['62598.8','1.0']]*20,'asks':[['62598.9','1.5']]*20}}
    trade={'dataType':'BTC-USDT@trade','data':[{'T':1786719506323,'m':False,'p':'62598.9','q':'0.0002','s':'BTC-USDT'}]}
    kline={'dataType':'BTC-USDT@kline_1m','data':[{'T':1786719480000,'c':'62598.9','h':'62598.9','l':'62594.4','o':'62594.4','v':'3.1902'}]}
    for stream,msg,now in [('depth',depth,1786719475000),('trade',trade,1786719476000),('kline',kline,1786719477000)]:
        normalized=c._normalize_messages(stream,msg,now)
        assert normalized
        for item in normalized:
            c.agg.consume(item,now)
    assert c.agg.totals['depth_messages_total']==1
    assert c.agg.totals['trade_messages_total']==1
    assert c.agg.totals['kline_messages_total']==1
    assert c.agg.totals['parse_errors_total']==0


def test_kline_runtime_list_shape_maps_close_boundary_without_future_event_bucket():
    c=m.Collector(policy())
    msg={'dataType':'BTC-USDT@kline_1m','data':[{'T':1786719480000,'c':'62598.9','h':'62598.9','l':'62594.4','o':'62594.4','v':'3.1902'}]}
    item=c._normalize_messages('kline',msg,1786719476123)[0]
    assert 'T' not in item['data']
    assert item['data']['K']['T']==1786719480000
    assert item['data']['K']['t']==1786719420000


def test_heartbeat_requires_received_and_normalized_all_three_streams(monkeypatch):
    c=m.Collector(policy())
    monkeypatch.setattr(m, '_sha', lambda _: 'SHA')
    h=c.heartbeat()
    assert h['state']=='HOLD_BINGX_WS_MICROSTRUCTURE_V2_CONNECTING'
    for name in ('depth','trade','kline'):
        c.stream_state[name]['messages']=1
        c.stream_state[name]['normalized_messages']=1
        c.stream_state[name]['last_message_ms']=h['updated_at_ms']
    c.agg.totals['depth_messages_total']=1
    c.agg.totals['trade_messages_total']=1
    c.agg.totals['kline_messages_total']=1
    h2=c.heartbeat()
    assert h2['state']=='PASS_BINGX_WS_MICROSTRUCTURE_V2_ACCUMULATING'
    assert h2['economic_signal_enabled'] is False
    assert h2['execution_authority']=='NONE'
    assert h2['order_authority']=='BLOCKED'


def test_malformed_runtime_payload_fails_closed():
    c=m.Collector(policy())
    for stream,msg in [
        ('trade',{'dataType':'BTC-USDT@trade','data':{'T':1}}),
        ('kline',{'dataType':'BTC-USDT@kline_1m','data':[{'T':1,'o':'1'}]}),
    ]:
        try:c._normalize_messages(stream,msg,1)
        except RuntimeError:pass
        else:raise AssertionError(f'{stream} malformed payload must fail closed')


def test_authority_drift_fails_closed():
    for key,value in [('economic_signal_enabled',True),('selection_authority',True),('order_authority','OPEN')]:
        cfg=policy(); cfg[key]=value
        try:m.validate_policy(cfg)
        except RuntimeError:pass
        else:raise AssertionError(f'{key} must fail closed')
