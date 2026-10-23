"""Opt-in, read-only B-source consumer for K117 development observation.

This process never fetches prices, places orders, or writes the B producer's
files. Actual bars remain actual input; unverified admission, volume, clocks,
costs, fills and account NAV remain explicitly unknown. Formal Shadow is HOLD.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

import k117_adapter as k

SCHEMA = 'k117.development.source_consumer.v1'
SOURCE = 'https://open-api.bingx.com/openApi/swap/v3/quote/klines'
SYMBOLS = ('BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'XRP-USDT', 'LINK-USDT', 'DOGE-USDT')


class SourceQualityHold(ValueError):
    def __init__(self, reason, evidence):
        super().__init__(reason)
        self.evidence = evidence


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    raw = Path(path).read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def within(root, relative):
    root = Path(root).resolve()
    result = (root / relative).resolve()
    if not result.is_relative_to(root):
        raise ValueError('SOURCE_PATH_OUTSIDE_ROOT')
    return result


def atomic(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w') as stream:
        json.dump(value, stream, sort_keys=True, separators=(',', ':'), allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    directory = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def install_write_boundary(out, counts=None):
    root = Path(out).resolve()
    def allowed(path):
        if isinstance(path, int):
            return
        if not Path(os.fsdecode(path)).resolve().is_relative_to(root):
            if counts is not None:
                counts['write_blocked_calls'] = counts.get('write_blocked_calls', 0) + 1
            raise ValueError('READ_ONLY_B_SOURCE_WRITE_BLOCKED')
    def audit(event, args):
        if event == 'open' and isinstance(args[0], (str, bytes)):
            mode, flags = args[1], args[2]
            if ((isinstance(mode, str) and any(x in mode for x in 'wax+'))
                    or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))):
                allowed(args[0])
        elif event in {'os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.chown', 'os.utime'}:
            allowed(args[0])
        elif event in {'os.rename', 'os.link', 'os.symlink'}:
            allowed(args[0]); allowed(args[1])
    sys.addaudithook(audit)


def read_snapshot(pointer_path, now_ms, *, check_process=True):
    """Read a stable producer commit and independently verify latest payloads."""
    pointer_path = Path(pointer_path).resolve()
    pointer, pointer_sha = read_json(pointer_path)
    out, source = Path(pointer['out']).resolve(), Path(pointer['source']).resolve()
    state, state_file_sha = read_json(out / 'STATE.json')
    status, _ = read_json(out / 'STATUS.json')
    claimed = state.get('state_sha256')
    body = {key: value for key, value in state.items() if key != 'state_sha256'}
    if not claimed or k.digest(body) != claimed:
        raise ValueError('B_ATOMIC_STATE_HASH_MISMATCH')
    if status.get('state_sha256') != claimed or file_hash(out / 'STATE.json') != state_file_sha:
        raise ValueError('B_SNAPSHOT_CHANGED_RETRY')
    if state.get('fixture') is not False or state.get('order_calls') != 0:
        raise ValueError('B_NO_ORDER_ACTUAL_SOURCE_REQUIRED')
    isolation = state.get('last_process_isolation', {})
    if isolation.get('credential_file_reads', 0) != 0 or isolation.get('order_calls', 0) != 0:
        raise ValueError('B_NO_ORDER_ISOLATION_INVALID')
    pid = int(pointer['pid'])
    proc = Path('/proc') / str(pid)
    live, locks = False, []
    if check_process:
        if proc.exists():
            args = (proc / 'cmdline').read_bytes().split(b'\0')
            live = b'ops.scalp7_orderless_shadow_v1' in args and str(out).encode() in args
        if not live:
            raise ValueError('B_SOURCE_WRITER_NOT_LIVE')
        lock = (out / 'writer.lock').stat()
        inode = f'{os.major(lock.st_dev):02x}:{os.minor(lock.st_dev):02x}:{lock.st_ino}'
        locks = [line for line in Path('/proc/locks').read_text().splitlines()
                 if inode in line and f' {pid} ' in line]
        if not live or not locks:
            raise ValueError('B_SOURCE_WRITER_NOT_LIVE')
    ident, ident_sha = read_json(source / 'IDENTITY.json')
    cursor, cursor_sha = read_json(source / 'CURSOR.json')
    if (ident.get('source') != SOURCE or ident.get('interval') != '1m'
            or ident.get('timeZone') != 0 or ident.get('synthetic_fill') is not False
            or set(ident.get('symbols', [])) != set(SYMBOLS)
            or cursor.get('identity_sha256') != ident_sha
            or state.get('source_identity_sha256') != ident_sha):
        raise ValueError('SOURCE_IDENTITY_MISMATCH')
    proofs = {}
    for symbol in SYMBOLS:
        items = cursor['symbols'].get(symbol, [])
        if not items:
            raise ValueError('SOURCE_SYMBOL_RECEIPT_MISSING')
        item = items[-1]
        receipt, receipt_sha = read_json(within(source, item['path']))
        if receipt_sha != item['sha256']:
            raise ValueError('SOURCE_RECEIPT_HASH_MISMATCH')
        raw = within(source, receipt['body_path']).read_bytes()
        normalized = within(source, receipt['normalized_path']).read_bytes()
        payload = json.loads(raw)
        if (hashlib.sha256(raw).hexdigest() != receipt['body_sha256']
                or hashlib.sha256(normalized).hexdigest() != receipt['normalized_sha256']):
            raise ValueError('SOURCE_PAYLOAD_HASH_MISMATCH')
        if (receipt.get('symbol') != symbol or receipt.get('source') != SOURCE
                or receipt.get('http_status') != 200 or str(payload.get('code')) != '0'
                or receipt['received_at_ms'] > now_ms
                or receipt['end_exclusive_ms'] > receipt['received_at_ms']):
            raise ValueError('SOURCE_RECEIPT_UNAVAILABLE_OR_INVALID')
        proofs[symbol] = {'receipt_sha256': receipt_sha,
                          'body_sha256': receipt['body_sha256'],
                          'normalized_sha256': receipt['normalized_sha256'],
                          'received_at_ms': receipt['received_at_ms'],
                          'start_ms': receipt.get('start_ms'),
                          'end_exclusive_ms': receipt['end_exclusive_ms'],
                          'missing_minutes': receipt.get('missing_minutes')}
    if file_hash(pointer_path) != pointer_sha:
        raise ValueError('B_POINTER_CHANGED_DURING_READ')
    keys, previous, continuity = set(), {}, {symbol: [] for symbol in SYMBOLS}
    for row in state.get('market', []):
        key = f"{row['symbol']}:{row['close_ts_ms']}"
        values = {name: row[name] for name in ('open_ts_ms', 'close_ts_ms', 'available_ts_ms',
                  'open', 'high', 'low', 'close', 'segment_id')}
        if key in keys or state.get('market_keys', {}).get(key) != k.digest(values):
            raise ValueError('B_MARKET_KEY_OR_HASH_MISMATCH')
        keys.add(key)
        if (row.get('evidence_kind') != 'ACTUAL_PUBLIC_CLOSED_30M'
                or row['symbol'] not in SYMBOLS
                or row['close_ts_ms'] - row['open_ts_ms'] != k.TF
                or row['open_ts_ms'] % k.TF
                or not row['close_ts_ms'] <= row['available_ts_ms'] <= row['processed_at_ms'] <= now_ms
                or row['received_at_ms'] != row['available_ts_ms']
                or row.get('witness', {}).get('identity_sha256') != ident_sha):
            raise ValueError('B_MARKET_CLOCK_OR_SOURCE_INVALID')
        prior = previous.get(row['symbol'])
        if prior is not None:
            if row['close_ts_ms'] <= prior['close_ts_ms']:
                raise ValueError('B_MARKET_SYMBOL_ORDER_INVALID')
            if row['open_ts_ms'] != prior['close_ts_ms']:
                continuity[row['symbol']].append({
                    'start_ms': prior['close_ts_ms'], 'end_exclusive_ms': row['open_ts_ms'],
                    'missing_30m_bars': (row['open_ts_ms'] - prior['close_ts_ms']) // k.TF,
                    'previous_segment_id': prior['segment_id'], 'next_segment_id': row['segment_id']})
        previous[row['symbol']] = row
        prices = [row[name] for name in ('open', 'high', 'low', 'close')]
        if (any(isinstance(value, bool) or not math.isfinite(float(value)) or value <= 0
                for value in prices)
                or row['high'] < max(row['open'], row['close'], row['low'])
                or row['low'] > min(row['open'], row['close'], row['high'])):
            raise ValueError('B_MARKET_OHLC_INVALID')
    return {'pointer': pointer, 'pointer_sha256': pointer_sha,
            'source_identity': ident, 'source_identity_sha256': ident_sha,
            'source_cursor_sha256': cursor_sha, 'state': state,
            'history_30m_gaps': continuity,
            'state_sha256': claimed, 'payload_proofs': proofs,
            'producer_pid': pid, 'producer_live_verified': live,
            'producer_kernel_locks': locks, 'observed_at_ms': now_ms}


def candidate_quality(snap, row):
    """Preserve source gaps and fail closed only on unknown/relevant candidate gaps."""
    symbol = row['symbol']
    receipt = snap['payload_proofs'][symbol]
    missing = receipt.get('missing_minutes')
    minute_gaps = row.get('witness', {}).get('issues', {}).get(symbol, {}).get('minute_gaps')
    evidence = {'symbol': symbol, 'open_ts_ms': row['open_ts_ms'],
        'close_ts_ms': row['close_ts_ms'], 'receipt_missing_minutes': deepcopy(missing),
        'witness_minute_gaps': deepcopy(minute_gaps),
        'history_30m_gaps': [deepcopy(gap) for gap in snap['history_30m_gaps'][symbol]
                             if gap['end_exclusive_ms'] <= row['open_ts_ms']],
        'latest_receipt_sha256': receipt['receipt_sha256'],
        'latest_receipt_start_ms': receipt['start_ms'],
        'latest_receipt_end_exclusive_ms': receipt['end_exclusive_ms']}
    if (not isinstance(missing, list) or not isinstance(minute_gaps, list)
            or any(isinstance(x, bool) or not isinstance(x, int) or x % 60000 for x in missing)):
        raise SourceQualityHold('SOURCE_CANDIDATE_GAP_EVIDENCE_UNKNOWN', evidence)
    for gap in minute_gaps:
        if (not isinstance(gap, dict)
                or any(isinstance(gap.get(key), bool) or not isinstance(gap.get(key), int)
                       for key in ('start_ms', 'end_exclusive_ms', 'missing_minutes'))
                or gap['start_ms'] % 60000 or gap['end_exclusive_ms'] % 60000
                or gap['end_exclusive_ms'] <= gap['start_ms']
                or gap['missing_minutes'] != (gap['end_exclusive_ms'] - gap['start_ms']) // 60000):
            raise SourceQualityHold('SOURCE_CANDIDATE_GAP_EVIDENCE_UNKNOWN', evidence)
    evidence['relevant_receipt_missing_minutes'] = [x for x in missing
        if row['open_ts_ms'] <= x < row['close_ts_ms']]
    evidence['relevant_witness_minute_gaps'] = [deepcopy(gap) for gap in minute_gaps
        if gap['start_ms'] < row['close_ts_ms'] and gap['end_exclusive_ms'] > row['open_ts_ms']]
    if evidence['relevant_receipt_missing_minutes'] or evidence['relevant_witness_minute_gaps']:
        raise SourceQualityHold('SOURCE_CANDIDATE_MINUTE_GAP', evidence)
    evidence['candidate_gap_check'] = 'NO_REPORTED_CANDIDATE_GAP'
    return evidence


class Observer:
    def __init__(self, *, development=False, pointer, out, started_at_ms=None,
                 check_process=True, adapter_factory=None):
        if development is not True:
            raise ValueError('DEFAULT_OFF_EXPLICIT_DEVELOPMENT_REQUIRED')
        self.pointer = Path(pointer).resolve()
        self.out = Path(out).resolve()
        p = json.loads(self.pointer.read_bytes())
        protected = [self.pointer.parent, Path(p['out']).resolve(), Path(p['source']).resolve()]
        if any(self.out.is_relative_to(root) for root in protected):
            raise ValueError('B_SOURCE_OUTPUT_PATH_FORBIDDEN')
        self.out.mkdir(parents=True, exist_ok=True)
        self.lock = (self.out / 'writer.lock').open('a+b')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise ValueError('K117_DEVELOPMENT_WRITER_ALREADY_ACTIVE')
        self.isolation_counts = None
        try:
            self._initialize(check_process, started_at_ms, adapter_factory)
        except Exception:
            self.close()
            raise

    def _initialize(self, check_process, started_at_ms, adapter_factory):
        self.check_process = check_process
        self.binding = k.digest({'observer_sha256': file_hash(__file__),
            'adapter_sha256': file_hash(k.__file__), 'source_pins': k.pins(),
            'pointer_path': str(self.pointer), 'mode': 'DEVELOPMENT_OBSERVATION'})
        existing = self.out / 'STATE.json'
        if existing.exists():
            self.state, _ = read_json(existing)
            claimed = self.state.pop('state_sha256')
            if claimed != k.digest(self.state) or self.state['binding'] != self.binding:
                self.close(); raise ValueError('OBSERVER_STATE_OR_CODE_MISMATCH')
            previous = None
            for event in self.state['events']:
                body = dict(event); claimed = body.pop('event_sha256')
                if body['previous'] != previous or k.digest(body) != claimed:
                    self.close(); raise ValueError('OBSERVER_EVENT_HASH_MISMATCH')
                previous = claimed
        else:
            start = int(time.time() * 1000) if started_at_ms is None else int(started_at_ms)
            self.state = {'schema': SCHEMA, 'identity': k.IDENTITY, 'binding': self.binding,
                'mode': 'DEVELOPMENT_OBSERVATION', 'fixture': False, 'development': True,
                'formal_active': False, 'formal_fresh_credit': False, 'formal_gate': k.FORMAL_GATE,
                'started_at_ms': start, 'fresh_start_ms': start, 'producer_binding': None,
                'seen': {}, 'observations': [], 'decisions': [], 'events': [], 'adapter': None,
                'virtual_fills': [], 'fee_bps': None, 'funding_bps': None, 'slippage_bps': None,
                'net_1x': None, 'net_2x': None, 'NAV': None, 'order_calls': 0,
                'credential_file_reads': 0, 'market_requests': 0, 'stopped': False,
                'process_isolation': None}
        factory = k.Adapter if adapter_factory is None else adapter_factory
        self.adapter = factory(enabled=True, fixture=False, development=True,
            state=self.state['adapter'], started_at_ms=self.state['started_at_ms'])
        self.d = self.adapter.d
        config = k.ROOT / 'research/campaigns/scalp7_20260915'
        self.fit = json.loads((config / 'broad_rebuild_v2/FRESH_FORWARD_CONFIG_V2.json').read_bytes())['regime_fit']
        self.costs = json.loads((config / 'cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json').read_bytes())['costs_bps']

    def log(self, kind, body):
        event = {'seq': len(self.state['events']), 'kind': kind, 'body': deepcopy(body),
                 'previous': self.state['events'][-1]['event_sha256'] if self.state['events'] else None}
        event['event_sha256'] = k.digest(event)
        self.state['events'].append(event)

    def save(self):
        self.state['adapter'] = deepcopy(self.adapter.state)
        if self.isolation_counts is not None:
            self.state['process_isolation'] = deepcopy(self.isolation_counts)
            self.state['order_calls'] = self.isolation_counts['order_calls']
            self.state['credential_file_reads'] = self.isolation_counts['credential_file_reads']
            self.state['market_requests'] = self.isolation_counts['public_get_calls']
        atomic(self.out / 'STATE.json', {**self.state, 'state_sha256': k.digest(self.state)})
        atomic(self.out / 'STATUS.json', self.report())

    def report(self):
        adapter = self.state['adapter'] or self.adapter.state
        isolation = self.state.get('process_isolation')
        return {'schema': SCHEMA, 'identity': k.IDENTITY, 'mode': 'DEVELOPMENT_OBSERVATION',
                'state': 'STOPPED' if self.state['stopped'] else 'DEVELOPMENT_OBSERVATION',
                'fixture': False, 'formal_active': False, 'formal_fresh_credit': False,
                'formal_gate': k.FORMAL_GATE, 'fresh_bars': len(self.state['observations']),
                'decisions': len(self.state['decisions']),
                'signals': sum(x['result'].get('status') == 'SIGNAL' for x in self.state['decisions']),
                'pending': len(adapter['pending']), 'open_virtual_positions': len(adapter['positions']),
                'virtual_fills': sum(event['kind'] == 'OPEN' for event in adapter['events']),
                'closed_T': len(adapter['trades']), 'NAV': None,
                'fee_bps': self.state['fee_bps'], 'funding_bps': self.state['funding_bps'],
                'slippage_bps': self.state['slippage_bps'],
                'orders': None if isolation is None else isolation['order_calls'],
                'credential_file_reads': None if isolation is None else isolation['credential_file_reads'],
                'market_requests': None if isolation is None else isolation['public_get_calls'],
                'process_isolation': isolation,
                'last_reason': self.state.get('last_reason'),
                'state_sha256': k.digest(self.state)}

    def step(self, now_ms=None):
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        if self.state['stopped']:
            raise ValueError('OBSERVER_ALREADY_STOPPED')
        try:
            snap = read_snapshot(self.pointer, now, check_process=self.check_process)
            binding = k.digest({'pointer_sha256': snap['pointer_sha256'],
                               'source_identity_sha256': snap['source_identity_sha256']})
            if self.state['producer_binding'] not in (None, binding):
                raise ValueError('B_PRODUCER_EPOCH_OR_IDENTITY_CHANGED')
            binding_new = self.state['producer_binding'] is None
            self.state['producer_binding'] = binding
            market = snap['state']['market']
            closes = sorted({r['close_ts_ms'] for r in market
                             if r['close_ts_ms'] > self.state['fresh_start_ms']})
            accepted = 0
            for close in closes:
                batch = {r['symbol']: r for r in market if r['close_ts_ms'] == close}
                if set(batch) != set(SYMBOLS):
                    continue  # Wait for the producer's complete six-symbol batch.
                quality = {symbol: candidate_quality(snap, row) for symbol, row in batch.items()}
                frames = {s: self.d.pd.DataFrame([r for r in market if r['symbol'] == s
                          and r['close_ts_ms'] <= close]) for s in SYMBOLS}
                context_error = None
                try:
                    frames = self.d.helpers['bind_causal_context'](frames, self.fit)
                except (ValueError, KeyError, TypeError) as exc:
                    context_error = type(exc).__name__ + ':' + str(exc)
                for symbol in SYMBOLS:
                    row = batch[symbol]; key = symbol + ':' + str(close)
                    signature = k.digest(row)
                    if key in self.state['seen']:
                        if self.state['seen'][key] != signature:
                            raise ValueError('OBSERVED_BAR_CHANGED')
                        continue
                    source_guard = {'identity_sha256': snap['source_identity_sha256'],
                        'volume_units': snap['source_identity'].get('volume_units'),
                        'synthetic_fill': False, 'higher_timeframe_complete': False,
                        'stale_authority': None, 'stale_ms': 0}
                    result = self.adapter.on_bar(symbol=symbol, frame=frames[symbol],
                        asof_ms=now, source=source_guard, fit=self.fit,
                        frozen_cost_bps=self.costs[symbol])
                    observation = {'symbol': symbol, 'close_ts_ms': close,
                        'available_ts_ms': row['available_ts_ms'], 'received_at_ms': row['received_at_ms'],
                        'consumer_decision_ts_ms': now, 'actual_bar': deepcopy(row),
                        'bar_sha256': signature, 'B_state_sha256': snap['state_sha256'],
                        'source_identity_sha256': snap['source_identity_sha256'],
                        'source_cursor_sha256': snap['source_cursor_sha256'],
                        'latest_source_payload': snap['payload_proofs'][symbol],
                        'source_quality': quality[symbol],
                        'fixture': False, 'formal_fresh_credit': False,
                        'native_evaluation': 'NOT_RUN' if result.get('reason') in {
                            'VOLUME_UNIT_UNKNOWN', 'SOURCE_IDENTITY_UNBOUND',
                            'SYNTHETIC_SOURCE_FORBIDDEN', 'STALE_THRESHOLD_AUTHORITY_MISSING',
                            'INCOMPLETE_HIGHER_TIMEFRAME'} else 'ADAPTER_RESULT_RECORDED',
                        'source_integrity_scope': 'B atomic market hash and causal clocks; independently hashed latest source receipt/raw/normalized payload',
                        'context_error': context_error}
                    self.state['seen'][key] = signature
                    self.state['observations'].append(observation)
                    self.state['decisions'].append({'symbol': symbol, 'close_ts_ms': close,
                                                  'asof_ms': now, 'result': result})
                    self.log('ACTUAL_DEVELOPMENT_BAR', {'observation': observation, 'result': result})
                    self.state['last_reason'] = result.get('reason')
                    accepted += 1
            if accepted or binding_new:
                self.save()
            elif not (self.out / 'STATE.json').exists():
                self.save()
            return accepted
        except (ValueError, KeyError, OSError, TypeError) as exc:
            reason = type(exc).__name__ + ':' + str(exc)
            evidence = getattr(exc, 'evidence', None)
            evidence_sha = k.digest(evidence)
            if (self.state.get('last_reason') != reason
                    or self.state.get('last_hold_evidence_sha256') != evidence_sha):
                self.state['last_reason'] = reason
                self.state['last_hold_evidence_sha256'] = evidence_sha
                self.log('HOLD', {'reason': reason, 'at_ms': now, 'source_quality': evidence})
                self.save()
            return 0

    def stop(self, reason):
        self.state['stopped'] = True
        self.state['stop_reason'] = reason
        self.log('STOPPED', {'reason': reason, 'at_ms': int(time.time() * 1000)})
        self.save()

    def close(self):
        if not self.lock.closed:
            self.lock.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--development', action='store_true')
    parser.add_argument('--b-pointer', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--max-seconds', required=True, type=int)
    parser.add_argument('--poll-seconds', type=float, default=10)
    parser.add_argument('--stop-after-first-batch', action='store_true')
    args = parser.parse_args(argv)
    if not args.development:
        raise SystemExit('DEFAULT_OFF_EXPLICIT_DEVELOPMENT_REQUIRED')
    if not 0 < args.max_seconds <= 86400 or not 1 <= args.poll_seconds <= 30:
        raise SystemExit('BOUNDED_RUNTIME_REQUIRED')
    sys.dont_write_bytecode = True
    allowed = {'PATH', 'LANG', 'LC_ALL', 'TZ', 'SYSTEMROOT'}
    env = {key: value for key, value in os.environ.items() if key in allowed}
    os.environ.clear(); os.environ.update(env)
    counts = k.install_boundary()
    observer = Observer(development=True, pointer=args.b_pointer, out=args.out)
    observer.isolation_counts = counts
    install_write_boundary(observer.out, counts)
    started = time.monotonic()
    try:
        observer.save()
        while True:
            accepted = observer.step()
            if counts['order_calls'] or counts['credential_file_reads'] or counts['public_get_calls']:
                raise ValueError('NO_ORDER_NO_MARKET_ISOLATION_BROKEN')
            if accepted:
                print(json.dumps(observer.report(), sort_keys=True), flush=True)
                if args.stop_after_first_batch:
                    observer.stop('FIRST_COMPLETE_FUTURE_BATCH_RECORDED')
                    break
            remaining = args.max_seconds - (time.monotonic() - started)
            if remaining <= 0:
                observer.stop('BOUNDED_TIME_COMPLETE')
                break
            time.sleep(min(args.poll_seconds, remaining))
        print(json.dumps(observer.report(), sort_keys=True), flush=True)
        return 0
    finally:
        observer.close()


if __name__ == '__main__':
    raise SystemExit(main())
