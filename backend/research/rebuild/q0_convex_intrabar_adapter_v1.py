"""Observed intrabar stop adapter for Q0 Convex Channel Breakout.

Preserves the frozen Q0 signal/entry/state-machine architecture.  The only
purpose of this module is to replace the old completed-4h stop-timestamp upper
bound with a causally observed BingX 1m first-cross witness for FUTURE rows.
No historical repair, signal retune, source selection or economic adoption.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence
import hashlib
import json

from backend.research.rebuild import q0_prospective_engine_v1 as q0

MINUTE_MS = 60_000
BAR_MS = q0.BAR
RULE_ID = 'Q0_CONVEX_CHANNEL_BREAKOUT_V1'
ADAPTER_ID = 'Q0_CONVEX_OBSERVED_1M_STOP_ADAPTER_V1'


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False,default=str).encode()).hexdigest()


def normalize_minute_rows(rows: Sequence[Mapping[str,Any]], bar_open_ts: int, bar_close_ts: int) -> list[dict[str,Any]]:
    out=[]
    for raw in rows:
        ts=int(raw.get('bar_open_ts',raw.get('ts_ms',-1)))
        close=int(raw.get('bar_close_ts',ts+MINUTE_MS))
        if ts < bar_open_ts or close > bar_close_ts: continue
        row=dict(bar_open_ts=ts,bar_close_ts=close,open=float(raw['open']),high=float(raw['high']),low=float(raw['low']),close=float(raw['close']),volume=float(raw.get('volume',0.0)))
        if close-ts!=MINUTE_MS or ts%MINUTE_MS: raise RuntimeError('Q0_1M_CLOCK_INVALID')
        if row['low']>min(row['open'],row['close'],row['high']) or row['high']<max(row['open'],row['close'],row['low']): raise RuntimeError('Q0_1M_OHLC_INVALID')
        out.append(row)
    out.sort(key=lambda x:x['bar_open_ts'])
    if len(out)!=BAR_MS//MINUTE_MS: raise RuntimeError('Q0_1M_STOP_BAR_INCOMPLETE')
    for i,row in enumerate(out):
        if row['bar_open_ts']!=bar_open_ts+i*MINUTE_MS: raise RuntimeError('Q0_1M_STOP_BAR_GAP_DUPLICATE')
    return out


def first_cross(minutes: Sequence[Mapping[str,Any]], stop: float) -> tuple[int,dict[str,Any]]:
    for i,row in enumerate(minutes):
        if float(row['low'])<=stop:
            return i,dict(row)
    raise RuntimeError('Q0_4H_LOW_STOP_WITHOUT_1M_CROSS')


def _path_extrema(entry_price: float, prior_4h: Sequence[Mapping[str,Any]], minutes: Sequence[Mapping[str,Any]], cross_index: int, fill_price: float) -> tuple[float,float]:
    highs=[entry_price,fill_price];lows=[entry_price,fill_price]
    highs.extend(float(r['high']) for r in prior_4h);lows.extend(float(r['low']) for r in prior_4h)
    # Every full 1m bar strictly before the first cross is fully pre-exit.
    highs.extend(float(r['high']) for r in minutes[:cross_index]);lows.extend(float(r['low']) for r in minutes[:cross_index])
    # Within the crossing minute, only the observed open and actual stop fill
    # are safe.  Its later high/low may be post-stop and are intentionally not
    # used for MFE/MAE.
    cross=minutes[cross_index];highs.append(float(cross['open']));lows.append(float(cross['open']))
    mfe=(max(highs)/entry_price-1.0)*10000.0
    mae=(min(lows)/entry_price-1.0)*10000.0
    return max(0.0,mfe),min(0.0,mae)


def resolve_trade(raw_trade: Mapping[str,Any], exit_4h_row: Mapping[str,Any], all_4h_rows: Sequence[Mapping[str,Any]], minute_rows: Sequence[Mapping[str,Any]]) -> tuple[dict[str,Any],dict[str,Any]]:
    trade=deepcopy(dict(raw_trade))
    if trade.get('exit_reason')!='PROTECTIVE_STOP_INTRABAR' or trade.get('intrabar_stop_timing_unknown') is not True:
        raise RuntimeError('Q0_INTRABAR_TRADE_REQUIRED')
    stop=float(trade['entry_stop_price']);entry=float(trade['entry_price']);entry_ts=int(trade['entry_ts'])
    bo=int(exit_4h_row['bar_open_ts']);bc=int(exit_4h_row['bar_close_ts'])
    if int(trade['exit_index'])<int(trade['entry_index']) or float(exit_4h_row['low'])>stop or float(exit_4h_row['open'])<=stop:
        raise RuntimeError('Q0_INTRABAR_STOP_SHAPE_INVALID')
    minutes=normalize_minute_rows(minute_rows,bo,bc)
    idx,cross=first_cross(minutes,stop)
    gap=float(cross['open'])<=stop
    fill=float(cross['open']) if gap else stop
    exit_ts=int(cross['bar_open_ts']) if gap else int(cross['bar_close_ts'])
    if not entry_ts <= exit_ts <= bc: raise RuntimeError('Q0_1M_EXIT_CLOCK_INVALID')
    prior=[r for r in all_4h_rows if entry_ts<=int(r['bar_open_ts'])<bo]
    mfe,mae=_path_extrema(entry,prior,minutes,idx,fill)
    old_upper=int(trade['exit_ts'])
    trade.update(
        exit_ts=exit_ts,exit_price=fill,gross_bps=(fill/entry-1.0)*10000.0,hold_ms=exit_ts-entry_ts,
        mfe_bps=mfe,mae_bps=mae,
        exit_timestamp_semantics='OBSERVED_1M_OPEN_GAP' if gap else 'OBSERVED_1M_FIRST_CROSS_BAR_CLOSE_UPPER_BOUND',
        excursion_semantics='COMPLETED_PRE_EXIT_4H_PLUS_FULL_1M_BEFORE_FIRST_CROSS_PLUS_CROSS_OPEN_AND_FILL_ONLY',
        intrabar_stop_timing_unknown=False,intrabar_stop_4h_timing_resolved=True,intrabar_stop_subminute_timing_unknown=not gap,
        intrabar_resolution_ms=0 if gap else MINUTE_MS,original_4h_exit_upper_bound_ts=old_upper,
        intrabar_witness_sha256=stable(minutes),intrabar_first_cross_row_sha256=stable(cross),intrabar_first_cross_bar_open_ts=int(cross['bar_open_ts']),
        intrabar_first_cross_bar_close_ts=int(cross['bar_close_ts']),intrabar_witness_rows_T=len(minutes),intrabar_adapter=ADAPTER_ID)
    witness=dict(
        schema='zel.q0.convex.intrabar_stop_witness.v1',adapter_id=ADAPTER_ID,rule_id=RULE_ID,
        signal_ts=int(trade['signal_ts']),entry_ts=entry_ts,stop=stop,exit_4h_bar_open_ts=bo,exit_4h_bar_close_ts=bc,
        first_cross_index=idx,first_cross=deepcopy(cross),fill_price=fill,resolved_exit_ts=exit_ts,
        timestamp_semantics=trade['exit_timestamp_semantics'],subminute_unknown=trade['intrabar_stop_subminute_timing_unknown'],
        full_stop_bar_1m_rows=deepcopy(minutes),full_stop_bar_1m_rows_sha256=stable(minutes),
        post_stop_1m_HLC_excluded_from_MFE_MAE=True,historical_backfill=False,formal_credit=0)
    witness['witness_sha256']=stable(witness)
    return trade,witness


def repair_new_intrabar_trades(before: Mapping[str,Any], after: Mapping[str,Any], batch_rows: Mapping[str,Mapping[str,Any]], history_by_symbol: Mapping[str,Sequence[Mapping[str,Any]]], minute_rows_by_symbol: Mapping[str,Sequence[Mapping[str,Any]]]) -> tuple[dict[str,Any],list[dict[str,Any]]]:
    result=deepcopy(dict(after));witnesses=[]
    for symbol in result['symbols']:
        prior_n=len(before['by_symbol'][symbol]['trades']);rows=result['by_symbol'][symbol]['trades']
        if len(rows)<prior_n: raise RuntimeError('Q0_TRADE_LEDGER_SHRANK')
        for j in range(prior_n,len(rows)):
            trade=rows[j]
            if trade.get('exit_reason')!='PROTECTIVE_STOP_INTRABAR': continue
            fixed,witness=resolve_trade(trade,batch_rows[symbol],history_by_symbol[symbol],minute_rows_by_symbol.get(symbol,[]))
            rows[j]=fixed;witness['symbol']=symbol;witnesses.append(witness)
            # Keep state trace internally consistent with the corrected raw row.
            for trace in reversed(result['by_symbol'][symbol]['trace']):
                if trace.get('kind')=='PROTECTIVE_STOP_INTRABAR' and trace.get('signal_index')==fixed.get('signal_index'):
                    trace.update(ts=fixed['exit_ts'],price=fixed['exit_price'],intrabar_adapter=ADAPTER_ID,
                                 original_4h_exit_upper_bound_ts=fixed['original_4h_exit_upper_bound_ts'])
                    break
    return result,witnesses


def self_test() -> int:
    bo=1_800_000_000_000-(1_800_000_000_000%BAR_MS);bc=bo+BAR_MS;entry=100.0;stop=95.0
    mins=[]
    for i in range(BAR_MS//MINUTE_MS):
        o=100.0 if i<11 else 96.0
        low=94.0 if i==11 else 96.0
        mins.append(dict(bar_open_ts=bo+i*MINUTE_MS,bar_close_ts=bo+(i+1)*MINUTE_MS,open=o,high=max(o,101.0),low=low,close=96.5,volume=1.0))
    raw=dict(signal_ts=bo-BAR_MS,entry_ts=bo,entry_price=entry,entry_index=10,exit_index=10,exit_ts=bc,exit_price=stop,gross_bps=-500.,hold_ms=BAR_MS,
             mfe_bps=100.,mae_bps=-600.,entry_stop_price=stop,exit_reason='PROTECTIVE_STOP_INTRABAR',intrabar_stop_timing_unknown=True)
    fixed,w=resolve_trade(raw,dict(bar_open_ts=bo,bar_close_ts=bc,open=100.,high=102.,low=94.,close=96.,volume=1.),[],mins)
    assert fixed['exit_ts']==bo+12*MINUTE_MS and fixed['exit_price']==stop
    assert fixed['intrabar_stop_timing_unknown'] is False and fixed['intrabar_stop_subminute_timing_unknown'] is True
    assert abs(fixed['mae_bps']+500.0)<1e-9 and w['post_stop_1m_HLC_excluded_from_MFE_MAE'] is True
    print('PASS_Q0_CONVEX_OBSERVED_1M_STOP_ADAPTER_V1');return 0


if __name__=='__main__': raise SystemExit(self_test())
