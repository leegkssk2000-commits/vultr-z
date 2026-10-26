"""No-order virtual BBO ledger: one common entry, independent comparison exits.

SQLite commits INSERT-only hash-linked events and its full checkpoint in one
FULL-synchronous WAL transaction. Bucket clocks never assert past fill times.
No broker/network APIs, actual funding, account NAV, or formal Shadow credit.
"""
from __future__ import annotations
from copy import deepcopy
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

SCHEMA = 'zel.delayed_bbo_40bp_virtual_shadow.v2'
TRACKS = ('native', 'runner')
COST = 40.0
HEX = re.compile(r'^[0-9a-f]{64}$')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def require(value, reason):
    if not value:
        raise ValueError(reason)


def number(value):
    require(not isinstance(value, bool) and isinstance(value, (int, float)), 'INVALID_NUMERIC_TYPE')
    require(math.isfinite(value), 'NONFINITE_NUMBER')
    return float(value)


def clock(value):
    require(isinstance(value, int) and not isinstance(value, bool) and value > 0, 'INVALID_CLOCK')
    return value


def sha(value):
    require(isinstance(value, str) and HEX.fullmatch(value), 'INVALID_EVIDENCE_SHA256')
    return value


def authority(state):
    require(state.get('order_calls') == 0 and state.get('real_broker_fills') == 0
            and state.get('formal_shadow') is False and state.get('account_NAV') is None,
            'VIRTUAL_AUTHORITY_CHANGED')
    for key in ('exchange_order_submitted', 'native_strategy_changed'):
        require(state.get(key, False) is False, 'VIRTUAL_AUTHORITY_CHANGED')
    for key in ('market_requests', 'API_calls', 'network_calls', 'credential_file_reads', 'g5_credit'):
        require(state.get(key, 0) == 0, 'VIRTUAL_NETWORK_ORDER_OR_CREDIT_CHANGED')


def initialize(state, *, upgrade=False):
    authority(state)
    if upgrade:
        require(not (state.get('positions') or state.get('closed_quote_marks') or state.get('pending')),
                'UNRESOLVED_PRIOR_OBSERVER_CANNOT_UPGRADE')
    require(state.get('virtual_shadow_schema') in (None, SCHEMA), 'VIRTUAL_SCHEMA_CHANGED')
    state['virtual_shadow_schema'] = SCHEMA
    for key in ('virtual_entries', 'virtual_exits', 'virtual_partials', 'virtual_censored', 'virtual_events', 'admission_acks'):
        state.setdefault(key, [])
    state.setdefault('positions', {})
    for key in ('virtual_open_T', 'virtual_entry_T', 'virtual_closed_T', 'virtual_censored_T',
                'runner_open_T', 'runner_closed_T', 'runner_censored_T', 'symbol_exposure_open_T',
                'virtual_partial_T', 'runner_partial_T'):
        state.setdefault(key, 0)
    for key in ('virtual_net_trade_bps_sum', 'virtual_net_R_sum', 'runner_net_trade_bps_sum', 'runner_net_R_sum',
                'virtual_partial_net_trade_bps_sum', 'virtual_partial_net_R_sum',
                'runner_partial_net_trade_bps_sum', 'runner_partial_net_R_sum'):
        state.setdefault(key, 0.0)
    state.setdefault('virtual_model_roundtrip_bps', COST)
    state.setdefault('native_next_open_parity', False)
    state.setdefault('native_exit_parity', False)
    verify(state)


def append(state, kind, body, event_id=None):
    event_id = event_id or digest({'kind': kind, 'body': body})
    require(isinstance(event_id, str) and event_id, 'INVALID_EVENT_ID')
    require(not any(e['event_id'] == event_id for e in state['virtual_events']), 'DUPLICATE_EVENT_ID')
    event = {'seq': len(state['virtual_events']), 'event_id': event_id, 'kind': kind,
             'body': deepcopy(body), 'previous_sha256': state['virtual_events'][-1]['event_sha256'] if state['virtual_events'] else None}
    event['event_sha256'] = digest(event)
    state['virtual_events'].append(event)


def tally(state):
    state['virtual_entry_T'] = len(state['virtual_entries'])
    state['symbol_exposure_open_T'] = len(state['positions'])
    for track, prefix in (('native', 'virtual'), ('runner', 'runner')):
        closed = [row for row in state['virtual_exits'] if row['track'] == track]
        partials = [row for row in state['virtual_partials'] if row['track'] == track]
        state[prefix + '_open_T'] = sum(track in pos['tracks'] for pos in state['positions'].values())
        state[prefix + '_closed_T'] = len(closed)
        state[prefix + '_censored_T'] = sum(row['track'] == track for row in state['virtual_censored'])
        state[prefix + '_net_trade_bps_sum'] = math.fsum(row['track_cumulative_net_bps_40_model'] for row in closed)
        state[prefix + '_net_R_sum'] = math.fsum(row['track_cumulative_net_R_40_model'] for row in closed)
        state[prefix + '_partial_T'] = len(partials)
        state[prefix + '_partial_net_trade_bps_sum'] = math.fsum(row['net_bps_40_model'] for row in partials)
        state[prefix + '_partial_net_R_sum'] = math.fsum(row['net_R_40_model'] for row in partials)


