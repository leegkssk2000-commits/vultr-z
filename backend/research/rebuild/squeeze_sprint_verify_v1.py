"""Read-only validation of saved sprint decisions and cash; no replay dispatcher.

Predicates below are independently evaluated from the observed price prefix.
They intentionally do not import or call the component or execution engines.
Stage1 fixed admissions are checked without imposing a fictitious capacity cap.
"""
from collections import defaultdict
from fractions import Fraction
from hashlib import sha256
from math import fsum, isclose, isfinite
from pathlib import Path
import json

from backend.research.rebuild import c63_c70_trader_verify_v1 as old

B, D = 14_400_000, 86_400_000
SCOPE = 'SQUEEZE_CONTINUATION_BENCHMARK_SPRINT_AFTER_PR1266_V1'
SCREEN = 'COMMON_TRADE_PROXY_NO_OCCUPANCY_REPLAY'
PARTIAL = 'D3_PROFIT_PARTIAL_NEXT_OPEN'
REPLACEMENTS = {'S1-02', 'S1-07'}
REASONS = {'S1-02': 'BASSO_SMA5_BELOW_SMA10_CLOSE',
           'S1-03': 'RASCHKE_NEW_CLOSE_HIGH_LOWER_3_10_OSCILLATOR',
           'S1-04': 'CARTER_FOUR_BAR_NET_NONPOSITIVE_CLOSE',
           'S1-07': 'MARTIN_LUK_DAILY_EMA9_CLOSE'}


def _equal(x, y, label):
    if isinstance(x, bool) or isinstance(y, bool):
        assert x == y and type(x) is type(y), label
    elif isinstance(x, (int, float)) and isinstance(y, (int, float)):
        assert isfinite(x) and isfinite(y) and isclose(x, y, rel_tol=1e-11, abs_tol=1e-7), label
    else:
        assert x == y, label


def _campaigns(rr):
    records = rr['trades'] + rr['open_positions']
    by = {r['signal_index']: r for r in records}
    assert len(by) == len(records), 'DUPLICATE_CAMPAIGN'
    return by


