"""Saved PR1264 lot diagnosis; no signals, strategy replay, or candidate gate.

The source-continuation ledger is an attribution intermediate: already saved
unit source legs at actual group-run allocations. It is not a recursively
admitted counterfactual portfolio and makes no executable-PnL claim.
"""
from copy import deepcopy
from math import fsum, isclose
from backend.research.rebuild import c70_profitlock_dd_v1 as dd
from backend.research.rebuild.c63_c70_trader_verify_v1 import independent_cost

a = dd.a
SCOPE = 'C70_LOT_LEVEL_RISK_AFTER_PR1264_V1'
OUT = a.ROOT / 'research/development_evidence' / SCOPE
GROUP = dd.OUT
PARTIAL = 'D3_PROFIT_PARTIAL_NEXT_OPEN'


def _equal(x, y, label):
    assert isclose(x, y, rel_tol=1e-11, abs_tol=1e-7), label


def _cost(cost, entry, stamp):
    return fsum(independent_cost(cost, entry, stamp).values())


def own_value(raw, stamp, price, cost):
    """Independent lot cash at completed close; equal-time opens excluded."""
    q = raw['allocation_numerator'] / raw['allocation_denominator']
    legs = [l for l in raw['tm_legs'] if l['status'] == 'C' and l['ts'] < stamp]
    partials = [l for l in legs if l['reason'] == PARTIAL]
    def net(leg):
        return q * leg['qty'] * ((leg['price'] / raw['entry_price'] - 1) * 10000
                                - _cost(cost, raw['entry_ts'], leg['ts']))
    bank = fsum(max(0., net(l)) for l in partials)
    realized = fsum(net(l) for l in legs)
    remaining = q * (1 - fsum(l['qty'] for l in legs))
    marked = remaining * ((price / raw['entry_price'] - 1) * 10000
                          - _cost(cost, raw['entry_ts'], stamp))
    return dict(realized_bank_net=bank, realized_net=realized,
                remaining_mark_net=marked, lot_marked_net=realized + marked,
                remaining_normalized_qty=remaining,
                first_partial_fill_ts=min((l['ts'] for l in partials), default=None))


def _source_ledger(raw_by, packet, cal):
    """Value immutable source references at saved actual allocations only."""
    result = dict(trades=[], open_observations=[])
    source_raw = {}
    for symbol, rr in sorted(raw_by.items()):
        for raw in rr['trades'] + rr['open_positions']:
            source = deepcopy(rr['source_references'][str(raw['signal_index'])]['raw'])
            for name in ('allocation_numerator', 'allocation_denominator',
                         'allocated_normalized_qty', 'capacity_reuse_entry'):
                source[name] = raw[name]
            status, row = dd.cap.campaign(source, symbol, packet)
            result['trades' if status == 'C' else 'open_observations'].append(row)
            source_raw[(symbol, raw['signal_index'], raw['signal_ts'])] = source
    result['metrics'] = a.metrics(result, packet, cal)
    return result, source_raw


def _index(result):
    return a.bridge._index(result['trades'], result['open_observations'])


def _terminal(row):
    return a.bridge._values(row)


def _window_values(w):
    return {key: {field: fsum(l['delta'][field] for l in w['legs']
                             if l['origin_key'] == key)
                  for field in a.bridge.VALUE_FIELDS}
            for key in {l['origin_key'] for l in w['legs']}}


def _split(parent, actual, source, classification):
    fields = a.bridge.VALUE_FIELDS
    zero = dict.fromkeys(fields, 0.)
    buckets = {name: dict(zero) for name in (
        'OWN_THRESHOLD_EXIT', 'UNBREACHED_OTHER_LOT_COLLATERAL_EXIT',
        'COMMON_QUANTITY_REENTRY_INTERACTION', 'NEW_EXCLUDED_ORIGINS')}
    details = []
    for key in sorted(parent.keys() | actual.keys() | source.keys()):
        p, g, s = parent.get(key, zero), actual.get(key, zero), source.get(key, zero)
        path_delta = {f: g[f] - s[f] for f in fields}
        if key in classification:
            bucket = classification[key]
            for f in fields:
                buckets[bucket][f] += path_delta[f]
        else:
            for f in fields:
                _equal(path_delta[f], 0., 'UNCHANGED_NON_RISK_SOURCE_PATH:' + f)
        allocation_delta = {f: s[f] - p[f] for f in fields}
        allocation_bucket = ('COMMON_QUANTITY_REENTRY_INTERACTION'
                             if key in parent and key in source else 'NEW_EXCLUDED_ORIGINS')
        for f in fields:
            buckets[allocation_bucket][f] += allocation_delta[f]
        details.append(dict(origin_key=key, risk_classification=classification.get(key),
                            actual_minus_saved_source_continuation=path_delta,
                            saved_source_allocation_minus_parent=allocation_delta,
                            allocation_bucket=allocation_bucket))
    totals = {f: fsum(actual[k][f] for k in actual) - fsum(parent[k][f] for k in parent)
              for f in fields}
    residual = {f: fsum(b[f] for b in buckets.values()) - totals[f] for f in fields}
    for f in fields:
        _equal(residual[f], 0., 'ATTRIBUTION_RESIDUAL:' + f)
    return dict(buckets=buckets, total_change=totals, residual=residual, details=details)