def validate_entry(entry):
    sha(entry['original_signal_digest']); sha(entry['source_quote_sha256'])
    require(isinstance(entry['symbol'], str) and entry['symbol'] and isinstance(entry['rule_id'], str) and entry['rule_id'], 'MISSING_SIGNAL_IDENTITY')
    require(entry['virtual_id'] == digest({'symbol': entry['symbol'], 'rule': entry['rule_id'],
                                          'signal': entry['original_signal_digest']}), 'VIRTUAL_SIGNAL_ID_CHANGED')
    decision, bucket, observed = (clock(entry[k]) for k in ('decision_ms', 'entry_quote_ts_ms', 'virtual_entry_observed_at_ms'))
    require(decision < bucket <= observed, 'ENTRY_NOT_POST_SIGNAL_OR_FUTURE')
    if entry['quote_received_at_ms'] is not None:
        require(bucket <= clock(entry['quote_received_at_ms']) <= observed, 'ENTRY_RECEIPT_CLOCK_INVALID')
    px, stop, risk = (number(entry[key]) for key in ('entry_ask', 'initial_stop', 'risk_price'))
    require(0 < stop < px and 0 < risk < px and math.isclose(risk, px - stop, rel_tol=1e-10, abs_tol=1e-10), 'INITIAL_RISK_GEOMETRY_INVALID')
    require(entry['source_quote_clock_kind'] == 'BUCKET_END' and entry['model_roundtrip_cost_bps'] == COST, 'ENTRY_CLOCK_OR_COST_MODEL_CHANGED')


def exit_math(entry, bid):
    bid = number(bid)
    require(bid > 0, 'INVALID_EXIT_BID')
    px, risk = number(entry['entry_ask']), number(entry['risk_price'])
    gross = 10000 * (bid / px - 1)
    net = gross - COST
    net_r = ((bid - px) - px * COST / 10000) / risk
    require(math.isclose(net_r, net / (10000 * risk / px), rel_tol=1e-9, abs_tol=1e-9), 'INDEPENDENT_R_CHECK_FAILED')
    return gross, net, net_r


def validate_exit(entry, row):
    require(row['track'] in TRACKS and row['virtual_id'] == entry['virtual_id']
            and row['symbol'] == entry['symbol'] and row['rule_id'] == entry['rule_id'], 'UNMATCHED_VIRTUAL_CLOSE')
    sha(row['source_quote_sha256'])
    bucket, observed = clock(row['exit_quote_ts_ms']), clock(row['virtual_exit_observed_at_ms'])
    require(entry['entry_quote_ts_ms'] < bucket <= observed
            and entry['virtual_entry_observed_at_ms'] < observed, 'RETROACTIVE_VIRTUAL_CLOSE')
    if row['quote_received_at_ms'] is not None:
        require(bucket <= clock(row['quote_received_at_ms']) <= observed, 'EXIT_RECEIPT_CLOCK_INVALID')
    fraction = number(row['closed_fraction'])
    require(0 < fraction <= 1, 'INVALID_CLOSED_FRACTION')
    for key, expected in zip(('gross_bps', 'net_bps_40_model', 'net_R_40_model'), exit_math(entry, row['exit_bid'])):
        require(math.isclose(number(row[key]), expected * fraction, rel_tol=1e-9, abs_tol=1e-8), 'INDEPENDENT_NET_OR_R_MISMATCH')
    require(math.isclose(number(row['charged_model_cost_bps']), COST * fraction, abs_tol=1e-9), 'FRACTION_COST_MISMATCH')
    if row.get('partial_decision_ts_ms') is not None:
        require(clock(row['partial_decision_ts_ms']) < bucket and row['partial_decision_ts_ms'] < observed,
                'PARTIAL_REQUIRES_LATER_OBSERVED_QUOTE')
        require(row['partial_decision_ts_ms'] >= entry['virtual_entry_observed_at_ms'], 'PARTIAL_DECISION_BEFORE_ENTRY_OBSERVED')
    require(row['model_roundtrip_cost_bps'] == COST and row['source_quote_clock_kind'] == 'BUCKET_END'
            and row['funding_actual_verified'] is False and row['native_exit_parity'] is False,
            'VIRTUAL_EXIT_AUTHORITY_CHANGED')


