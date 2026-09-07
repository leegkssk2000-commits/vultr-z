"""Descriptive origin bridges; reused existing Top5 decision owners unchanged."""
from collections import defaultdict
from datetime import datetime, timezone
import math
from backend.research.rebuild import parallel_exit_metrics_v1 as exits
from backend.research.rebuild import keltner_cumulative_entry_metrics_v1 as entries

bridge = exits.bridge
stage_values = entries.stage_values


def index(view):
    return bridge._index(view['trades'], view['open_observations'])


def effects(parent, child):
    p, c = index(parent), index(child)
    winners = sorted((k for k, (s,t) in p.items() if s=='C' and t['net_bps']>0),
                     key=lambda k:(-p[k][1]['net_bps'],k))
    large = set(winners[:math.ceil(len(winners)*.1)])
    rows, groups = [], defaultdict(list)
    zero = dict.fromkeys(exits.VALUE_FIELDS, 0.)
    for origin in sorted(p.keys() | c.keys()):
        a, b = p.get(origin), c.get(origin)
        av, bv = bridge._values(a) if a else zero, bridge._values(b) if b else zero
        t = (a or b)[1]
        delta = {k:bv[k]-av[k] for k in exits.VALUE_FIELDS}
        r = {'origin_key':origin, 'symbol':t['symbol'], 'signal_ts':t['signal_ts'],
            'entry_month':datetime.fromtimestamp(t['entry_ts']/1000,timezone.utc).strftime('%Y-%m'),
            'transition':(a[0] if a else 'ABSENT')+'_'+(b[0] if b else 'ABSENT'),
            'parent':av, 'child':bv, 'delta':delta, 'parent_large_winner':origin in large,
            'parent_winner':origin in winners,
            'winner_to_loss':origin in winners and b is not None and bv['net_bps']<0,
            'winner_removed':origin in winners and b is None,
            'parent_hold_ms':a[1]['hold_ms'] if a else 0,
            'child_hold_ms':b[1]['hold_ms'] if b else 0}
        rows.append(r); groups[r['transition']].append(r)
    totals = {k:sum(r['delta'][k] for r in rows) for k in exits.VALUE_FIELDS}
    pt, ct = bridge._totals(list(p.values())), bridge._totals(list(c.values()))
    for key in exits.VALUE_FIELDS:
        bridge._same(totals[key], ct[key]-pt[key], 'SPRINT_ALL_ORIGIN_TERMINAL_BRIDGE:'+key)
    def winner_group(big):
        rs = [r for r in rows if r['parent_winner'] and r['parent_large_winner']==big]
        amount = sum(r['parent']['net_bps'] for r in rs)
        retained = sum(min(r['parent']['net_bps'], max(0.,r['child']['net_bps'])) for r in rs)
        closed = sum(min(r['parent']['net_bps'],max(0.,r['child']['net_bps'])) for r in rs if r['transition']=='C_C')
        unresolved = sum(r['parent']['net_bps'] for r in rs if r['transition']=='C_O')
        return {'T':len(rs), 'parent_positive_bps':amount, 'child_signed_terminal_bps':sum(r['child']['net_bps'] for r in rs),
            'capped_terminal_preserved_bps_hypothetical':retained,
            'capped_terminal_retention_hypothetical':retained/amount if amount else None,
            'realized_capped_retention_lower':closed/amount if amount else None,
            'realized_capped_retention_upper':(closed+unresolved)/amount if amount else None,
            'profit_cut_bps':sum(max(0.,r['parent']['net_bps']-max(0.,r['child']['net_bps'])) for r in rs),
            'additional_loss_after_winner_bps':sum(max(0.,-r['child']['net_bps']) for r in rs),
            'signed_winner_deterioration_bps':sum(max(0.,r['parent']['net_bps']-r['child']['net_bps']) for r in rs),
            'winner_to_loss_T':sum(r['winner_to_loss'] for r in rs),
            'winner_removed_T':sum(r['winner_removed'] for r in rs),
            'winner_to_loss_origins':[r['origin_key'] for r in rs if r['winner_to_loss']]}
    positive = [r for r in rows if r['delta']['net_bps']>0]
    top = max(positive,key=lambda r:r['delta']['net_bps']) if positive else None
    def concentration(key):
        grouped = defaultdict(float)
        for r in rows: grouped[r[key]] += r['delta']['net_bps']
        return dict(grouped)
    return {'all_origin_terminal_delta_bps':totals,
        'transition_groups':{k:{'T':len(v),'delta_bps':{f:sum(r['delta'][f] for r in v) for f in exits.VALUE_FIELDS}} for k,v in sorted(groups.items())},
        'ordinary_winners':winner_group(False), 'large_winners':winner_group(True),
        'largest_positive_origin':top, 'net_increment_without_largest_positive':totals['net_bps']-(top['delta']['net_bps'] if top else 0.),
        'largest_positive_share_of_net_increment':top['delta']['net_bps']/totals['net_bps'] if top and totals['net_bps'] else None,
        'increment_by_symbol':concentration('symbol'), 'increment_by_entry_month':concentration('entry_month'),
        'per_origin':rows, 'parity':'PASS', 'absence_is_only_zero_contribution_not_zero_return_trade':True,
        'cost_saving_already_in_net':True, 'post_outcome_diagnostic_only':True, 'independent':False}


def fixed_full_bridge(parent, fixed, full):
    a, b, c = index(parent), index(fixed), index(full)
    t = [bridge._totals(list(v.values())) for v in (a,b,c)]
    output = {}
    for field in exits.VALUE_FIELDS:
        direct, occupancy, total = t[1][field]-t[0][field], t[2][field]-t[1][field], t[2][field]-t[0][field]
        bridge._same(direct+occupancy,total,'SPRINT_FIXED_FULL_BRIDGE:'+field)
        output[field] = {'fixed_path_or_filter_effect':direct,'full_occupancy_remainder':occupancy,'full_total_effect':total}
    return {'terminal':output,'fixed_to_full_effects':effects(fixed,full),
        'parent_to_full_effects':effects(parent,full),'parity':'PASS',
        'fixed_is_executable_portfolio':False,'all_costs_and_open_marks_included':True}


def compare(kind, ps, cs, parent, child, rows, costs, start, end):
    owner = exits if kind=='KR1' else entries
    return owner.compare(ps,cs,parent['trades'],parent['open_observations'],
        child['trades'],child['open_observations'],rows,costs,start,end)