def diagnose_period(per):
    spec = a.read(GROUP / 'SPEC.json')
    cal = spec['periods'][per]
    packet = a.gz(a.INPUTS / (per + '.json.gz'))
    raw_by = a.gz(GROUP / per / 'RAW.json.gz')
    group_result = a.gz(GROUP / per / 'RESULT.json.gz')
    parent = a.gz(dd.cap.OUT / per / 'RESULT.json.gz')
    parent_raw = a.gz(dd.cap.OUT / per / 'RAW.json.gz')
    source, source_raw = _source_ledger(raw_by, packet, cal)
    pi, gi, si = _index(parent), _index(group_result), _index(source)
    origins = {a.key(row): key for key, (_, row) in gi.items()}
    pri_raw = {(sym, r['signal_index'], r['signal_ts']): r
               for sym, rr in parent_raw.items() for r in rr['trades'] + rr['open_positions']}
    for origin in source_raw.keys() & pri_raw.keys():
        assert source_raw[origin]['tm_legs'] == pri_raw[origin]['tm_legs'], 'UNCHANGED_UNIT_SOURCE_LEGS'
    triggers = []
    classification = {}
    risk_details = []
    for symbol, rr in sorted(raw_by.items()):
        by = {r['signal_index']: r for r in rr['trades'] + rr['open_positions']}
        peaks, first_breach = {}, {}
        fills = {(n['group_id'], n['decision']['signal_ts']): n for n in rr['group_trace']
                 if n['kind'] == 'GROUP_EXIT_FILL'}
        for obs in rr['group_trace']:
            if obs['kind'] != 'GROUP_CLOSE_OBSERVATION':
                continue
            values = {}
            for active in obs['active_lots']:
                i = active['signal_index']
                raw = by[i]
                value = own_value(raw, obs['ts'], obs['price'], packet['costs'][symbol])
                _equal(value['remaining_normalized_qty'], active['qty'], 'ACTIVE_LOT_QTY')
                armed = value['first_partial_fill_ts'] is not None
                if armed:
                    peaks[i] = max(peaks.get(i, value['lot_marked_net']), value['lot_marked_net'])
                breached = bool(armed and value['realized_bank_net'] > 0
                                and value['lot_marked_net'] <= peaks[i] - value['realized_bank_net'])
                if breached:
                    first_breach.setdefault(i, obs['ts'])
                values[i] = dict(value, lot_peak_marked_net=peaks.get(i), own_threshold_breached=breached,
                                 first_own_breach_observed_ts=first_breach.get(i), signal_index=i)
            if not obs['trigger']:
                continue
            fill = fills.get((obs['group_id'], obs['ts']))
            filled = {lot['signal_index']: lot for lot in fill['lots']} if fill else {}
            lots = []
            for i, value in values.items():
                raw = by[i]
                key = origins[(symbol, i, raw['signal_ts'])]
                actual_cut = bool(filled.get(i, {}).get('risk_exit'))
                label = ('OWN_THRESHOLD_EXIT' if value['own_threshold_breached']
                         else 'UNBREACHED_OTHER_LOT_COLLATERAL_EXIT') if actual_cut else 'SOURCE_PRIORITY_OR_NO_FILL'
                cut_qty = fsum(l['qty'] * raw['allocated_normalized_qty'] for l in raw['tm_legs']
                              if actual_cut and l['ts'] == fill['ts']
                              and l['reason'] == 'ZEL_POST_PARTIAL_RISK_ENVELOPE_NEXT_OPEN')
                money = {f: _terminal(gi[key])[f] - _terminal(si[key])[f] for f in a.bridge.VALUE_FIELDS}
                item = dict(value, origin_key=key, symbol=symbol, group_id=obs['group_id'],
                            trigger_ts=obs['ts'], actual_risk_exit=actual_cut, classification=label,
                            exit_ts=fill['ts'] if actual_cut else None,
                            normalized_cut_qty=cut_qty, saved_source_continuation_delta=money,
                            source_priority_reason=filled.get(i, {}).get('exit_reason') if not actual_cut else None)
                lots.append(item)
                if actual_cut:
                    assert key not in classification, 'LOT_CUT_ONCE'
                    classification[key] = label
                    risk_details.append(item)
            triggers.append(dict(symbol=symbol, group_id=obs['group_id'], trigger_ts=obs['ts'],
                                 saved_group_bank_net=obs['realized_bank_net'],
                                 saved_group_peak_net=obs['peak_group_marked_net'],
                                 saved_group_marked_net=obs['group_marked_net'],
                                 actual_next_open_fill=fill is not None, lots=lots))
    actual_risk_origins = {origins[(symbol, r['signal_index'], r['signal_ts'])]
                          for symbol, rr in raw_by.items() for r in rr['trades'] + rr['open_positions']
                          if r['risk_envelope_exit']}
    assert set(classification) == actual_risk_origins, 'RISK_CUT_COVERAGE'
    reentries = []
    for key in sorted(pi.keys() & gi.keys()):
        p, g = pi[key][1], gi[key][1]
        pq, gq = p['assembled_qty'], g['assembled_qty']
        if pq == gq:
            continue
        prior_group_exits = [n for n in raw_by[g['symbol']]['group_trace']
                             if n['kind'] == 'GROUP_EXIT_FILL' and n['ts'] < g['signal_ts']]
        prior = prior_group_exits[-1] if prior_group_exits else None
        reentries.append(dict(origin_key=key, symbol=g['symbol'], signal_index=g['signal_index'],
                              signal_ts=g['signal_ts'], parent_qty=pq, group_qty=gq,
                              parent_reuse=p['capacity_reuse_entry'], group_reuse=g['capacity_reuse_entry'],
                              full_size_group_root=gq == 1. and not g['capacity_reuse_entry'],
                              latest_prior_same_symbol_group_exit=prior,
                              source_path_unit_legs_identical=True,
                              terminal_allocation_net_change_bps=_terminal(si[key])['net_bps'] - _terminal(pi[key])['net_bps']))
    terminal = _split({k: _terminal(v) for k, v in pi.items()},
                      {k: _terminal(v) for k, v in gi.items()},
                      {k: _terminal(v) for k, v in si.items()}, classification)
    pw, gw = dd.own_window(parent, packet, cal), dd.own_window(group_result, packet, cal)
    left, right = gw['peak_ts'], gw['trough_ts']
    pwin, gwin, swin = (dd.window(r, packet, cal, left, right) for r in (parent, group_result, source))
    window = _split(_window_values(pwin), _window_values(gwin), _window_values(swin), classification)
    dd_buckets = {k: -v['net_bps'] for k, v in window['buckets'].items()}
    relocation = -pwin['totals']['net_bps'] - pw['marked_DD_bps']
    own_dd_change = gw['marked_DD_bps'] - pw['marked_DD_bps']
    residual = fsum(dd_buckets.values()) + relocation - own_dd_change
    _equal(residual, 0., 'DD_DIRECT_COLLATERAL_REENTRY_RELOCATION_RESIDUAL')
    collateral = [r for r in risk_details if r['classification'] == 'UNBREACHED_OTHER_LOT_COLLATERAL_EXIT']
    counts = dict(group_triggers=len(triggers), active_lot_trigger_observations=sum(len(t['lots']) for t in triggers),
                  own_breached_lot_trigger_observations=sum(l['own_threshold_breached'] for t in triggers for l in t['lots']),
                  actual_risk_exits=len(risk_details), own_breached_actual_exits=len(risk_details) - len(collateral),
                  collateral_actual_exits=len(collateral),
                  source_priority_or_no_fill_lot_observations=sum(not l['actual_risk_exit'] for t in triggers for l in t['lots']),
                  collateral_normalized_exit_qty=fsum(r['normalized_cut_qty'] for r in collateral),
                  collateral_terminal_net_change_bps=fsum(r['saved_source_continuation_delta']['net_bps'] for r in collateral),
                  collateral_terminal_gross_change_bps=fsum(r['saved_source_continuation_delta']['gross_bps'] for r in collateral),
                  collateral_terminal_cost_change_bps=fsum(r['saved_source_continuation_delta']['cost_bps'] for r in collateral),
                  common_quantity_changes=len(reentries),
                  full_size_root_quantity_changes=sum(r['full_size_group_root'] for r in reentries))
    assert counts['group_triggers'] == {'DEV2025': 26, 'SEEN2026': 6}[per], 'ALL_SAVED_GROUP_TRIGGERS'
    return dict(period=per, counts=counts, triggers=triggers, collateral_lots=collateral,
                common_quantity_reentry_interactions=reentries, terminal_attribution=terminal,
                dd_attribution=dict(parent_own_peak_ts=pw['peak_ts'], parent_own_trough_ts=pw['trough_ts'],
                                    group_own_peak_ts=left, group_own_trough_ts=right,
                                    parent_own_DD_bps=pw['marked_DD_bps'], group_own_DD_bps=gw['marked_DD_bps'],
                                    matched_group_window_DD_change_by_bucket_bps=dd_buckets,
                                    matched_group_window_DD_change_bps=-window['total_change']['net_bps'],
                                    parent_window_relocation_bps=relocation,
                                    own_max_DD_change_bps=own_dd_change, residual_bps=residual,
                                    matched_window_full_accounting=window,
                                    different_maxima_subtraction_is_causal_attribution=False),
                source_continuation_note='Saved original unit legs valued at actual group-run allocations; no admission or signals rerun. This nonrecursive ledger is solely an exact accounting bridge, not a feasible counterfactual portfolio.',
                interpretation='Own/collateral classification uses only actual lot fills strictly before each group decision and own causal post-partial peak. Later source legs are used only for forensic PnL attribution, never classification or a candidate gate.',
                parent_replays=0, economic_replays=0, candidate_gate=False, status='PASS_SAVED_ONLY')


