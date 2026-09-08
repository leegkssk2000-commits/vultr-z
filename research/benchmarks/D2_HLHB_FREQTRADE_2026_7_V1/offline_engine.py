"""Unmodified FT 2026.7 backtester with network-free analytical market metadata.

SPOT engine matching of existing BingX perpetual prices is an offline price-path
comparison, never certification of BingX futures/live/funding/liquidation.
Only Exchange metadata and strategy class discovery are supplied externally.
"""
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
import importlib.util
import hashlib
import socket
import pandas as pd
from freqtrade.enums import RunMode, TradingMode, MarginMode, CandleType
from freqtrade.exchange import Exchange
from freqtrade.optimize.backtesting import Backtesting
from freqtrade.resolvers import StrategyResolver

BAR=14_400_000

def blocked(*args, **kwargs):
    raise RuntimeError('BENCHMARK_NETWORK_FORBIDDEN')

def external_class(path):
    path=Path(path); raw=path.read_bytes()
    if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!='5164cda889e37759d86252f02e7d9a3bfc648fb1':
        raise RuntimeError('HLHB_SOURCE_DRIFT')
    spec=importlib.util.spec_from_file_location('unchanged_hlhb',path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod.hlhb

def frame(rows):
    return pd.DataFrame({'date':pd.to_datetime([r['bar_open_ts'] for r in rows],unit='ms',utc=True),
                        **{k:[r[k] for r in rows] for k in ('open','high','low','close','volume')}})

def run_frame(strategy_class, frames, start_ms, end_ms, workdir):
    workdir=Path(workdir);workdir.mkdir(parents=True,exist_ok=True)
    config={'dry_run':True,'dry_run_wallet':1_000_000_000.0,'tradable_balance_ratio':1.0,
      'stake_currency':'USDT','stake_amount':1000.0,'max_open_trades':len(frames),
      'timeframe':'4h','trading_mode':TradingMode.SPOT,'margin_mode':MarginMode.NONE,
      'runmode':RunMode.BACKTEST,'candle_type_def':CandleType.SPOT,'fee':0.0005,
      'exchange':{'name':'bingx','pair_whitelist':list(frames),'pair_blacklist':[],
                  'key':'','secret':'','enable_ws':False},
      'pairlists':[{'method':'StaticPairList','allow_inactive':True}],
      'entry_pricing':{'price_side':'other','use_order_book':False},
      'exit_pricing':{'price_side':'other','use_order_book':False},
      'unfilledtimeout':{'entry':10,'exit':10,'unit':'minutes'},
      'datadir':workdir/'data','user_data_dir':workdir,'strategy':strategy_class.__name__,
      'timerange':f'{(start_ms-BAR)//1000}-{end_ms//1000}',
      'export':'none','enable_protections':False,'position_stacking':False,
      'zel_start_ms':start_ms,'zel_end_ms':end_ms}
    config['datadir'].mkdir(exist_ok=True)
    with patch.object(socket.socket,'connect',blocked),patch('socket.create_connection',blocked):
        ex=Exchange(config,validate=False,load_leverage_tiers=False)
        markets={p:{'id':p.replace('/','-'),'symbol':p,'base':p.split('/')[0],
          'quote':'USDT','active':True,'spot':True,'swap':False,'future':False,
          'type':'spot','contract':False,'linear':False,'inverse':False,
          'taker':.0005,'maker':.0005,'precision':{'amount':1e-12,'price':1e-12},
          'limits':{'amount':{'min':1e-12,'max':None},'price':{'min':None,'max':None},'cost':{'min':0,'max':None}}} for p in frames}
        ex._markets=markets;ex._api.set_markets(markets);ex._api_async.set_markets(markets)
        def resolve(strategy_name, config, extra_dir=None):
            return StrategyResolver.validate_strategy(strategy_class(config))
        try:
            with patch.object(StrategyResolver,'_load_strategy',side_effect=resolve):
                bt=Backtesting(config,exchange=ex)
            strat=bt.strategylist[0];bt._set_strategy(strat)
            processed=strat.advise_all_indicators({p:df.copy() for p,df in frames.items()})
            signals={p:strat.advise_entry(df.copy(),{'pair':p}) for p,df in processed.items()}
            engine_start=max(start_ms-BAR,min(int(df.date.iloc[0].timestamp()*1000) for df in frames.values()))
            result=bt.backtest(processed,datetime.fromtimestamp(engine_start/1000,timezone.utc),
                               datetime.fromtimestamp((end_ms-BAR)/1000,timezone.utc))
            fields=['timeframe','startup_candle_count','minimal_roi','stoploss','trailing_stop',
              'trailing_stop_positive','trailing_stop_positive_offset','trailing_only_offset_is_reached',
              'use_exit_signal','exit_profit_only','ignore_roi_if_entry_signal','order_types',
              'order_time_in_force','max_open_trades','position_adjustment_enable','can_short']
            resolved={k:getattr(strat,k,None) for k in fields}
            resolved.update(engine_position_stacking=bt._position_stacking,
               source_position_stacking=getattr(strat,'position_stacking',None),
               engine_required_startup=bt.required_startup)
            return result,signals,getattr(strat,'audit',None),resolved,config,markets
        finally:
            Backtesting.cleanup();ex.close()
