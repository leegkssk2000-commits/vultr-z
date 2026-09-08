"""Actual Freqtrade engine, offline analytical market metadata; no exchange IO."""
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
import socket
import pandas as pd
import numpy as np
from freqtrade.strategy import IStrategy
from freqtrade.enums import RunMode, TradingMode, MarginMode, CandleType
from freqtrade.exchange import Exchange
from freqtrade.optimize.backtesting import Backtesting
from freqtrade.resolvers import StrategyResolver
BAR=14_400_000

def bounded_ema(values,n):
    a=2/(n+1);out=[]
    for i in range(len(values)):
        part=values[max(0,i-4*n+1):i+1];v=float(part[0])
        for x in part[1:]:v=a*float(x)+(1-a)*v
        out.append(v)
    return np.array(out)

class BreakV2Port(IStrategy):
    INTERFACE_VERSION=3
    timeframe='4h';startup_candle_count=0
    minimal_roi={};stoploss=-0.999999
    trailing_stop=False;process_only_new_candles=True
    use_exit_signal=True;exit_profit_only=False
    def populate_indicators(self,df,metadata):
        df['ema20']=bounded_ema(df.close.to_numpy(),20)
        df['ema50']=bounded_ema(df.close.to_numpy(),50)
        df['highest50']=df.high.rolling(50).max()
        df['volratio']=df.volume/df.volume.rolling(20).mean()
        df['raw_signal']=((df.close>df.highest50.shift(1))&(df.ema20>df.ema50)&(df.volratio>=1.1)&(np.arange(len(df))>=239))
        return df
    def populate_entry_trend(self,df,metadata):
        df['enter_long']=df.raw_signal.astype(int);return df
    def populate_exit_trend(self,df,metadata):
        df['exit_long']=0;return df
    def custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs):
        if (current_time-trade.open_date_utc).total_seconds()>=86400:return 'H6_NEXT_OPEN'
        return None

class SmokeStrategy(BreakV2Port):
    def populate_indicators(self,df,metadata):
        df['raw_signal']=np.arange(len(df))==2;return df

def blocked(*args,**kwargs):raise RuntimeError('BENCHMARK_MARKET_NETWORK_FORBIDDEN')

def run_frame(strategy_class,frames,start_ms,end_ms,workdir,history_start=None):
    workdir=Path(workdir);workdir.mkdir(parents=True,exist_ok=True)
    config={'dry_run':True,'dry_run_wallet':1000000000.0,'tradable_balance_ratio':1.0,
      'stake_currency':'USDT','stake_amount':1000.0,'max_open_trades':len(frames),
      'timeframe':'4h','trading_mode':TradingMode.SPOT,'margin_mode':MarginMode.NONE,
      'runmode':RunMode.BACKTEST,'candle_type_def':CandleType.SPOT,'fee':0.0005,
      'exchange':{'name':'bingx','pair_whitelist':list(frames),'pair_blacklist':[],
                  'key':'','secret':'','enable_ws':False},
      'pairlists':[{'method':'StaticPairList','allow_inactive':True}],
      'entry_pricing':{'price_side':'other','use_order_book':False},
      'exit_pricing':{'price_side':'other','use_order_book':False},
      'order_types':{'entry':'market','exit':'market','stoploss':'market','stoploss_on_exchange':False},
      'order_time_in_force':{'entry':'GTC','exit':'GTC'},
      'unfilledtimeout':{'entry':10,'exit':10,'unit':'minutes'},
      'datadir':workdir/'data','user_data_dir':workdir,'strategy':strategy_class.__name__,
      'timerange':f'{(start_ms-BAR)//1000}-{end_ms//1000}',
      'export':'none','enable_protections':False,'position_stacking':False,
      'verified_history_start':history_start or {}}
    config['datadir'].mkdir(exist_ok=True)
    with patch.object(socket.socket,'connect',blocked),patch('socket.create_connection',blocked):
        ex=Exchange(config,validate=False,load_leverage_tiers=False)
        markets={p:{'id':p.replace('/','-'),'symbol':p,'base':p.split('/')[0],
          'quote':'USDT','active':True,'spot':True,'swap':False,'future':False,
          'type':'spot','contract':False,'linear':False,'inverse':False,
          'taker':.0005,'maker':.0005,'precision':{'amount':1e-12,'price':1e-12},
          'limits':{'amount':{'min':1e-12,'max':None},'price':{'min':None,'max':None},'cost':{'min':0,'max':None}}} for p in frames}
        ex._markets=markets;ex._api.set_markets(markets);ex._api_async.set_markets(markets)
        # Replace only class discovery, NOT official attribute/hyperparam loading.
        def resolve(strategy_name,config,extra_dir=None):
            return StrategyResolver.validate_strategy(strategy_class(config))
        try:
            with patch.object(StrategyResolver,'_load_strategy',side_effect=resolve):bt=Backtesting(config,exchange=ex)
            strat=bt.strategylist[0];bt._set_strategy(strat)
            if hasattr(strat,'buy_indicator_shift'):
                assert strat.buy_indicator_shift.value==15 and strat.buy_crossed_indicator_shift.value==9
            processed=strat.advise_all_indicators({p:df.copy() for p,df in frames.items()})
            signals={p:strat.advise_entry(df.copy(),{'pair':p}) for p,df in processed.items()}
            engine_start=max(start_ms-BAR,min(int(df.date.iloc[0].timestamp()*1000) for df in frames.values()))
            output=bt.backtest(processed,datetime.fromtimestamp(engine_start/1000,timezone.utc),datetime.fromtimestamp((end_ms-BAR)/1000,timezone.utc))
            output['resolved_parameters']={'minimal_roi':strat.minimal_roi,'stoploss':strat.stoploss,
              'buy':getattr(strat,'buy_params',None),'max_open_trades':strat.max_open_trades}
            return output,signals
        finally:
            Backtesting.cleanup();ex.close()

if __name__=='__main__':
    df=pd.DataFrame({'date':pd.date_range('2025-01-01',periods=30,freq='4h',tz='UTC'),
      'open':np.linspace(100,129,30),'high':np.linspace(102,131,30),
      'low':np.linspace(99,128,30),'close':np.linspace(101,130,30),'volume':1000.})
    a=int(df.date.iloc[0].timestamp()*1000);b=int(df.date.iloc[-1].timestamp()*1000)+BAR
    result,_=run_frame(SmokeStrategy,{'BTC/USDT':df},a,b,'/tmp/zel-benchmark-smoke')
    rr=result['results'];print(rr.to_json(orient='records',date_format='iso'))
    assert len(rr)==1 and rr.iloc[0].exit_reason=='H6_NEXT_OPEN'
    assert rr.iloc[0].open_rate==103 and rr.iloc[0].close_rate==109
    assert (rr.iloc[0].close_date-rr.iloc[0].open_date).total_seconds()==86400
    print('SYNTHETIC_FREQTRADE_OFFLINE_SMOKE_PASS; actual_market_evaluations=0')