def verify(state):
    authority(state)
    require(state.get('virtual_shadow_schema') == SCHEMA and state.get('virtual_model_roundtrip_bps') == COST, 'VIRTUAL_SCHEMA_OR_COST_CHANGED')
    require(state.get('native_next_open_parity') is False and state.get('native_exit_parity') is False, 'VIRTUAL_PARITY_AUTHORITY_CHANGED')
    previous, event_ids, reconstructed = None, set(), {'ENTRY': [], 'EXIT': [], 'PARTIAL': [], 'CENSOR': [], 'ADMISSION_ACK': []}
    last_observed, introduced, terminated = 0, set(), set()
    for seq, event in enumerate(state['virtual_events']):
        body = {key: value for key, value in event.items() if key != 'event_sha256'}
        require(event['seq'] == seq and event['previous_sha256'] == previous and digest(body) == event['event_sha256'], 'EVENT_HASH_CHAIN_INVALID')
        require(event['event_id'] not in event_ids and event['kind'] in reconstructed, 'DUPLICATE_OR_INVALID_EVENT')
        record = event['body']
        observed = clock(record[{'ENTRY': 'virtual_entry_observed_at_ms', 'EXIT': 'virtual_exit_observed_at_ms', 'PARTIAL': 'virtual_exit_observed_at_ms', 'CENSOR': 'observed_at_ms', 'ADMISSION_ACK': 'acknowledgement_ts_ms'}[event['kind']]])
        require(observed >= last_observed, 'EVENT_OBSERVATION_CLOCK_ROLLBACK')
        last_observed = observed
        if event['kind'] == 'ENTRY':
            introduced.add(record['virtual_id'])
        elif event['kind'] != 'ADMISSION_ACK':
            require(record['virtual_id'] in introduced, 'TERMINAL_BEFORE_ENTRY_EVENT')
            pair = (record['virtual_id'], record['track'])
            require(pair not in terminated, 'FILL_AFTER_TRACK_TERMINAL')
            if event['kind'] in ('EXIT', 'CENSOR'):
                terminated.add(pair)
        event_ids.add(event['event_id']); previous = event['event_sha256']
        reconstructed[event['kind']].append(event['body'])
    for kind, key in (('ENTRY', 'virtual_entries'), ('EXIT', 'virtual_exits'), ('PARTIAL', 'virtual_partials'), ('CENSOR', 'virtual_censored'), ('ADMISSION_ACK', 'admission_acks')):
        require(reconstructed[kind] == state[key], 'EVENT_CHECKPOINT_RECORD_MISMATCH')
    entries = {}
    for entry in state['virtual_entries']:
        validate_entry(entry)
        require(entry['virtual_id'] not in entries, 'DUPLICATE_VIRTUAL_SIGNAL')
        entries[entry['virtual_id']] = entry
    ack_ids, original_ack_ids = set(), set()
    entry_events = {event['event_sha256']: event for event in state['virtual_events'] if event['kind'] == 'ENTRY'}
    ack_events = {event['body']['ack_sha256']: event for event in state['virtual_events'] if event['kind'] == 'ADMISSION_ACK'}
    for ack in state['admission_acks']:
        body = {key: value for key, value in ack.items() if key != 'ack_sha256'}
        require(digest(body) == sha(ack['ack_sha256']), 'ADMISSION_ACK_HASH_INVALID')
        sha(ack['original_signal_digest']); sha(ack['source_evidence_sha256'])
        signal_id = digest({'symbol': ack['symbol'], 'rule': ack['rule_id'], 'signal': ack['original_signal_digest']})
        require(ack['signal_id'] == signal_id and signal_id not in ack_ids
                and ack['original_signal_digest'] not in original_ack_ids, 'DUPLICATE_OR_INVALID_ADMISSION_ACK')
        ack_ids.add(signal_id)
        original_ack_ids.add(ack['original_signal_digest'])
        require(type(ack['accepted']) is bool and isinstance(ack['reason'], str) and ack['reason']
                and clock(ack['acknowledgement_ts_ms']) >= clock(ack['decision_ms']), 'ADMISSION_ACK_IDENTITY_OR_CLOCK_INVALID')
        require(isinstance(ack['symbol'], str) and ack['symbol'] and isinstance(ack['rule_id'], str) and ack['rule_id'], 'ADMISSION_ACK_IDENTITY_OR_CLOCK_INVALID')
        if ack['accepted']:
            event = entry_events.get(ack['source_entry_event_sha256'])
            require(event is not None and ack['source_entry_virtual_id'] == signal_id, 'ADMISSION_ACK_ENTRY_EVENT_UNBOUND')
            require(event['seq'] < ack_events[ack['ack_sha256']]['seq'], 'ADMISSION_ACK_BEFORE_ENTRY_EVENT')
            entry = event['body']
            require(entry['virtual_id'] == signal_id and entry['decision_ms'] == ack['decision_ms']
                    and entry['virtual_entry_observed_at_ms'] == ack['acknowledgement_ts_ms']
                    and entry['source_quote_sha256'] == ack['source_evidence_sha256'], 'ADMISSION_ACK_ENTRY_EVIDENCE_MISMATCH')
        else:
            require(ack['source_entry_event_sha256'] is None and ack['source_entry_virtual_id'] is None
                    and signal_id not in entries, 'REJECTED_ACK_HAS_ENTRY')
    require(set(entries).issubset(ack_ids), 'ENTRY_WITHOUT_ATOMIC_ADMISSION_ACK')
    parts = {}
    for row in state['virtual_partials']:
        pair = (row['virtual_id'], row['track'])
        require(pair[0] in entries, 'PARTIAL_WITHOUT_ENTRY')
        validate_exit(entries[pair[0]], row)
        parts.setdefault(pair, []).append(row)
        require(math.fsum(x['closed_fraction'] for x in parts[pair]) < 1, 'PARTIAL_EXCEEDS_REMAINING')
        for key, cumulative in [('net_bps_40_model', 'track_cumulative_net_bps_40_model'), ('net_R_40_model', 'track_cumulative_net_R_40_model')]:
            require(math.isclose(number(row[cumulative]), math.fsum(x[key] for x in parts[pair]), abs_tol=1e-8), 'PARTIAL_CUMULATIVE_ACCOUNTING')
    finished = set()
    for row in state['virtual_exits'] + state['virtual_censored']:
        pair = (row['virtual_id'], row['track'])
        require(pair not in finished and pair[0] in entries and pair[1] in TRACKS, 'DUPLICATE_OR_UNKNOWN_TRACK_TERMINAL')
        finished.add(pair)
        if 'net_bps_40_model' in row:
            validate_exit(entries[pair[0]], row)
            previous_parts = parts.get(pair, [])
            require(math.isclose(math.fsum(x['closed_fraction'] for x in previous_parts) + row['closed_fraction'], 1, abs_tol=1e-10), 'TERMINAL_FRACTION_ACCOUNTING')
            for key, cumulative in [('net_bps_40_model', 'track_cumulative_net_bps_40_model'), ('net_R_40_model', 'track_cumulative_net_R_40_model')]:
                require(math.isclose(number(row[cumulative]), math.fsum(x[key] for x in previous_parts) + row[key], abs_tol=1e-8), 'TERMINAL_CUMULATIVE_ACCOUNTING')
        else:
            require(clock(row['observed_at_ms']) >= entries[pair[0]]['virtual_entry_observed_at_ms']
                    and row['state'] == 'UNKNOWN_NO_RETRO_BID_FILL'
                    and row['symbol'] == entries[pair[0]]['symbol'] and row['rule_id'] == entries[pair[0]]['rule_id']
                    and row['last_source_quote_ts_ms'] >= entries[pair[0]]['entry_quote_ts_ms']
                    and row['last_quote_read_at_ms'] >= entries[pair[0]]['virtual_entry_observed_at_ms']
                    and clock(row['last_source_quote_ts_ms']) <= clock(row['last_quote_read_at_ms']) <= row['observed_at_ms'], 'INVALID_CENSOR_CLOCK_OR_CLAIM')
            require(math.isclose(number(row['remaining_fraction']), 1 - math.fsum(x['closed_fraction'] for x in parts.get(pair, [])), abs_tol=1e-10), 'CENSOR_FRACTION_ACCOUNTING')
            for key, cumulative in [('net_bps_40_model', 'known_partial_net_bps_40_model'), ('net_R_40_model', 'known_partial_net_R_40_model')]:
                require(math.isclose(number(row[cumulative]), math.fsum(x[key] for x in parts.get(pair, [])), abs_tol=1e-8), 'CENSOR_PARTIAL_ACCOUNTING')
    active = set()
    for symbol, pos in state['positions'].items():
        require(pos['virtual_id'] in entries and symbol == pos['symbol'], 'UNKNOWN_ACTIVE_POSITION')
        entry = entries[pos['virtual_id']]
        require(pos['symbol'] == entry['symbol'] and pos['rule_id'] == entry['rule_id'], 'POSITION_IDENTITY_CHANGED')
        require(pos['tracks'] and set(pos['tracks']).issubset(TRACKS), 'INVALID_ACTIVE_TRACKS')
        for track, item in pos['tracks'].items():
            require(item['virtual_id'] == pos['virtual_id'] and item['symbol'] == symbol
                    and item['rule_id'] == entry['rule_id'], 'TRACK_IDENTITY_CHANGED')
            for key, saved in [('entry_ask_price', 'entry_ask'), ('base_stop_price', 'initial_stop'),
                               ('initial_risk_price', 'risk_price'), ('entry_quote_ts_ms', 'entry_quote_ts_ms'),
                               ('quote_read_at_ms', 'virtual_entry_observed_at_ms'), ('original_signal_digest', 'original_signal_digest')]:
                require(item[key] == entry[saved], 'TRACK_ENTRY_CHANGED')
            require(clock(item['last_quote_ts_ms']) >= entry['entry_quote_ts_ms']
                    and clock(item['last_quote_read_at_ms']) >= entry['virtual_entry_observed_at_ms']
                    and item['last_quote_ts_ms'] <= item['last_quote_read_at_ms'], 'TRACK_CLOCK_INVALID')
            require(item['cost_assumption_roundtrip_bps'] == COST and item['formal_shadow'] is False
                    and item['real_broker_fill'] is False, 'TRACK_AUTHORITY_OR_COST_CHANGED')
            active.add((pos['virtual_id'], track))
            require(math.isclose(number(item['remaining_fraction']), 1 - math.fsum(x['closed_fraction'] for x in parts.get((pos['virtual_id'], track), [])), abs_tol=1e-10), 'ACTIVE_FRACTION_ACCOUNTING')
            for key, cumulative in [('net_bps_40_model', 'cumulative_realized_net_bps_40_model'), ('net_R_40_model', 'cumulative_realized_net_R_40_model')]:
                require(math.isclose(number(item[cumulative]), math.fsum(x[key] for x in parts.get((pos['virtual_id'], track), [])), abs_tol=1e-8), 'ACTIVE_CUMULATIVE_ACCOUNTING')
    require(not active & finished and active | finished == {(key, track) for key in entries for track in TRACKS}, 'VIRTUAL_EXPOSURE_ACCOUNTING_INVALID')
    expected = deepcopy(state); tally(expected)
    for key in ('virtual_open_T', 'virtual_entry_T', 'virtual_closed_T', 'virtual_censored_T',
                'runner_open_T', 'runner_closed_T', 'runner_censored_T',
                'virtual_net_trade_bps_sum', 'virtual_net_R_sum', 'runner_net_trade_bps_sum', 'runner_net_R_sum',
                'symbol_exposure_open_T', 'virtual_partial_T', 'runner_partial_T',
                'virtual_partial_net_trade_bps_sum', 'virtual_partial_net_R_sum',
                'runner_partial_net_trade_bps_sum', 'runner_partial_net_R_sum'):
        require(state[key] == expected[key], 'VIRTUAL_TALLY_INVALID:' + key)
    canonical(state)