def _days(rows, j):
    groups = defaultdict(list)
    for row in rows[:j + 1]:
        groups[row['bar_open_ts'] // D].append(row)
    return [group[-1]['close'] for day, group in sorted(groups.items())
            if [r['bar_open_ts'] for r in group] == [day * D + k * B for k in range(6)]]


def _oscillator(rows, j):
    if j < 9:
        return None
    return fsum(r['close'] for r in rows[j - 2:j + 1]) / 3 - fsum(
        r['close'] for r in rows[j - 9:j + 1]) / 10


def component_prefix(slot, rows, j, ei, entry, runner, cost):
    """Independent predicate at one completed close, never a strategy replay."""
    assert slot in REASONS and 0 <= ei <= j < len(rows), 'COMPONENT_IDENTITY'
    stamp = rows[j]['bar_close_ts']
    net = (rows[j]['close'] / entry - 1) * 10000 - fsum(
        old.independent_cost(cost, rows[ei]['bar_open_ts'], stamp).values())
    features = dict(index=j, available_at=stamp, close=rows[j]['close'],
                    entry_index=ei, actual_partial_filled=runner)
    trigger = False
    if slot in REPLACEMENTS:
        days = _days(rows, j)
        features.update(is_daily_close=stamp % D == 0, completed_days=len(days))
        if slot == 'S1-02':
            fast = fsum(days[-5:]) / 5 if len(days) >= 5 else None
            slow = fsum(days[-10:]) / 10 if len(days) >= 10 else None
            features.update(sma5=fast, sma10=slow, history_available=slow is not None)
            trigger = bool(runner and stamp % D == 0 and slow is not None and fast < slow)
        else:
            ema = fsum(days[:9]) / 9 if len(days) >= 9 else None
            if ema is not None:
                for value in days[9:]:
                    ema = 0.2 * value + 0.8 * ema
            features.update(ema9=ema, history_available=ema is not None)
            trigger = bool(runner and stamp % D == 0 and ema is not None and rows[j]['close'] < ema)
        features['data_safety_required'] = bool(runner and stamp % D == 0 and not features['history_available'])
    elif slot == 'S1-03':
        prior = max(range(ei, j), key=lambda k: rows[k]['close']) if j > ei else None
        prior_close = rows[prior]['close'] if prior is not None else None
        oscillator = _oscillator(rows, j)
        prior_oscillator = _oscillator(rows, prior) if prior is not None else None
        record = prior_close is not None and rows[j]['close'] > prior_close
        features.update(oscillator=oscillator, prior_record_close=prior_close,
                        prior_record_oscillator=prior_oscillator, prior_record_index=prior,
                        new_strict_record=record,
                        history_available=oscillator is not None and prior_oscillator is not None)
        trigger = bool(runner and record and oscillator is not None and prior_oscillator is not None
                       and oscillator < prior_oscillator)
    else:
        due = j == ei + 3
        features.update(held_bars=j - ei + 1, checkpoint_index=ei + 3,
                        checkpoint_due=due, net_progress_bps=net, initial_thrust_bars=4)
        trigger = due and net <= 0
    return dict(trigger=trigger, reason=REASONS[slot] if trigger else None, features=features,
                source_slot=slot)


def _verify_observation(observed, expected):
    for name in ('trigger', 'reason', 'source_slot'):
        assert observed[name] == expected[name], 'CAUSAL_COMPONENT_' + name
    for name, value in expected['features'].items():
        _equal(observed['features'][name], value, 'CAUSAL_FEATURE_' + name)


def _base_pending(raw, rows, j, runner, count, cost, slots):
    row = rows[j]
    entry = raw['entry_price']
    day = old.daily(rows, j)
    net = (row['close'] / entry - 1) * 10000 - fsum(
        old.independent_cost(cost, raw['entry_ts'], row['bar_close_ts']).values())
    reason = 'FIXED_FLOOR_CLOSE' if row['close'] <= raw['fixed_floor'] else None
    if reason is None and runner and row['close'] <= entry:
        reason = 'RUNNER_BREAKEVEN_CLOSE'
    if reason is None and not runner and row['close'] - rows[j - 14]['close'] <= 0:
        reason = 'MOMENTUM_NONPOSITIVE_CLOSE'
    if reason is None and runner and day['is_daily_close']:
        if day['sma10'] is None:
            reason = 'RUNNER_DAILY_HISTORY_SAFETY_CLOSE'
        elif not set(slots) & REPLACEMENTS and row['close'] < day['sma10']:
            reason = 'RUNNER_SMA10_CLOSE'
    return reason, day, net


def verify_lifecycle_saved(raw, trace, rows, cost, end, slots, component_observations=None):
    """Check a supplied saved campaign, source priority, fills and causal features."""
    slots = tuple(slots)
    assert slots and len(slots) == len(set(slots)) and all(s in REASONS for s in slots)
    assert len(set(slots) & REPLACEMENTS) <= 1, 'MULTIPLE_RUNNER_REPLACEMENTS'
    ei, entry = raw['entry_index'], raw['entry_price']
    assert raw['signal_index'] + 1 == ei >= 14, 'ORIGINAL_NEXT_OPEN_ENTRY'
    assert raw['entry_ts'] == raw['signal_ts'] == rows[ei]['bar_open_ts'], 'ENTRY_TIMESTAMP'
    assert entry == rows[ei]['open'] and raw['side'] == 'long', 'ACTUAL_ENTRY'
    assert raw['assembled_qty'] == 1 and raw['original_protective_sl'] is None
    assert raw['exchange_resident_stop'] is False
    final_index = raw.get('exit_index', raw.get('mark_index'))
    assert final_index is not None and ei <= final_index < len(rows), 'TERMINAL_INDEX'
    for j, row in enumerate(rows[:final_index + 1]):
        assert row['bar_close_ts'] == row['bar_open_ts'] + B, 'BAR_CLOSE_CLOCK'
        if j:
            assert row['bar_open_ts'] == rows[j - 1]['bar_close_ts'], 'BAR_GAP'
    assert [t['kind'] for t in trace].count('ENTRY_NEXT_OPEN') == 1
    assert trace[0]['kind'] == 'ENTRY_NEXT_OPEN' and trace[0]['index'] == ei
    assert trace[0]['ts'] == raw['entry_ts'] and trace[0]['price'] == entry
    qty, runner, managed, count = 1., False, False, 0
    pending, fills, last_held = None, [], ei - 1
    expected_obs = {}
    for event in trace[1:]:
        j, kind = event['index'], event['kind']
        row = rows[j]
        assert event['signal_index'] == raw['signal_index'], 'TRACE_ORIGIN'
        if kind == 'HELD_CLOSE_OBSERVATION':
            assert j == last_held + 1 and qty > 0 and pending is None, 'HELD_CONTIGUITY_OR_UNFILLED_DECISION'
            last_held = j
            assert event['ts'] == row['bar_close_ts'] and event['close'] == row['close'], 'CLOSE_OBSERVATION'
            if event['ts'] % D == 0 and event['ts'] > raw['entry_ts']:
                count += 1
            reason, day, net = _base_pending(raw, rows, j, runner, count, cost, slots)
            assert event['daily'] == day and event['daily_count'] == count, 'COMPLETE_DAILY_HISTORY'
            _equal(event['momentum'], row['close'] - rows[j - 14]['close'], 'NATIVE_MOMENTUM')
            assert event['runner'] == runner, 'ACTUAL_PARTIAL_BEFORE_RUNNER'
            _equal(event['remaining_qty'], qty, 'HELD_REMAINING')
            _equal(event['net_progress_bps'], net, 'CLOSE_NET_AFTER_COST')
            first = day['is_daily_close'] and count == 3 and not managed
            assert event['first_management'] == first, 'FROZEN_D3_CLOCK'
            if first:
                managed = True
            observations = [component_prefix(s, rows, j, ei, entry, runner, cost) for s in slots]
            for obs in observations:
                expected_obs[(obs['source_slot'], j)] = (obs, reason is not None)
            if reason is None:
                triggered = [o for o in observations if o['trigger']]
                if triggered:
                    reason = triggered[0]['reason']
            if reason:
                pending = dict(action='FINAL', reason=reason, signal_index=j, signal_ts=event['ts'])
            elif first and net > 0:
                pending = dict(action='PARTIAL', reason='D3_PROFIT', signal_index=j, signal_ts=event['ts'])
                if day['sma10'] is None or row['close'] < day['sma10']:
                    pending['exit_remainder'] = 'D3_SMA10_SAFETY_CLOSE'
            observed_pending = event.get('pending')
            if observed_pending is None:
                assert pending is None, 'OMITTED_REQUIRED_EXIT'
            else:
                assert {k: v for k, v in observed_pending.items() if k != 'screen_slot'} == pending, 'CAUSAL_EXIT_PRIORITY'
            if 'component_observations' in event:
                assert len(event['component_observations']) == len(observations)
                for observed, expected in zip(event['component_observations'], observations, strict=True):
                    _verify_observation(observed, expected)
        elif kind in ('PARTIAL_FILL', 'FINAL_FILL'):
            assert pending and j == pending['signal_index'] + 1, 'NEXT_OBSERVABLE_OPEN_ONLY'
            assert event['ts'] == row['bar_open_ts'] == pending['signal_ts'] and event['ts'] < end
            assert event['price'] == row['open'], 'GAP_OPEN_PRICE'
            assert {k: v for k, v in event['decision'].items() if k != 'screen_slot'} == pending
            if kind == 'PARTIAL_FILL':
                assert pending['action'] == 'PARTIAL' and not runner and not event['slot_released']
                _equal(event['qty'], 1 / 3, 'FROZEN_ONE_THIRD_PARTIAL')
                fills.append(dict(status='C', qty=1 / 3, index=j, ts=event['ts'], price=row['open'], reason=PARTIAL))
                qty -= 1 / 3
                runner = True
                _equal(event['remaining_qty'], qty, 'PARTIAL_RESIDUAL')
                if not pending.get('exit_remainder'):
                    pending = None
            else:
                assert pending['action'] == 'FINAL' or pending.get('exit_remainder')
                reason = pending.get('exit_remainder', pending['reason']) + '_NEXT_OPEN'
                fills.append(dict(status='C', qty=qty, index=j, ts=event['ts'], price=row['open'], reason=reason))
                qty, pending = 0., None
                assert event['slot_released'] and event['remaining_qty'] == 0
        elif kind == 'TERMINAL_MARK':
            assert qty > 0 and j == last_held and event['ts'] == row['bar_close_ts'] == end
            assert not event['slot_released'] and event['price'] == row['close'], 'NO_FAKE_TERMINAL_FILL'
            _equal(event['remaining_qty'], qty, 'TERMINAL_RESIDUAL')
            fills.append(dict(status='O', qty=qty, index=j, ts=end, price=row['close'], reason='TERMINAL_MARK'))
        else:
            raise AssertionError('UNKNOWN_TRACE_EVENT')
    assert raw['tm_legs'] == fills and fills, 'ALL_LEGS_FROM_SAVED_TRACE'
    _equal(fsum(l['qty'] for l in fills), 1., 'UNIT_QUANTITY_CONSERVATION')
    _equal(raw['remaining_qty'], qty, 'RAW_REMAINING_QUANTITY')
    assert raw['partial_count'] == sum(l['reason'] == PARTIAL for l in fills)
    assert raw['runner_activated'] == runner
    last = fills[-1]
    assert last['index'] == final_index
    _equal(raw['hold_ms'], last['ts'] - raw['entry_ts'], 'ACTUAL_HOLD_MS')
    gross = fsum(l['qty'] * (l['price'] / entry - 1) * 10000 for l in fills)
    if last['status'] == 'O':
        assert 'exit_ts' not in raw and raw['terminal_liquidation'] is False
        assert raw['mark_ts'] == end and raw['mark_price'] == last['price']
        _equal(raw['gross_mark_bps'], gross, 'RAW_MARK_GROSS')
    else:
        assert raw['exit_ts'] == last['ts'] and raw['exit_price'] == last['price']
        assert raw['exit_reason'] == last['reason'] and qty == 0
        _equal(raw['gross_bps'], gross, 'RAW_CLOSED_GROSS')
    held = rows[ei:final_index if last['status'] == 'C' else final_index + 1]
    _equal(raw['mfe_bps'], max([0., (last['price'] / entry - 1) * 10000] +
                             [(r['high'] / entry - 1) * 10000 for r in held]), 'MFE_OBSERVED_PREFIX')
    _equal(raw['mae_bps'], min([0., (last['price'] / entry - 1) * 10000] +
                             [(r['low'] / entry - 1) * 10000 for r in held]), 'MAE_OBSERVED_PREFIX')
    if component_observations is not None:
        expected_keys = set(expected_obs)
        if set(slots) <= REPLACEMENTS:
            expected_keys = {k for k, (o, _) in expected_obs.items() if o['features']['actual_partial_filled']}
        seen = set()
        for observed in component_observations:
            key = (observed['source_slot'], observed['index'])
            assert key in expected_keys and key not in seen, 'SCREEN_OBSERVATION_COVERAGE'
            seen.add(key)
            expected, priority = expected_obs[key]
            _verify_observation(observed, expected)
            assert observed['source_exit_priority'] == priority, 'SCREEN_SOURCE_PRIORITY'
            assert observed['selected'] == (expected['trigger'] and not priority), 'SCREEN_SELECTED_TRIGGER'
        assert seen == expected_keys, 'MISSING_SCREEN_OBSERVATIONS'
    return dict(campaigns=1, trace_events=len(trace), unit_legs=len(fills), economic_replays=0)


def verify_screen_saved(raw, parent_raw, rows, cost, end):
    """Verify one symbol's Stage1 outputs supplied by the economic owner."""
    assert raw['events'] == parent_raw['events'], 'STAGE1_NEW_ADMISSION_OR_EVENT_CHANGE'
    actual, parent = _campaigns(raw), _campaigns(parent_raw)
    assert actual.keys() == parent.keys(), 'STAGE1_FIXED_ORIGINS'
    slot = raw['audit']['slot']
    assert raw['audit']['comparison_mode'] == SCREEN and 'capacity_timeline' not in raw
    assert raw['saved_parent_capacity_timeline'] == parent_raw.get('capacity_timeline', [])
    for field in ('source_lifecycle_replays', 'signal_generation_calls', 'occupancy_replays',
                  'new_exchange_orders', 'formal_credit'):
        assert raw['audit'][field] == 0, 'STAGE1_FORBIDDEN_' + field
    assert raw['audit']['canonical_candidate_number'] is None
    ntrace, nobs = 0, 0
    for i, record in actual.items():
        source = parent[i]
        for field in ('signal_index', 'signal_ts', 'entry_index', 'entry_ts', 'entry_price',
                      'side', 'fixed_floor', 'fixed_target', 'setup_id', 'allocation_numerator',
                      'allocation_denominator', 'allocated_normalized_qty', 'capacity_reuse_entry'):
            assert record[field] == source[field], 'STAGE1_FIXED_IDENTITY_' + field
        trace = [t for t in raw['trace'] if t['signal_index'] == i]
        obs = [t for t in raw['screen_trace'] if t['signal_index'] == i]
        verify_lifecycle_saved(record, trace, rows, cost, end, (slot,), obs)
        ntrace += len(trace)
        nobs += len(obs)
        assert record['screen_changed'] == (record['tm_legs'] != source['tm_legs'])
        partial = [l for l in record['tm_legs'] if l['reason'] == PARTIAL]
        assert all(l in source['tm_legs'] for l in partial), 'SOURCE_PARTIAL_CHANGED'
    assert ntrace == len(raw['trace']) and nobs == len(raw['screen_trace']), 'UNKNOWN_TRACE_ORIGIN'
    return dict(status='PASS', campaigns=len(actual), trace_events=ntrace,
                component_close_observations=nobs, new_admissions=0, allocation_changes=0,
                occupancy_replays=0, economic_replays=0)


def verify_money_saved(raw_by, result, packet):
    """Independently charge each saved actual/terminal unit leg including costs."""
    positions = {(r['symbol'], r['signal_index'], r['signal_ts']): (status, r)
                 for status, field in (('C', 'trades'), ('O', 'open_observations')) for r in result[field]}
    assert len(positions) == len(result['trades']) + len(result['open_observations']), 'UNIQUE_CASH_CAMPAIGNS'
    checked, total = set(), dict.fromkeys(old.a.bridge.VALUE_FIELDS, 0.)
    for symbol, rr in raw_by.items():
        for bare in _campaigns(rr).values():
            key = (symbol, bare['signal_index'], bare['signal_ts'])
            checked.add(key)
            status, row = positions[key]
            q = Fraction(bare['allocation_numerator'], bare['allocation_denominator'])
            assert 0 < q <= 1, 'POSITIVE_NORMALIZED_ENTRY_ALLOCATION'
            assert (status == 'C') == ('exit_ts' in bare)
            _equal(row['assembled_qty'], float(q), 'CASH_ASSEMBLED_QTY')
            values = dict.fromkeys(old.a.bridge.VALUE_FIELDS, 0.)
            assert len(bare['tm_legs']) == len(row['weighted_legs'])
            for leg, weighted in zip(bare['tm_legs'], row['weighted_legs'], strict=True):
                assert weighted['status'] == leg['status'], 'LEG_STATUS'
                w = float(q) * leg['qty']
                _equal(weighted['qty'], w, 'WEIGHTED_LEG_QTY')
                _equal(weighted['numerator'] / weighted['denominator'], w, 'WEIGHT_FRACTION')
                parts = old.independent_cost(packet['costs'][symbol], bare['entry_ts'], leg['ts'])
                cost = fsum(parts.values())
                gross = (leg['price'] / bare['entry_price'] - 1) * 10000
                expected = dict(gross_bps=gross, cost_bps=cost, net_bps=gross - cost,
                                cost2x_net_bps=gross - 2 * cost, **parts)
                unit = old.a.bridge._values((weighted['status'], weighted['row']))
                for field, value in expected.items():
                    _equal(unit[field], value, 'INDEPENDENT_UNIT_CASH_' + field)
                    values[field] += w * value
            aggregate = old.a.bridge._values((status, row))
            for field, value in values.items():
                _equal(aggregate[field], value, 'INDEPENDENT_CAMPAIGN_CASH_' + field)
                total[field] += value
    assert checked == positions.keys(), 'ALL_CASH_CAMPAIGNS_COVERED'
    _equal(result['metrics']['terminal_net_bps'], total['net_bps'], 'INDEPENDENT_TERMINAL_NET')
    _equal(result['metrics']['terminal_cost2x_net_bps'], total['cost2x_net_bps'], 'INDEPENDENT_TERMINAL_COST2')
    assert result['formal_credit'] == 0 and result['independent'] is False
    return dict(status='PASS', campaigns=len(checked), totals=total, economic_replays=0)


def verify_hashes(spec, root, inputs, evidence=None):
    root, inputs = Path(root), Path(inputs)
    counts = {}
    for group in ('source_files_sha256', 'preserved_files_sha256'):
        assert isinstance(spec[group], dict) and spec[group], 'MISSING_FROZEN_HASH_GROUP'
        for name, digest in spec[group].items():
            path = (root / name).resolve()
            assert path.is_relative_to(root.resolve()) and sha256(path.read_bytes()).hexdigest() == digest, group + ':' + name
        counts[group] = len(spec[group])
    for period, digest in spec['input_packet_sha256'].items():
        assert sha256((inputs / (period + '.json.gz')).read_bytes()).hexdigest() == digest, 'INPUT_PACKET_HASH'
    if evidence is not None and (Path(evidence) / 'EVIDENCE_HASHES.json').exists():
        hashes = json.loads((Path(evidence) / 'EVIDENCE_HASHES.json').read_text())
        for name, digest in hashes.items():
            assert sha256((Path(evidence) / name).read_bytes()).hexdigest() == digest, 'EVIDENCE_HASH:' + name
    return dict(status='PASS', **counts)


def verify_stage1_selection(table, registry, selection):
    """Independent per-window gates and deterministic <=3 survivor narrowing."""
    periods = ('DEV2025', 'SEEN2026')
    assert len(table) <= 8
    passed = []
    for slot, per_table in sorted(table.items()):
        assert set(per_table) == set(periods), 'SCREEN_BOTH_WINDOWS'
        eligible = True
        for per in periods:
            m = per_table[per]
            checks = dict(source=m['source_conformance'] == 'PASS', causal=m['causal_integrity'] == 'PASS',
                          normal_positive=m['normal_increment_bps'] > 0,
                          cost2_positive=m['cost2_increment_bps'] > 0,
                          ordinary_retained=m['ordinary_winner_retention'] is not None and m['ordinary_winner_retention'] >= .6,
                          top_decile_retained=m['top_decile_winner_retention'] is not None and m['top_decile_winner_retention'] >= .6,
                          positive_after_winner_cuts=m['normal_increment_bps'] > 0)
            assert selection['decisions'][slot][per] == dict(passed=all(checks.values()), checks=checks), 'INDEPENDENT_STAGE1_GATE'
            eligible &= all(checks.values())
        if eligible:
            passed.append(slot)
    assert selection['hard_gate_passed'] == passed
    if len(passed) <= 3:
        expected = sorted(passed)
    else:
        def vector(slot):
            return tuple(x for p in periods for x in (
                table[slot][p]['cost2_increment_bps'], table[slot][p]['ordinary_winner_retention'],
                table[slot][p]['top_decile_winner_retention'],
                table[slot][p]['loss_tail_worst_decile_mean_bps'] or 0.,
                -table[slot][p]['quantity_exposure_symbol_days']))
        vectors = {s: vector(s) for s in passed}
        frontier = [s for s in passed if not any(t != s and all(x >= y for x, y in zip(vectors[t], vectors[s]))
                    and any(x > y for x, y in zip(vectors[t], vectors[s])) for t in passed)]
        expected = sorted(frontier, key=lambda s: (
            {'A': 0, 'B': 1, 'C': 2}[registry[s]['performance_grade']],
            -fsum(table[s][p]['cost2_increment_bps'] for p in periods), s))[:3]
    assert selection['survivors'] == expected, 'INDEPENDENT_STAGE1_SURVIVORS'
    assert selection['pareto_or_deterministic_cap_excluded'] == sorted(set(passed) - set(expected))
    assert selection['FULL'] == selection['canonical_candidates'] == 0
    return dict(status='PASS', source_slots=len(table), survivors=expected)


def verify_history_saved(prior, budget, stage1_windows, full_windows):
    """Append-only historical trials and bounded, unique one-time observations."""
    for field in ('candidate_trials', 'trials'):
        assert budget[field][:len(prior[field])] == prior[field], 'PRIOR_HISTORY_CHANGED_' + field
    changed = {'candidate_trials', 'trials', 'cumulative_actual', 'cumulative_actual_evaluations',
               'squeeze_sprint_allocation'}
    for field in set(prior) - changed:
        assert budget[field] == prior[field], 'PRIOR_BUDGET_CHANGED_' + field
    new_candidates = budget['candidate_trials'][len(prior['candidate_trials']):]
    new_trials = budget['trials'][len(prior['trials']):]
    assert len(new_candidates) <= 4 and len(new_trials) <= 10, 'SPRINT_MAXIMUM_BUDGET'
    assert budget['cumulative_actual'] == prior['cumulative_actual'] + len(new_candidates)
    assert budget['cumulative_actual_evaluations'] == prior['cumulative_actual_evaluations'] + len(new_trials)
    assert len(stage1_windows) <= 16 and len(set(stage1_windows)) == len(stage1_windows)
    assert len(full_windows) <= 10 and len(set(full_windows)) == len(full_windows)
    assert len(new_trials) == len(full_windows), 'ACTUAL_FULL_TRIAL_COUNT'
    starts = budget['squeeze_sprint_allocation']['screen_window_starts']
    assert len(starts) == len(stage1_windows), 'STAGE1_START_COUNT'
    assert all(x['scope'] == SCOPE for x in new_candidates + new_trials), 'NEW_SCOPE_ONLY'
    return dict(status='PASS', preserved_candidates=len(prior['candidate_trials']),
                new_candidates=len(new_candidates), new_FULL=len(new_trials),
                screen_windows=len(stage1_windows), economic_replays=0)


def verify_receipt(folder, spec_digest):
    folder = Path(folder)
    receipt = json.loads((folder / 'RECEIPT.json').read_text())
    started = json.loads((folder / 'EXECUTION_STARTED.json').read_text())
    assert receipt['spec_sha256'] == spec_digest, 'RECEIPT_FROZEN_SPEC'
    assert started['spec_sha256'] == spec_digest, 'STARTED_FROZEN_SPEC'
    commit = receipt.get('freeze_commit', receipt.get('frozen_commit'))
    assert commit and commit == started.get('freeze_commit', started.get('frozen_commit')), 'SAME_FROZEN_EXECUTION_COMMIT'
    for name, digest in receipt['files'].items():
        path = (folder / name).resolve()
        assert path.is_relative_to(folder.resolve()), 'RECEIPT_PATH'
        assert sha256(path.read_bytes()).hexdigest() == digest, 'RECEIPT_FILE_' + name
    assert {'RAW.json.gz', 'RESULT.json.gz'} <= receipt['files'].keys(), 'RECEIPT_RAW_CASH_REQUIRED'
    return dict(status='PASS', freeze_commit=commit, files=len(receipt['files']))


def verify(hashes_only=False):
    """CLI is saved-only; --hashes-only never opens market or result packets."""
    from backend.research.rebuild import squeeze_sprint_account_v1 as c
    a, out = c.a, c.OUT
    spec = a.read(out / 'SPEC.json')
    hashes = verify_hashes(spec, a.ROOT, a.INPUTS, out)
    if 'challenge_sha256' in spec:
        assert a.h(out / 'CHALLENGE_WINDOW_SEALED.json') == spec['challenge_sha256'], 'CHALLENGE_PRESTAGE1_SEAL'
    if hashes_only:
        return dict(status='PASS_HASHES_ONLY', hashes=hashes, outcome_packets_decoded=0, economic_replays=0)
    if not any((out / 'STAGE1').glob('*/*/RAW.json.gz')):
        return dict(status='PREOUTCOME_NO_ECONOMIC_RESULTS', hashes=hashes,
                    outcome_packets_decoded=0, economic_replays=0)
    spec_digest = a.h(out / 'SPEC.json')
    table, stages, screens, fulls = {}, {}, [], []
    packets = {per: a.gz(a.INPUTS / (per + '.json.gz')) for per in c.PERIODS}
    parent_raw = {per: a.gz(c.cap.OUT / per / 'RAW.json.gz') for per in c.PERIODS}
    parent_result = {per: a.gz(c.cap.OUT / per / 'RESULT.json.gz') for per in c.PERIODS}
    for stage in ('STAGE1',):
        stages[stage] = {}
        stage_dir = out / stage
        if not stage_dir.exists():
            continue
        for slot_dir in sorted(p for p in stage_dir.iterdir() if p.is_dir()):
            slot = slot_dir.name
            assert {p.name for p in slot_dir.iterdir() if p.is_dir()} == set(c.PERIODS), 'BOTH_WINDOWS_ONCE'
            stages[stage][slot] = {}
            for per in c.PERIODS:
                folder, packet, cal = slot_dir / per, packets[per], spec['periods'][per]
                receipt = verify_receipt(folder, spec_digest)
                raw, result = a.gz(folder / 'RAW.json.gz'), a.gz(folder / 'RESULT.json.gz')
                assert set(raw) == set(parent_raw[per]), 'SAME_SYMBOL_UNIVERSE'
                check = verify_screen_saved
                symbols = {symbol: check(rr, parent_raw[per][symbol], packet['rows_by'][symbol],
                                         packet['costs'][symbol], cal['runoff_end_ms']) for symbol, rr in raw.items()}
                cash = verify_money_saved(raw, result, packet)
                assert a.metrics(result, packet, cal) == result['metrics'], 'SAVED_DAILY_MARK_METRICS'
                assert c.snapshot(result, parent_result[per]) == a.read(folder / 'SNAPSHOT.json'), 'SAVED_SNAPSHOT'
                for name in ('events', 'trace', 'screen_trace'):
                    assert result[name] == [dict(t, symbol=s) for s, rr in sorted(raw.items())
                                            for t in rr.get(name, [])], 'SAVED_TRACE_EXPORT_' + name
                if stage == 'STAGE1':
                    screens.append((slot, per))
                    metric = a.read(folder / 'SCREEN_METRICS.json')
                    assert c.screen_metrics(parent_result[per], result) == metric, 'SAVED_SCREEN_METRICS'
                    table.setdefault(slot, {})[per] = metric
                else:
                    fulls.append((stage, slot, per))
                    assert a.decomposition(parent_result[per], result) == a.read(folder / 'DECOMPOSITION.json'), 'SAVED_FULL_DECOMPOSITION'
                stages[stage][slot][per] = dict(symbols=symbols, money=cash, receipt=receipt)
    assert table, 'NO_SAVED_STAGE1_OUTPUTS'
    selection = verify_stage1_selection(table, a.read(out / 'SOURCE_REGISTRY.json'), a.read(out / 'STAGE1_SELECTION.json'))
    # Dedicated Stage2 verifier owns FULL lifecycle checks. This CLI counts its
    # saved receipts without replaying or reading those result packets.
    fulls = [(stage, folder.parent.name, folder.name) for stage in ('STAGE2', 'STAGE3')
             for folder in sorted((out / stage).glob('*/*')) if folder.is_dir() and (folder / 'RECEIPT.json').exists()]
    history = verify_history_saved(a.read(out / 'HISTORY_PRIOR.json'), a.read(out / 'BUDGET.json'), screens, fulls)
    return dict(status='PASS_SAVED_ONLY', stages=stages, hashes=hashes, stage1_selection=selection,
                history=history, economic_replays=0, parent_replays=0)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hashes-only', action='store_true')
    print(json.dumps(verify(parser.parse_args().hashes_only), indent=2, allow_nan=False))
