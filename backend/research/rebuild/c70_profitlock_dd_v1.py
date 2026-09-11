"""Saved-only DD attribution on original UTC after-open reporting marks."""
from math import fsum, isclose
from backend.research.rebuild import c70_tm_capreuse_account_v1 as cap
from backend.research.rebuild import parallel_exit_metrics_v1 as marks

a=cap.a
SCOPE='C70_CUMULATIVE_PROFITLOCK_AFTER_PR1262_V1'
OUT=a.ROOT/'research/development_evidence'/SCOPE


def parents(per,packet,cal):
    return dict(cap.parents(per,packet,cal),CAPREUSE=a.gz(cap.OUT/per/'RESULT.json.gz'))


def window(result,packet,cal,left,right):
    prices=marks._prices(packet['rows_by'],cal['start_ms'],cal['runoff_end_ms'])
    details=[];active=[]
    for origin,(status,row) in sorted(a.bridge._index(result['trades'],result['open_observations']).items()):
        legs=row.get('weighted_legs') or [dict(status=status,row=row,qty=1.)]
        partial=[l for l in legs if l['status']=='C' and l['row'].get('exit_reason')=='D3_PROFIT_PARTIAL_NEXT_OPEN']
        is_managed=bool(partial and partial[0]['row']['exit_ts']<=right)
        qty=fsum(l['qty'] for l in legs if l['row']['entry_ts']<=left and
                 (l['status']=='O' or l['row']['exit_ts']>left))
        if qty:active.append(dict(origin_key=origin,symbol=row['symbol'],signal_ts=row['signal_ts'],normalized_qty=qty,
                                  reuse=row.get('capacity_reuse_entry',False)))
        for leg in legs:
            unit=leg['row'];st=leg['status'];q=leg['qty']
            role=('CAPREUSE_LOT' if row.get('capacity_reuse_entry') else
                  'TM_PARTIAL_LEG' if is_managed and leg in partial else
                  'TM_RUNNER_REMAINDER' if is_managed else 'ORIGINAL_LOT')
            endpoints=[]
            for ts in (left,right):
                v=marks._boundary((st,unit),ts,prices,packet['costs'],cal['start_ms'],cal['runoff_end_ms'])
                v={k:q*value for k,value in v.items()}
                realized=st=='C' and unit['exit_ts']<=ts and unit['entry_ts']<=ts and ts!=cal['start_ms']
                v.update(realized_net_bps=v['net_bps'] if realized else 0.,
                         unrealized_net_bps=0. if realized else v['net_bps'],
                         realized_partial_net_bps=v['net_bps'] if realized and leg in partial else 0.)
                endpoints.append(v)
            delta={k:endpoints[1][k]-endpoints[0][k] for k in endpoints[0]}
            details.append(dict(origin_key=origin,symbol=row['symbol'],signal_ts=row['signal_ts'],
                                role=role,qty=q,start=endpoints[0],end=endpoints[1],delta=delta))
    fields=list(a.bridge.VALUE_FIELDS)+['realized_net_bps','unrealized_net_bps','realized_partial_net_bps']
    roles={role:{k:fsum(d['delta'][k] for d in details if d['role']==role) for k in fields}
           for role in ('ORIGINAL_LOT','TM_PARTIAL_LEG','TM_RUNNER_REMAINDER','CAPREUSE_LOT')}
    totals={k:fsum(d['delta'][k] for d in details) for k in fields}
    expected=fsum(d['value'] for d in result['metrics']['daily'] if left<d['mark_ts']<=right)
    assert isclose(totals['net_bps'],expected,abs_tol=1e-7)
    assert isclose(totals['realized_net_bps']+totals['unrealized_net_bps'],expected,abs_tol=1e-7)
    assert isclose(totals['gross_bps']-totals['cost_bps'],expected,abs_tol=1e-7)
    return dict(start_ms=left,end_ms=right,totals=totals,by_role=roles,active_at_peak=active,legs=details,
                parity='PASS',valuation_phase='SAVED_UTC_AFTER_OPEN; TERMINAL_CLOSE_NO_FUTURE_OPEN',
                attribution_only=True,cash_transfer_note='Realization moves value from unrealized to realized; component changes are not independent economic losses.')


def own_window(result,packet,cal):
    daily=result['metrics']['daily'];diag=marks.marked_diagnostics(daily,cal['start_ms']);w=diag['worst_window']
    left,right=w['start_ms'],w['end_ms'];lookup={cal['start_ms']:0.,**{d['mark_ts']:d['cumulative_net_mark_bps'] for d in daily}}
    recovery=next((d['mark_ts'] for d in daily if d['mark_ts']>right and d['cumulative_net_mark_bps']>=lookup[left]),None)
    contribution=window(result,packet,cal,left,right)
    dd=diag['marked_DD_trade_sum_bps'];assert isclose(-contribution['totals']['net_bps'],dd,abs_tol=1e-7)
    return dict(peak_ts=left,trough_ts=right,recovery_ts=recovery,recovery_censored=recovery is None,
                peak_net_bps=lookup[left],trough_net_bps=lookup[right],marked_DD_bps=dd,contribution=contribution)


def compare(parent,child,packet,cal,pw,cw):
    left,right=cw['peak_ts'],cw['trough_ts']
    p=window(parent,packet,cal,left,right);c=window(child,packet,cal,left,right)
    parent_loss=-p['totals']['net_bps'];child_loss=-c['totals']['net_bps']
    effect=child_loss-parent_loss;relocation=parent_loss-pw['marked_DD_bps'];excess=cw['marked_DD_bps']-pw['marked_DD_bps']
    assert isclose(effect+relocation,excess,abs_tol=1e-7)
    old=a.bridge._index(parent['trades'],parent['open_observations']);new=a.bridge._index(child['trades'],child['open_observations'])
    def delta_by_origin(w):
        return {k:fsum(d['delta']['net_bps'] for d in w['legs'] if d['origin_key']==k) for k in {d['origin_key'] for d in w['legs']}}
    pd,cd=delta_by_origin(p),delta_by_origin(c)
    occupancy=fsum(cd.get(k,0)-pd.get(k,0) for k in old.keys()^new.keys())
    common=fsum(cd[k]-pd[k] for k in old.keys()&new.keys())
    assert isclose(common+occupancy,c['totals']['net_bps']-p['totals']['net_bps'],abs_tol=1e-7)
    return dict(own_max_DD_excess_bps=excess,child_window_same_calendar_DD_effect_bps=effect,
                parent_window_relocation_bps=relocation,residual_bps=effect+relocation-excess,
                common_window_net_change_bps=common,occupancy_window_net_change_bps=occupancy,
                child_window_parent=p,child_window_child=c,
                parent_window_child=window(child,packet,cal,pw['peak_ts'],pw['trough_ts']),
                different_maxima_subtraction_is_causal_attribution=False,parity='PASS')


def attribution(results,packet,cal):
    own={label:own_window(r,packet,cal) for label,r in results.items()};pairs={}
    labels=list(results)
    for p,c in zip(labels,labels[1:]):pairs[p+'__'+c]=compare(results[p],results[c],packet,cal,own[p],own[c])
    return dict(kind='SAVED_ONLY_DD_ATTRIBUTION',own=own,adjacent=pairs,parent_replays=0,economic_replays=0)