def diagnose():
    files = [GROUP / 'SPEC.json']
    for per in a.PERIODS:
        files.extend([a.INPUTS / (per + '.json.gz')])
        files.extend(folder / per / name for folder in (GROUP, dd.cap.OUT)
                     for name in ('RAW.json.gz', 'RESULT.json.gz'))
    return dict(scope=SCOPE, kind='PR1264_SAVED_GROUP_TO_LOT_FORENSIC_DIAGNOSTIC',
                periods={per: diagnose_period(per) for per in a.PERIODS},
                saved_inputs_sha256={str(path.relative_to(a.ROOT)): a.h(path) for path in files},
                comparison_parent='EXACT_PR1262_C70_TM_CAPREUSE_V1_CANDIDATE82',
                failed_reference='EXACT_PR1264_C70_CUMULATIVE_PROFITLOCK_V1_CANDIDATE83',
                risk_classification_phase='COMPLETED_4H_CLOSE_BEFORE_EQUAL_TIME_OPEN_FILLS',
                attribution_valuation_phase='INHERITED_UTC_AFTER_OPEN_DAILY_MARKS',
                candidate_gate=False, parent_replays=0, economic_replays=0)


def report(data):
    lines = ['# PR1264 saved group → lot diagnostic', '',
             'PR1262 CAPREUSE is the development parent. This saved-only diagnostic does not gate the authorized LOTLOCK candidate.', '',
             '| Window | Group triggers | Actual risk exits | Own breached exits | Other-lot collateral exits | Collateral normalized qty | Collateral net change vs saved continuation (bps) | Full-size root qty changes |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for per, result in data['periods'].items():
        c = result['counts']
        lines.append(f"| {per} | {c['group_triggers']} | {c['actual_risk_exits']} | {c['own_breached_actual_exits']} | {c['collateral_actual_exits']} | {c['collateral_normalized_exit_qty']:.9f} | {c['collateral_terminal_net_change_bps']:.6f} | {c['full_size_root_quantity_changes']} |")
    lines += ['', 'Own thresholds use only each lot’s positive actual partial net, its own completed-close marked net and its own peak since actual partial. Equal-time next-open fills are excluded. Source exits already due at the next open keep priority.', '',
              'The source-continuation intermediate values immutable saved unit source legs at the group run’s actual allocations. It does not rerun admissions and is not an executable counterfactual. Positive collateral net change means the forced cut happened to improve saved terminal PnL; it remains a collateral intervention.', '',
              '| Window | Own-threshold exit DD effect | Collateral exit DD effect | Quantity/reentry DD effect | New/excluded DD effect | Peak-window relocation | Own max DD change | Residual |',
              '|---|---:|---:|---:|---:|---:|---:|---:|']
    for per, result in data['periods'].items():
        d = result['dd_attribution']; b = d['matched_group_window_DD_change_by_bucket_bps']
        lines.append(f"| {per} | {b['OWN_THRESHOLD_EXIT']:.6f} | {b['UNBREACHED_OTHER_LOT_COLLATERAL_EXIT']:.6f} | {b['COMMON_QUANTITY_REENTRY_INTERACTION']:.6f} | {b['NEW_EXCLUDED_ORIGINS']:.6f} | {d['parent_window_relocation_bps']:.6f} | {d['own_max_DD_change_bps']:.6f} | {d['residual_bps']:.9f} |")
    lines += ['', 'DD effects above use the same group peak→trough calendar on both ledgers. Negative means a lower loss in that matched window. The parent window relocation term separately reconciles the difference between each run’s own maximum DD. These are observed saved-accounting allocations; they do not establish isolated causal portfolio returns.', '',
              'Full trigger details, source-priority cases, lot cash/peak witnesses, collateral PnL, quantity/reentry changes, terminal money bridges and DD residuals are in PRE_DIAGNOSTIC.json. Parent strategy replays and economic evaluations: 0.', '']
    return '\n'.join(lines)
