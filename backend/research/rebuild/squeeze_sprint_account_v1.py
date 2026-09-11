"""Saved cash accounting and pre-outcome, deterministic sprint selection.

No entry generator, economic replay, file-writing CLI or automated tuning.
Stage1 money/exposure is a fixed-admission component proxy, never FULL.
"""
from copy import deepcopy
from math import fsum, isclose
from backend.research.rebuild import c70_tm_capreuse_account_v1 as cap
from backend.research.rebuild import squeeze_sprint_components_v1 as components

a=cap.a
SCOPE='SQUEEZE_CONTINUATION_BENCHMARK_SPRINT_AFTER_PR1266_V1'
OUT=a.ROOT/'research/development_evidence'/SCOPE
PERIODS=('DEV2025','SEEN2026')
SCREEN='COMMON_TRADE_PROXY_NO_OCCUPANCY_REPLAY'


def charge(raw_by,packet,cal,label,mode):
    result=dict(trades=[],open_observations=[],events=[],trace=[],screen_trace=[],audit={},candidate=label,
                comparison_mode=mode,independent=False,formal_credit=0,operating_adoption=False)
    for symbol,rr in sorted(raw_by.items()):
        for raw in rr['trades']+rr['open_positions']:
            status,row=cap.campaign(raw,symbol,packet)
            row.update(candidate=label,comparison_mode=mode,evidence_type='SOURCE_COMPONENT_ZEL_PORT')
            row.pop('trade_sha256',None);row.pop('observation_sha256',None)
            row['trade_sha256' if status=='C' else 'observation_sha256']=a.p.sha(row)
            result['trades' if status=='C' else 'open_observations'].append(row)
        for name in ('events','trace','screen_trace'):
            result[name].extend(dict(x,symbol=symbol) for x in rr.get(name,[]))
        result['audit'][symbol]=deepcopy(rr['audit'])
    result['metrics']=a.metrics(result,packet,cal)
    return result


def snapshot(result,parent):
    s=cap.snapshot(result,parent)
    s['comparison_mode']=result.get('comparison_mode','SAVED_PARENT_FULL')
    s['component_exit_count']=sum(t.get('component_exit',False) or any(
        l['reason'].removesuffix('_NEXT_OPEN') in {v['reason'] for v in components.REGISTRY.values()}
        for l in t.get('tm_legs',[])) for t in result['trades'])
    s['component_trigger_count']=sum(t.get('trigger',False) for t in result.get('screen_trace',[]))
    s['screen_changed_campaigns']=sum(t.get('screen_changed',False) for t in result['trades']+result['open_observations'])
    return s


def screen_metrics(parent,child):
    p=snapshot(parent,parent);c=snapshot(child,parent)
    old=a.bridge._index(parent['trades'],parent['open_observations'])
    new=a.bridge._index(child['trades'],child['open_observations'])
    assert old.keys()==new.keys(),'SCREEN_FIXED_ORIGIN_SET'
    assert all(old[k][1]['assembled_qty']==new[k][1]['assembled_qty'] for k in old),'SCREEN_FIXED_ALLOCATION'
    bridge=a.decomposition(parent,child)
    assert bridge['occupancy_new_excluded_net_bps']==0
    def values(index,field):return fsum(a.bridge._values(v)[field] for v in index.values())
    def giveback(index):
        return fsum(max(0.,row.get('mfe_bps',0)*row['assembled_qty']-a.bridge._values((status,row))['gross_bps'])
                    for status,row in index.values())
    def mae(index):return fsum(row.get('mae_bps',0)*row['assembled_qty'] for _,row in index.values())
    r=dict(comparison_mode=SCREEN,normal_increment_bps=c['terminal_net_bps']-p['terminal_net_bps'],
        cost2_increment_bps=c['terminal_cost2x_net_bps']-p['terminal_cost2x_net_bps'],
        gross_delta_bps=values(new,'gross_bps')-values(old,'gross_bps'),
        cost_delta_bps=values(new,'cost_bps')-values(old,'cost_bps'),
        ordinary_winner_retention=c['ordinary_winner_retention'],top_decile_winner_retention=c['top_decile_winner_retention'],
        avoided_loss_campaigns=sum(a.bridge._values(old[k])['net_bps']<=0<a.bridge._values(new[k])['net_bps'] for k in old),
        reduced_loss_campaigns=sum(a.bridge._values(old[k])['net_bps']<0 and a.bridge._values(new[k])['net_bps']>a.bridge._values(old[k])['net_bps'] for k in old),
        clipped_winner_campaigns=sum(a.bridge._values(old[k])['net_bps']>0 and a.bridge._values(new[k])['net_bps']<a.bridge._values(old[k])['net_bps'] for k in old),
        mfe_giveback_reduction_bps=giveback(old)-giveback(new),quantity_weighted_mae_delta_bps=mae(new)-mae(old),
        loss_tail_worst_bps=c['loss_tail_worst_bps'],loss_tail_worst_decile_mean_bps=c['loss_tail_worst_decile_mean_bps'],
        exposure_delta_symbol_days=c['quantity_exposure_symbol_days']-p['quantity_exposure_symbol_days'],
        quantity_exposure_symbol_days=c['quantity_exposure_symbol_days'],
        hold_maximum_days=c['exposure']['maximum_holding_days_including_open'],
        trigger_count=c['component_trigger_count'],component_exit_count=c['component_exit_count'],
        changed_campaigns=c['screen_changed_campaigns'],gross_decomposition=bridge,
        source_conformance='PASS',causal_integrity='PASS',formal_credit=0,canonical_candidates=0,FULL=0,
        exposure_semantics='FIXED_PARENT_ADMISSIONS_AND_ALLOCATIONS; MAY_EXCEED_CAPACITY; NOT_EXECUTABLE_FULL')
    assert isclose(r['normal_increment_bps'],r['gross_delta_bps']-r['cost_delta_bps'],abs_tol=1e-7)
    assert isclose(r['cost2_increment_bps'],r['gross_delta_bps']-2*r['cost_delta_bps'],abs_tol=1e-7)
    return r