def enter(state, position, *, event_id=None):
    verify(state)
    require(position.get('formal_shadow') is False and position.get('real_broker_fill') is False
            and position.get('original_next_open_fill_verified') is False
            and position.get('cost_assumption_roundtrip_bps') == COST, 'ENTRY_AUTHORITY_OR_COST_CHANGED')
    symbol = position['symbol']
    virtual_id = digest({'symbol': symbol, 'rule': position['rule_id'], 'signal': position['original_signal_digest']})
    entry = {'virtual_id': virtual_id, 'rule_id': position['rule_id'], 'symbol': symbol,
        'original_signal_digest': position['original_signal_digest'], 'decision_ms': position['decision_ms'],
        'entry_quote_ts_ms': position['entry_quote_ts_ms'], 'virtual_entry_observed_at_ms': position['quote_read_at_ms'],
        'quote_received_at_ms': position.get('quote_received_at_ms'), 'source_quote_clock_kind': position['source_quote_clock_kind'],
        'entry_ask': position['entry_ask_price'], 'initial_stop': position['base_stop_price'],
        'risk_price': position['initial_risk_price'], 'source_quote_sha256': position['quote_entry_sha256'],
        'model_roundtrip_cost_bps': COST, 'fill_type': 'SIMULATED_OBSERVED_LATE_BBO_ASK_NO_BROKER_FILL'}
    validate_entry(entry)
    prior = next((x for x in state['virtual_entries'] if x['virtual_id'] == virtual_id), None)
    if prior is not None:
        require(prior == entry, 'DUPLICATE_VIRTUAL_SIGNAL_DIFFERENT_QUOTE')
        return virtual_id
    require(symbol not in state['positions'], 'DUPLICATE_SYMBOL_POSITION')
    candidate = deepcopy(state)
    p = deepcopy(position); p['virtual_id'] = virtual_id
    p.setdefault('last_quote_read_at_ms', p['quote_read_at_ms'])
    p['remaining_fraction'] = 1.0
    p['cumulative_realized_net_bps_40_model'] = 0.0
    p['cumulative_realized_net_R_40_model'] = 0.0
    candidate['positions'][symbol] = {**p, 'tracks': {track: deepcopy(p) for track in TRACKS}}
    candidate['virtual_entries'].append(entry); append(candidate, 'ENTRY', entry, event_id)
    _ack(candidate, position, accepted=True, reason='VIRTUAL_ENTRY_ACCEPTED', at_ms=position['quote_read_at_ms'],
         evidence_sha256=position['quote_entry_sha256'], entry_event_sha256=candidate['virtual_events'][-1]['event_sha256'])
    tally(candidate); verify(candidate); state.clear(); state.update(candidate)
    return virtual_id


