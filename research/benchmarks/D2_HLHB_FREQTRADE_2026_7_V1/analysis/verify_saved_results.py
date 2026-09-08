"""Read-only reconciliation of saved outputs. No strategy or engine imports."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path('/workspace/scratch/91d255a1335a')
RUNS = ROOT / 'vultr-z-external/research/benchmarks/D2_HLHB_FREQTRADE_2026_7_V1'
OUT = ROOT / 'benchmark-analysis'


def load(path):
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == '.gz' else data)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key(t):
    return t['symbol'], t.get('original_signal_index', t.get('signal_index'))


def compare_dev():
    result_path = RUNS / 'results/D2_DEV2025/RESULT.json'
    raw_path = RUNS / 'results/D2_DEV2025/RAW_ENGINE.json'
    native_path = ROOT / 'external-checkpoint/inputs/reference/Results/DEV2025/RESULT.json.gz'
    packet_path = ROOT / 'external-checkpoint/inputs/DEV2025.json.gz'
    result, raw, native, packet = map(load, (result_path, raw_path, native_path, packet_path))
    nt = {key(t): t for t in native['trades'] + native['open_observations']}
    ext = {(t['pair'].replace('/', '-'), int(t['enter_tag'].split(':')[1])): t for t in raw['trades']}
    ntrace = defaultdict(list)
    for t in native['trace']:
        ntrace[key(t)].append(t)
    ex_trace = defaultdict(list)
    for t in raw['audit']['trace']:
        ex_trace[t['pair'].replace('/', '-'), t['original_signal_index']].append(t)
    timeout_kinds = {'ORIGINAL_TIME_STOP_CLOSE', 'RUNNER_FINAL_TIME_STOP_CLOSE'}
    differences = []
    timeout_count = 0
    for k, t in sorted(nt.items(), key=lambda item: (item[1]['entry_ts'], item[0])):
        e = ext[k]
        fill_trace = [v for v in ntrace[k] if 'price' in v and v['ts'] == t['exit_ts'] and v['kind'] != 'ENTRY_NEXT_OPEN']
        assert len(fill_trace) == 1, (k, fill_trace)
        nreason = fill_trace[0]['kind']
        assert nreason == e['exit_reason'], (k, nreason, e['exit_reason'])
        if nreason in timeout_kinds:
            timeout_count += 1
        if t['exit_price'] == e['close_rate']:
            continue
        assert nreason in timeout_kinds, (k, nreason)
        rows = packet['rows_by'][k[0]]
        j = t['exit_index']
        target = [v for v in ex_trace[k] if v.get('native_target_only')]
        assert len(target) == 1
        facts = {
            'native_trace_matches_timeout_reason': nreason == e['exit_reason'],
            'native_price_equals_completed_close': t['exit_price'] == rows[j]['close'],
            'ft_price_equals_following_open': e['close_rate'] == rows[j + 1]['open'],
            'native_ts_equals_completed_close_ts': t['exit_ts'] == rows[j]['bar_close_ts'],
            'ft_ts_equals_following_open_ts': e['close_timestamp'] == rows[j + 1]['bar_open_ts'],
            'timestamps_identical': t['exit_ts'] == e['close_timestamp'],
            'independent_target_matches_native_close': target[0]['price'] == t['exit_price'],
            'independent_target_index_matches_native': target[0]['index'] == j,
        }
        assert all(facts.values()), (k, facts)
        differences.append({'symbol': k[0], 'origin_index': k[1], 'decision_index': t['decision_index'],
                            'entry_ts': t['entry_ts'], 'native_exit_index': j,
                            'exit_ts': t['exit_ts'], 'exit_utc': datetime.fromtimestamp(t['exit_ts'] / 1000, timezone.utc).isoformat(),
                            'native_reason_from_trace': nreason, 'external_reason': e['exit_reason'],
                            'native_close': t['exit_price'], 'ft_next_open': e['close_rate'],
                            'gross_delta_bps': (e['close_rate'] - t['exit_price']) / t['entry_price'] * 10000,
                            'verification': facts})
    differences.sort(key=lambda v: (v['exit_ts'], v['symbol'], v['origin_index']))
    assert len(differences) == len(result['parity']['exit_differences']) == 29
    extkeycounts = Counter((t['pair'], int(t['enter_tag'].split(':')[1])) for t in raw['trades'])
    duplicates = {str(k): v for k, v in extkeycounts.items() if v > 1}
    overlaps = []
    same_time_entries = []
    for symbol in packet['rows_by']:
        pair_trades = sorted([t for t in raw['trades'] if t['pair'].replace('/', '-') == symbol], key=lambda t: t['open_timestamp'])
        for prior, current in zip(pair_trades, pair_trades[1:]):
            if current['open_timestamp'] < prior['close_timestamp']:
                overlaps.append({'symbol': symbol, 'prior': prior['enter_tag'], 'current': current['enter_tag']})
            if current['open_timestamp'] == prior['close_timestamp']:
                same_time_entries.append({'symbol': symbol, 'prior': prior['enter_tag'], 'current': current['enter_tag']})
    nrefs = {(t['symbol'], t['reference_signal_index']): t for t in native['reference_opportunities']}
    erefs = {(p.replace('/', '-'), t['reference_signal_index']): t for p, audit in raw['audit']['pairs'].items() for t in audit['reference_opportunities']}
    refdiff = []
    for k in sorted(nrefs.keys() | erefs.keys()):
        if k not in nrefs or k not in erefs:
            refdiff.append({'key': k, 'missing': True})
            continue
        fields = set(nrefs[k]) & set(erefs[k])
        changes = {f: [nrefs[k][f], erefs[k][f]] for f in fields if nrefs[k][f] != erefs[k][f]}
        if changes:
            refdiff.append({'key': k, 'changes': changes})
    assert not (duplicates or overlaps or same_time_entries or refdiff)
    return {
        'status': 'SAVED_DEV2025_VALID_WITH_EXPLICIT_TIMEOUT_FILL_DIFFERENCE',
        'new_economic_runs': 0,
        'sources_sha256': {str(p): digest(p) for p in (result_path, raw_path, native_path, packet_path)},
        'entries_native': len(nt), 'entries_external': len(ext),
        'raw_signals': result['parity']['raw_signals_native'],
        'signal_differences': result['parity']['signal_differences'],
        'entry_differences': result['parity']['entry_differences'],
        'reference_opportunities_native': len(nrefs), 'reference_opportunities_external': len(erefs),
        'reference_all_shared_fields_differences': refdiff,
        'cost_differences': result['parity']['cost_differences'],
        'all_native_exit_reasons_match_ft': True,
        'timeout_trades': timeout_count, 'timeout_price_difference_count': len(differences),
        'timeout_equal_close_next_open_count': timeout_count - len(differences),
        'price_difference_reasons': dict(Counter(v['native_reason_from_trace'] for v in differences)),
        'earliest_exit_mismatch': differences[0],
        'net_delta_from_timeout_gaps_bps': sum(v['gross_delta_bps'] for v in differences),
        'duplicate_origins': duplicates, 'actual_position_overlaps': overlaps,
        'same_timestamp_exit_reentry': same_time_entries,
        'callback_errors': raw['audit']['callback_errors'],
        'differences': differences,
    }


def diagnose_seen():
    raw_path = RUNS / 'results/D2_SEEN2026/RAW_ENGINE.json'
    failure_path = RUNS / 'results/D2_SEEN2026/FAILURE.json'
    packet_path = ROOT / 'external-checkpoint/inputs/SEEN2026.json.gz'
    raw, failure, packet = map(load, (raw_path, failure_path, packet_path))
    rows_by = packet['rows_by']
    cut = 1778198400000 - 14400000
    offsets = []
    for t in sorted(raw['trades'], key=lambda t: t['open_timestamp']):
        symbol = t['pair'].replace('/', '-')
        rows = rows_by[symbol]
        trim = next(i for i, r in enumerate(rows) if r['bar_open_ts'] >= cut)
        anchor = int(t['enter_tag'].split(':')[2])
        actual = anchor - trim
        offsets.append({'symbol': symbol, 'source_rows': len(rows), 'cropped_prefix_rows': trim,
                        'intended_decision_index': anchor, 'stale_callback_index': actual,
                        'intended_decision_close_ts': rows[anchor]['bar_close_ts'],
                        'stale_callback_close_ts': rows[actual]['bar_close_ts'],
                        'entry_ts': t['open_timestamp']})
    return {'status': failure['status'], 'economic_comparison_valid': False,
            'new_economic_runs': 0, 'retry_allowed': False,
            'raw_trade_count': len(raw['trades']), 'audited_entry_count': len(raw['audit']['entries']),
            'callback_error_count': len(raw['audit']['callback_errors']),
            'callback_error_types': dict(Counter(e['message'] for e in raw['audit']['callback_errors'])),
            'all_raw_trades_force_exit': all(t['exit_reason'] == 'force_exit' for t in raw['trades']),
            'first_fault': 'D2_ENTRY_FEATURE_CALLBACK_TIME_MISMATCH',
            'root_cause': 'FULL_CANONICAL_CACHE_WITH_CROPPED_ENGINE_CURSOR; required_startup=0 loses the 3027-row canonical prefix offset',
            'source_sequence': [
                'offline_engine.run_frame passes full prefix features with timerange beginning in 2026',
                'FT Backtesting._get_ohlcv_as_lists caches full dataframe before trim_dataframe',
                'FT time_pair_generator sets callback max_index = required_startup + cropped row_index',
                'DataProvider.get_analyzed_dataframe applies max_index to full cached dataframe',
                'D2Independent.order_filled rejects stale decision index and cannot initialize held state',
                'FT strategy_safe_wrapper suppresses callback exceptions; custom_exit cannot apply D2 rules',
                'post-run audit rejects all seven forced-close artifacts as economic evidence'],
            'first_trade_offsets': offsets,
            'sources_sha256': {str(p): digest(p) for p in (raw_path, failure_path, packet_path)},
            'required_next_scope_validation': 'Fix callback calendar/cache alignment generically and add an offset-prefix synthetic engine regression before any separately authorized replacement economic attempt. Preserve failed attempt and all frozen artifacts.',
            }


dev, seen = compare_dev(), diagnose_seen()
output = {'DEV2025': dev, 'SEEN2026': seen}
(OUT / 'D2_SAVED_RECONCILIATION.json').write_text(json.dumps(output, indent=2, sort_keys=True) + '\n')
lines = ['# 저장 결과 독립 검산', '',
         '경제 엔진·native replay 재실행 0회. 원형 저장거래·trace·기존 canonical 가격과 저장 FT 결과만 읽음.', '',
         '## DEV2025', '',
         f"- 원시 신호 {dev['raw_signals']}개, 원형/FT 거래 {dev['entries_native']}/{dev['entries_external']}건.",
         '- 신호·진입·참조예약 모든 공유 필드·공통비용 차이 0. 중복 origin·같은 종목 점유겹침·동일시각 재진입 0.',
         f"- 시간청산 {dev['timeout_trades']}건 중 가격차이 {len(dev['differences'])}건. 나머지 {dev['timeout_equal_close_next_open_count']}건은 종가와 다음 시가가 수치상 같음.",
         '- 29건 전부 원형 trace상 시간청산이고, 원형 가격=완료봉 종가, FT 가격=바로 다음봉 시가. 모든 청산시각은 동일.',
         f"- 29건 구성: {dev['price_difference_reasons']}.",
         f"- 합산 손익차이 {dev['net_delta_from_timeout_gaps_bps']:+.12f} trade-bps. 공통비용차이 0이므로 순손익차이도 동일.",
         f"- 최초: {dev['earliest_exit_mismatch']['symbol']} origin {dev['earliest_exit_mismatch']['origin_index']}, {dev['earliest_exit_mismatch']['exit_utc']}, 종가 {dev['earliest_exit_mismatch']['native_close']} → 다음시가 {dev['earliest_exit_mismatch']['ft_next_open']}.", '',
         '| 종목 | origin | 원형 trace 이유 | 종가 | FT 다음시가 | 차이 trade-bps |',
         '|---|---:|---|---:|---:|---:|']
for v in dev['differences']:
    lines.append(f"| {v['symbol']} | {v['origin_index']} | {v['native_reason_from_trace']} | {v['native_close']} | {v['ft_next_open']} | {v['gross_delta_bps']:+.9f} |")
lines += ['', '## SEEN2026', '',
          '- FAILED_CONSUMED. 실측 전략 경제성 판정 불가. 자동 재시도 없음.',
          '- canonical 3748행 캐시는 유지되지만, 엔진 calendar가 앞 3027행을 잘라낸 후 그 상대 커서를 같은 캐시에 적용함.',
          '- 최초 BTC 진입의 요구 decision index 3040과 callback index 13 불일치. 완료봉 시각 검사가 stale 행을 거절함.',
          f"- entry 감사 {seen['audited_entry_count']}건, custom_exit 오류 {seen['callback_error_count']}회. 7개 강제 종료 결과는 경제표에서 제외해야 함.",
          '- source 호출순서 및 7종목별 정확한 커서 차이는 JSON에 기록.',
          '- 수정은 범용 calendar/cache 정렬 계약에서 수행해야 하며, 원형 판정·실패 시도는 보존해야 함. 별도 승인 전 경제 재실행 금지.', '']
(OUT / 'D2_SAVED_RECONCILIATION.md').write_text('\n'.join(lines))
print(json.dumps({'DEV2025': {k: v for k, v in dev.items() if k not in ('differences', 'sources_sha256')},
                  'SEEN2026': {k: v for k, v in seen.items() if k not in ('first_trade_offsets', 'sources_sha256', 'source_sequence')}}, sort_keys=True))