def stage1_gate(m):
    checks=dict(source=m['source_conformance']=='PASS',causal=m['causal_integrity']=='PASS',
        normal_positive=m['normal_increment_bps']>0,cost2_positive=m['cost2_increment_bps']>0,
        ordinary_retained=m['ordinary_winner_retention'] is not None and m['ordinary_winner_retention']>=.60,
        top_decile_retained=m['top_decile_winner_retention'] is not None and m['top_decile_winner_retention']>=.60,
        positive_after_winner_cuts=m['normal_increment_bps']>0)
    return dict(passed=all(checks.values()),checks=checks)


def _vector(periods):
    # Every window is a separate Pareto coordinate; a collapse cannot be hidden
    # by summing a profitable period. Higher coordinates always preferred.
    return tuple(x for per in PERIODS for x in (
        periods[per]['cost2_increment_bps'],periods[per]['ordinary_winner_retention'],
        periods[per]['top_decile_winner_retention'],
        periods[per]['loss_tail_worst_decile_mean_bps'] if periods[per]['loss_tail_worst_decile_mean_bps'] is not None else 0.,
        -periods[per]['quantity_exposure_symbol_days']))


def _narrow(passed,table,registry,limit):
    if len(passed)<=limit:return sorted(passed),[]
    vectors={s:_vector(table[s]) for s in passed}
    dominated=[s for s in passed if any(t!=s and all(a>=b for a,b in zip(vectors[t],vectors[s]))
        and any(a>b for a,b in zip(vectors[t],vectors[s])) for t in passed)]
    frontier=[s for s in passed if s not in dominated]
    rank=lambda s:({'A':0,'B':1,'C':2}[registry[s]['performance_grade']],
        -fsum(table[s][p]['cost2_increment_bps'] for p in PERIODS),s)
    selected=sorted(frontier,key=rank)[:limit]
    return selected,sorted(set(passed)-set(selected))


def select_stage1(table,registry):
    decisions={s:{p:stage1_gate(table[s][p]) for p in PERIODS} for s in sorted(table)}
    passed=[s for s,d in decisions.items() if all(v['passed'] for v in d.values())]
    survivors,limited=_narrow(passed,table,registry,3)
    return dict(stage='STAGE1',survivors=survivors,decisions=decisions,hard_gate_passed=passed,
        pareto_or_deterministic_cap_excluded=limited,per_window_gate='BOTH_SEPARATELY',FULL=0,canonical_candidates=0)


def full_gate(child,parent):
    # Preserve the exact parent's cumulative-workcopy criterion (SPEC retention
    # 1), and inherited loss-tail discipline. Screen's .60 is NOT adoption.
    checks=dict(normal_positive=child['terminal_net_bps']>parent['terminal_net_bps'],
        cost2_positive=child['terminal_cost2x_net_bps']>parent['terminal_cost2x_net_bps'],
        closed_net_positive=child['net_bps']>parent['net_bps'],
        dd_not_worse=child['marked_DD_trade_sum_bps']<=parent['marked_DD_trade_sum_bps']+1e-7,
        ordinary_retained=child['ordinary_winner_retention'] is not None and child['ordinary_winner_retention']>=1.-1e-12,
        top_decile_retained=child['top_decile_winner_retention'] is not None and child['top_decile_winner_retention']>=1.-1e-12,
        worst_loss_not_worse=(child['loss_tail_worst_bps'] or 0.)>=(parent['loss_tail_worst_bps'] or 0.)-1e-7,
        tail_not_worse=(child['loss_tail_worst_decile_mean_bps'] or 0.)>=(parent['loss_tail_worst_decile_mean_bps'] or 0.)-1e-7)
    return dict(passed=all(checks.values()),checks=checks)


def select_stage2(table,parents,registry):
    decisions={s:{p:full_gate(table[s][p],parents[p]) for p in PERIODS} for s in sorted(table)}
    passed=[s for s,d in decisions.items() if all(v['passed'] for v in d.values())]
    transformed={s:{p:dict(table[s][p],cost2_increment_bps=table[s][p]['terminal_cost2x_net_bps']-parents[p]['terminal_cost2x_net_bps']) for p in PERIODS} for s in table}
    survivors,limited=_narrow(passed,transformed,registry,2)
    return dict(stage='STAGE2',survivors=survivors,decisions=decisions,hard_gate_passed=passed,
                pareto_or_deterministic_cap_excluded=limited,per_window_gate='BOTH_SEPARATELY')