def _ack(state, event, *, accepted, reason, at_ms, evidence_sha256, entry_event_sha256=None):
    require(type(accepted) is bool and isinstance(reason, str) and reason, 'ADMISSION_ACK_ACCEPTANCE_OR_REASON_INVALID')
    sha(event['original_signal_digest']); sha(evidence_sha256)
    require(isinstance(event['rule_id'], str) and event['rule_id']
            and isinstance(event['symbol'], str) and event['symbol'], 'ADMISSION_ACK_IDENTITY_OR_CLOCK_INVALID')
    require(clock(at_ms) >= clock(event['decision_ms']), 'ADMISSION_ACK_BEFORE_DECISION')
    signal_id = digest({'symbol': event['symbol'], 'rule': event['rule_id'], 'signal': event['original_signal_digest']})
    if accepted:
        sha(entry_event_sha256)
    else:
        require(entry_event_sha256 is None, 'REJECTED_ACK_HAS_ENTRY')
    ack = {'signal_id': signal_id, 'original_signal_digest': event['original_signal_digest'],
           'rule_id': event['rule_id'], 'symbol': event['symbol'], 'decision_ms': event['decision_ms'],
           'acknowledgement_ts_ms': at_ms, 'accepted': accepted, 'reason': reason,
           'source_entry_event_sha256': entry_event_sha256,
           'source_entry_virtual_id': signal_id if accepted else None,
           'source_evidence_sha256': evidence_sha256}
    ack['ack_sha256'] = digest(ack)
    previous = next((x for x in state['admission_acks'] if x['signal_id'] == signal_id), None)
    if previous is not None:
        require(previous == ack, 'CONFLICTING_ADMISSION_ACK')
        return deepcopy(previous)
    state['admission_acks'].append(ack)
    append(state, 'ADMISSION_ACK', ack, 'admission:' + signal_id)
    return deepcopy(ack)


