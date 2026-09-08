"""Frozen rules, full-prefix features, aligned FT view and fatal QA assertions.

No core engine/strategy decision changes, orders, source requests or retries.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import importlib.metadata
from pathlib import Path
import sys
from unittest.mock import patch
HERE = Path(__file__).resolve().parent
FROZEN = HERE.parent / 'D2_HLHB_FREQTRADE_2026_7_V1'
if not (FROZEN/'D2Independent.py').is_file():
    raise RuntimeError('FROZEN_BENCHMARK_NOT_FOUND')
sys.path.insert(0, str(FROZEN))
import offline_engine as ft
from D2Independent import D2Independent
BAR = 14_400_000

class FatalBenchmarkBoundary(BaseException):
    """Deliberately not swallowed by FT's ordinary Exception handler."""

def ensure_entry_calendar(current_time, start_ms, end_ms):
    stamp = int(current_time.timestamp()*1000)
    if not start_ms <= stamp < end_ms:
        raise FatalBenchmarkBoundary('ENTRY_OUTSIDE_APPROVED_PERIOD:'+str(stamp))

def entry_time(args, kwargs):
    return kwargs['current_time'] if 'current_time' in kwargs else args[5]

class GuardedD2(D2Independent):
    """Same decisions; terminate the attempt on impossible callback state."""
    def confirm_trade_entry(self, *args, **kwargs):
        ensure_entry_calendar(entry_time(args,kwargs),self._start,self._end)
        return super().confirm_trade_entry(*args,**kwargs)
    def order_filled(self,*args,**kwargs):
        try:
            return super().order_filled(*args,**kwargs)
        except Exception as exc:
            raise FatalBenchmarkBoundary('D2_ORDER_FILLED:'+str(exc)) from exc
    def custom_exit(self,*args,**kwargs):
        try:
            return super().custom_exit(*args,**kwargs)
        except Exception as exc:
            raise FatalBenchmarkBoundary('D2_CUSTOM_EXIT:'+str(exc)) from exc

def strategy(kind):
    if kind=='D2': return GuardedD2
    if kind!='HLHB': raise ValueError('UNKNOWN_FROZEN_STRATEGY')
    original=ft.external_class(FROZEN/'hlhb.py')
    class GuardedHLHB(original):
        """Unchanged source parameters plus a non-economic calendar assertion."""
        def confirm_trade_entry(self,*args,**kwargs):
            ensure_entry_calendar(entry_time(args,kwargs),int(self.config['zel_start_ms']),int(self.config['zel_end_ms']))
            return super().confirm_trade_entry(*args,**kwargs)
    return GuardedHLHB

def aligned_view(processed,start_ms,end_ms,required_startup):
    if required_startup<0 or end_ms<=start_ms:
        raise ValueError('INVALID_CALENDAR_OR_STARTUP')
    cutoff_ms=start_ms-(int(required_startup)+1)*BAR
    cutoff=datetime.fromtimestamp(cutoff_ms/1000,timezone.utc)
    end=datetime.fromtimestamp(end_ms/1000,timezone.utc)
    result={}
    for pair,frame in processed.items():
        if frame.empty or frame['date'].dt.tz is None:
            raise ValueError('EMPTY_OR_NAIVE_FRAME:'+pair)
        times=[int(x.timestamp()*1000) for x in frame['date']]
        if any(b-a!=BAR for a,b in zip(times,times[1:])):
            raise ValueError('NONCONTIGUOUS_ENGINE_VIEW:'+pair)
        if times[-1]+BAR!=end_ms:
            raise ValueError('FROZEN_END_MISMATCH:'+pair)
        view=frame.loc[(frame['date']>=cutoff)&(frame['date']<end)].copy()
        # Never reset the original zel_index or recompute bounded indicators.
        if len(view)<=required_startup+1:
            raise ValueError('ALIGNED_VIEW_INSUFFICIENT_BARS:'+pair)
        if int(view['date'].iloc[0].timestamp()*1000)!=max(times[0],cutoff_ms):
            raise ValueError('ENGINE_CACHE_CUTOFF_MISMATCH:'+pair)
        result[pair]=view
    return result

def installed_core_identity():
    import freqtrade,json
    if importlib.metadata.version('freqtrade')!='2026.7':
        raise RuntimeError('ENGINE_VERSION_DRIFT')
    root=Path(freqtrade.__file__).resolve().parent
    expected=json.loads((FROZEN/'environment/ENGINE_CORE_SOURCE_SHA256.json').read_bytes())
    actual={}
    for name,spec in expected.items():
        actual[name]=hashlib.sha256((root/name).read_bytes()).hexdigest()
        if actual[name]!=spec['sha256']:
            raise RuntimeError('INSTALLED_FT_CORE_DRIFT:'+name)
    return actual

def run_frame(kind,frames,start_ms,end_ms,workdir):
    before=installed_core_identity()
    original=ft.Backtesting.backtest
    view_records={}
    def invoke(backtester,processed,start_date,end_date):
        view=aligned_view(processed,start_ms,end_ms,backtester.required_startup)
        for pair,frame in view.items():
            view_records[pair]={'rows':len(frame),'first_open_ms':int(frame['date'].iloc[0].timestamp()*1000),
                'original_first_index':None if 'zel_index' not in frame else int(frame['zel_index'].iloc[0]),
                'startup':backtester.required_startup,'indicator_prefix_rows':len(processed[pair])}
        return original(backtester,view,start_date,end_date)
    # Serial call-boundary wrapper only; installed matching source stays intact.
    with patch.object(ft.Backtesting,'backtest',invoke):
        value=ft.run_frame(strategy(kind),frames,start_ms,end_ms,workdir)
    if installed_core_identity()!=before:
        raise RuntimeError('FT_CORE_CHANGED_DURING_RUN')
    raw=value[0]['results'].to_dict('records')
    for row in raw: ensure_entry_calendar(row['open_date'],start_ms,end_ms)
    audit=value[2]
    if audit and (audit['callback_errors'] or len(audit['entries'])!=len(raw)):
        raise FatalBenchmarkBoundary('CALLBACK_OR_ENTRY_COUNT_MISMATCH')
    return value,view_records