def ack_signal(state, event, *, accepted, reason, at_ms, evidence_sha256, entry_event_sha256=None):
    """Durable accepted/rejected acknowledgement; no inference from missing ACK."""
    verify(state)
    candidate = deepcopy(state)
    ack = _ack(candidate, event, accepted=accepted, reason=reason, at_ms=at_ms,
               evidence_sha256=evidence_sha256, entry_event_sha256=entry_event_sha256)
    verify(candidate); state.clear(); state.update(candidate)
    return ack


def _fill_row(entry, evidence, track, fraction, previous_parts, *, partial=False):
    gross, net, net_r = exit_math(entry, evidence['terminal_bid_price'])
    for key, expected in [('observational_net_bps_at_40bp', net), ('observational_net_R', net_r)]:
        require(math.isclose(number(evidence[key]), expected, rel_tol=1e-9, abs_tol=1e-8), 'INDEPENDENT_NET_OR_R_MISMATCH')
    require(evidence.get('real_trade') is False and evidence.get('order_calls') == 0, 'EXIT_AUTHORITY_CHANGED')
    row = {'virtual_id': entry['virtual_id'], 'track': track, 'symbol': evidence['symbol'], 'rule_id': evidence['rule_id'],
        'entry_quote_ts_ms': entry['entry_quote_ts_ms'], 'virtual_entry_observed_at_ms': entry['virtual_entry_observed_at_ms'],
        'exit_quote_ts_ms': evidence['terminal_quote_ts_ms'], 'virtual_exit_observed_at_ms': evidence['read_at_ms'],
        'quote_received_at_ms': evidence.get('terminal_received_at_ms'), 'source_quote_clock_kind': evidence['source_quote_clock_kind'],
        'exit_bid': evidence['terminal_bid_price'], 'gross_bps': gross * fraction,
        'net_bps_40_model': net * fraction, 'net_R_40_model': net_r * fraction,
        'closed_fraction': fraction, 'charged_model_cost_bps': COST * fraction,
        'track_cumulative_net_bps_40_model': math.fsum(x['net_bps_40_model'] for x in previous_parts) + net * fraction,
        'track_cumulative_net_R_40_model': math.fsum(x['net_R_40_model'] for x in previous_parts) + net_r * fraction,
        'model_roundtrip_cost_bps': COST, 'reason': evidence['reason'], 'source_quote_sha256': evidence['source_quote_sha256'],
        'partial_decision_ts_ms': evidence.get('partial_decision_ts_ms'), 'partial_fill': partial,
        'fill_type': 'SIMULATED_OBSERVED_BBO_BID_NOT_BROKER_FILL', 'intrabar_path_verified': False,
        'funding_actual_verified': False, 'native_exit_parity': False}
    validate_exit(entry, row)
    return row


def _fill(state, evidence, track, event_id, partial):
    verify(state); require(track in TRACKS, 'UNKNOWN_TRACK')
    symbol = evidence['symbol']; pos = state['positions'].get(symbol)
    target = evidence.get('virtual_id') or (pos['virtual_id'] if pos else None)
    kind, table = ('PARTIAL', 'virtual_partials') if partial else ('EXIT', 'virtual_exits')
    if target is None:
        previous = [x for x in (state[table] + (state['virtual_exits'] if partial else [])) if x['symbol'] == symbol and x['track'] == track
                    and x['rule_id'] == evidence['rule_id'] and x['exit_quote_ts_ms'] == evidence['terminal_quote_ts_ms']
                    and x['source_quote_sha256'] == evidence['source_quote_sha256']]
        require(len(previous) == 1, 'UNMATCHED_VIRTUAL_CLOSE'); target = previous[0]['virtual_id']
    entry = next((x for x in state['virtual_entries'] if x['virtual_id'] == target), None)
    require(entry is not None, 'UNMATCHED_VIRTUAL_CLOSE')
    previous_parts = [x for x in state['virtual_partials'] if x['virtual_id'] == target and x['track'] == track]
    if partial:
        decision = clock(evidence['partial_decision_ts_ms'])
        fraction = number(evidence['partial_fraction'])
        completed = next((x for x in state['virtual_exits'] if x['virtual_id'] == target
                          and x['track'] == track and x.get('partial_decision_ts_ms') == decision), None)
        if completed is not None:
            require(math.isclose(fraction, completed['closed_fraction'], abs_tol=1e-12), 'CONFLICTING_PARTIAL_RETRY')
            row = _fill_row(entry, evidence, track, completed['closed_fraction'], previous_parts)
            require(completed == row, 'CONFLICTING_PARTIAL_RETRY'); return deepcopy(completed)
        prior = next((x for x in previous_parts if x['partial_decision_ts_ms'] == decision), None)
        if prior is not None:
            prefix = previous_parts[:previous_parts.index(prior)]
            row = _fill_row(entry, evidence, track, fraction, prefix, partial=True)
            require(prior == row, 'CONFLICTING_PARTIAL_RETRY'); return deepcopy(prior)
    else:
        fraction = 1 - math.fsum(x['closed_fraction'] for x in previous_parts)
        prior = next((x for x in state['virtual_exits'] if x['virtual_id'] == target and x['track'] == track), None)
        if prior is not None:
            row = _fill_row(entry, evidence, track, fraction, previous_parts)
            require(prior == row, 'CONFLICTING_TRACK_TERMINAL'); return deepcopy(prior)
    require(pos is not None and pos['virtual_id'] == target and track in pos['tracks'], 'UNMATCHED_ACTIVE_TRACK')
    item = pos['tracks'][track]
    remaining = number(item['remaining_fraction'])
    require(0 < fraction <= remaining + 1e-12, 'PARTIAL_EXCEEDS_REMAINING')
    if partial and math.isclose(fraction, remaining, abs_tol=1e-12):
        # A requested partial that exhausts the remainder is a completed exit.
        kind, table, partial, fraction = 'EXIT', 'virtual_exits', False, remaining
    row = _fill_row(entry, evidence, track, fraction, previous_parts, partial=partial)
    require(row['exit_quote_ts_ms'] >= item['last_quote_ts_ms'] and row['virtual_exit_observed_at_ms'] >= item['last_quote_read_at_ms'], 'EXIT_OBSERVATION_CLOCK_ROLLBACK')
    candidate = deepcopy(state)
    candidate[table].append(row); append(candidate, kind, row, event_id)
    if partial:
        updated = candidate['positions'][symbol]['tracks'][track]
        updated['remaining_fraction'] = remaining - fraction
        updated['cumulative_realized_net_bps_40_model'] = row['track_cumulative_net_bps_40_model']
        updated['cumulative_realized_net_R_40_model'] = row['track_cumulative_net_R_40_model']
        updated['last_quote_ts_ms'] = row['exit_quote_ts_ms']
        updated['last_quote_read_at_ms'] = row['virtual_exit_observed_at_ms']
    else:
        del candidate['positions'][symbol]['tracks'][track]
        if not candidate['positions'][symbol]['tracks']:
            del candidate['positions'][symbol]
    tally(candidate); verify(candidate); state.clear(); state.update(candidate)
    return deepcopy(row)


def exit_at_bid(state, evidence, *, track='native', event_id=None):
    return _fill(state, evidence, track, event_id, False)


def partial_at_bid(state, evidence, *, track='native', event_id=None):
    return _fill(state, evidence, track, event_id, True)


def censor(state, symbol, reason, *, track=None, at_ms=None, event_id=None):
    verify(state); require(track is None or track in TRACKS, 'UNKNOWN_TRACK')
    require(isinstance(reason, str) and reason, 'CENSOR_REASON_REQUIRED')
    at = clock(at_ms)
    pos = state['positions'].get(symbol)
    chosen = [track] if track else list(TRACKS)
    if pos is None:
        previous = [x for x in state['virtual_censored'] if x['symbol'] == symbol and x['reason'] == reason
                    and x['observed_at_ms'] == at and x['track'] in chosen]
        require(previous, 'NO_POSITION_TO_CENSOR'); return deepcopy(previous)
    candidate, rows = deepcopy(state), []
    for selected in chosen:
        if selected not in pos['tracks']:
            previous = next((x for x in state['virtual_censored'] if x['virtual_id'] == pos['virtual_id']
                and x['track'] == selected and x['reason'] == reason and x['observed_at_ms'] == at), None)
            if previous is not None:
                rows.append(deepcopy(previous))
            continue
        item = pos['tracks'][selected]
        require(at >= item['last_quote_read_at_ms'], 'CENSOR_OBSERVATION_CLOCK_ROLLBACK')
        row = {'virtual_id': pos['virtual_id'], 'track': selected, 'rule_id': pos['rule_id'], 'symbol': symbol,
            'reason': reason, 'state': 'UNKNOWN_NO_RETRO_BID_FILL', 'observed_at_ms': at,
            'last_source_quote_ts_ms': item['last_quote_ts_ms'], 'last_quote_read_at_ms': item['last_quote_read_at_ms'],
            'net_bps_40_model_unavailable': None, 'net_R_unavailable': None,
            'remaining_fraction': item['remaining_fraction'],
            'known_partial_net_bps_40_model': item['cumulative_realized_net_bps_40_model'],
            'known_partial_net_R_40_model': item['cumulative_realized_net_R_40_model']}
        candidate['virtual_censored'].append(row)
        append(candidate, 'CENSOR', row, (event_id + ':' + selected) if event_id else None)
        del candidate['positions'][symbol]['tracks'][selected]; rows.append(row)
    require(rows, 'NO_ACTIVE_TRACK_TO_CENSOR')
    if not candidate['positions'][symbol]['tracks']:
        del candidate['positions'][symbol]
    tally(candidate); verify(candidate); state.clear(); state.update(candidate)
    return deepcopy(rows)


class Store:
    """Exclusive single writer; SQLite is authoritative after interrupted status IO."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = self.path.with_suffix(self.path.suffix + '.writer.lock').open('a+b')
        self.db = None
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.db = sqlite3.connect(self.path, timeout=0, isolation_level=None)
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,
                    event_sha256 TEXT NOT NULL UNIQUE, payload TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS no_event_update BEFORE UPDATE ON events
                    BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_EVENTS'); END;
                CREATE TRIGGER IF NOT EXISTS no_event_delete BEFORE DELETE ON events
                    BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_EVENTS'); END;
                CREATE TABLE IF NOT EXISTS checkpoint (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL,
                    state_sha256 TEXT NOT NULL, event_count INTEGER NOT NULL,
                    head_sha256 TEXT, payload TEXT NOT NULL);
            ''')
            self.revision = 0
            self.current = self.load()
        except Exception:
            self.close(); raise

    def load(self):
        require(self.db.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'SQLITE_INTEGRITY_INVALID')
        row = self.db.execute('SELECT revision,state_sha256,event_count,head_sha256,payload FROM checkpoint WHERE singleton=1').fetchone()
        events = self.db.execute('SELECT seq,event_id,event_sha256,payload FROM events ORDER BY seq').fetchall()
        if row is None:
            require(not events, 'EVENTS_WITHOUT_ATOMIC_CHECKPOINT')
            self.revision = 0; self.current = None; return None
        revision, checksum, count, head, raw = row
        state = json.loads(raw); verify(state)
        require(digest(state) == checksum and len(events) == count == len(state['virtual_events']), 'CHECKPOINT_HASH_OR_EVENT_COUNT_INVALID')
        for expected, stored in zip(state['virtual_events'], events):
            require((expected['seq'], expected['event_id'], expected['event_sha256'], canonical(expected)) == stored, 'SQLITE_EVENT_CHECKPOINT_MISMATCH')
        require(head == (state['virtual_events'][-1]['event_sha256'] if events else None), 'CHECKPOINT_HEAD_INVALID')
        self.revision = revision; self.current = deepcopy(state)
        return deepcopy(state)

    def commit(self, state):
        verify(state)
        prior = self.current
        old_events = prior['virtual_events'] if prior else []
        require(state['virtual_events'][:len(old_events)] == old_events, 'APPEND_ONLY_PREFIX_CHANGED')
        if prior:
            for event in state['virtual_events'][len(old_events):]:
                if event['kind'] not in ('EXIT', 'PARTIAL', 'CENSOR'):
                    continue
                row = event['body']; pos = prior['positions'].get(row['symbol'])
                if pos is None or pos['virtual_id'] != row['virtual_id'] or row['track'] not in pos['tracks']:
                    continue
                old = pos['tracks'][row['track']]
                observed = row['virtual_exit_observed_at_ms'] if event['kind'] in ('EXIT', 'PARTIAL') else row['observed_at_ms']
                source = row['exit_quote_ts_ms'] if event['kind'] in ('EXIT', 'PARTIAL') else row['last_source_quote_ts_ms']
                require(observed >= old['last_quote_read_at_ms'] and source >= old['last_quote_ts_ms'],
                        'CHECKPOINT_TERMINAL_CLOCK_ROLLBACK')
            for symbol, pos in prior['positions'].items():
                next_pos = state['positions'].get(symbol)
                if next_pos is None or next_pos['virtual_id'] != pos['virtual_id']:
                    continue
                for track, item in pos['tracks'].items():
                    if track in next_pos['tracks']:
                        following = next_pos['tracks'][track]
                        require(following['last_quote_ts_ms'] >= item['last_quote_ts_ms']
                                and following['last_quote_read_at_ms'] >= item['last_quote_read_at_ms'], 'CHECKPOINT_OBSERVATION_CLOCK_ROLLBACK')
            if 'updated_at_ms' in prior and 'updated_at_ms' in state:
                require(clock(state['updated_at_ms']) >= clock(prior['updated_at_ms']), 'CHECKPOINT_OBSERVATION_CLOCK_ROLLBACK')
        raw, checksum = canonical(state), digest(state)
        if prior is not None and checksum == digest(prior):
            return self.revision
        try:
            self.db.execute('BEGIN IMMEDIATE')
            existing = self.db.execute('SELECT revision FROM checkpoint WHERE singleton=1').fetchone()
            require((existing[0] if existing else 0) == self.revision, 'STALE_CHECKPOINT_REVISION')
            for event in state['virtual_events'][len(old_events):]:
                self.db.execute('INSERT INTO events VALUES(?,?,?,?)', (event['seq'], event['event_id'], event['event_sha256'], canonical(event)))
            revision = self.revision + 1
            head = state['virtual_events'][-1]['event_sha256'] if state['virtual_events'] else None
            self.db.execute('INSERT INTO checkpoint VALUES(1,?,?,?,?,?) ON CONFLICT(singleton) DO UPDATE SET revision=excluded.revision,state_sha256=excluded.state_sha256,event_count=excluded.event_count,head_sha256=excluded.head_sha256,payload=excluded.payload',
                            (revision, checksum, len(state['virtual_events']), head, raw))
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            raise
        self.revision = revision; self.current = deepcopy(state)
        return self.revision

    def close(self):
        if self.db is not None:
            self.db.close(); self.db = None
        if not self.lock.closed:
            self.lock.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
