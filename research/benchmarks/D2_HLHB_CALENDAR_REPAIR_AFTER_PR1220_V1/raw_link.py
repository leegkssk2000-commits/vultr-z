"""Independent raw-engine -> common ledger verification; stdlib only.

Does not import the engine, strategy, original normalizer or replay code.
force_exit is a terminal observation, not an observed strategy liquidation.
The compact cost/mark context was derived from the exact executed packet;
its byte pin and original source identities are checked by the parent verifier.
"""
from datetime import datetime
import hashlib
import json
import math

BAR_MS = 14_400_000
SETTLEMENT_MS = 28_800_000
INTRABAR_REASONS = {'roi', 'stop_loss', 'trailing_stop_loss', 'stoploss_on_exchange'}
ENGINE_FIELDS = ('profit_ratio', 'profit_abs', 'fee_open', 'fee_close',
                 'fee_open_cost', 'fee_close_cost', 'funding_fees',
                 'stake_amount', 'amount', 'leverage', 'exit_reason')

def require(ok, message):
    if not ok:
        raise ValueError(message)

def stamp(value):
    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    require(dt.tzinfo is not None, 'RAW_TIMEZONE_REQUIRED')
    return int(round(dt.timestamp() * 1000))

def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()

def equal(actual, expected, field):
    if isinstance(expected, dict):
        require(isinstance(actual, dict) and set(actual) == set(expected), 'RAW_LINK_KEYS:' + field)
        for key, value in expected.items():
            equal(actual[key], value, field + '.' + key)
    elif isinstance(expected, bool) or expected is None or isinstance(expected, str):
        require(type(actual) is type(expected) and actual == expected, 'RAW_LINK_MISMATCH:' + field)
    elif isinstance(expected, int):
        require(type(actual) is int and actual == expected, 'RAW_LINK_MISMATCH:' + field)
    elif isinstance(expected, float):
        require(not isinstance(actual, bool) and isinstance(actual, (float, int))
                and math.isfinite(actual) and math.isfinite(expected)
                and math.isclose(actual, expected, rel_tol=1e-11, abs_tol=1e-7),
                'RAW_LINK_MISMATCH:' + field)
    else:
        require(actual == expected, 'RAW_LINK_MISMATCH:' + field)

def charge(entry, exit_, binding):
    require(exit_ >= entry, 'RAW_NEGATIVE_DURATION')
    fee, spread, impact, funding_rate = (float(binding[key]) for key in
        ('fee_bps', 'spread_bps', 'impact_bps', 'funding_p95_per_settlement_bps'))
    require(all(math.isfinite(x) and x >= 0 for x in (fee, spread, impact, funding_rate)),
            'INVALID_CONTEXT_COST')
    count = exit_ // SETTLEMENT_MS - entry // SETTLEMENT_MS
    funding = count * funding_rate
    subtotal = fee + spread + impact + funding
    return {'fee_bps': fee, 'spread_bps': spread, 'impact_bps': impact,
            'funding_settlements': count, 'funding_bps': funding,
            'floor_adjustment_bps': max(0.0, 20.0 - subtotal),
            'total_bps': max(20.0, subtotal)}

def normalize_raw_trade(raw, context):
    start, end = context['period']
    symbol = str(raw['pair']).split(':')[0].replace('/', '-')
    require(symbol in context['costs'] and symbol in context['final_marks'], 'RAW_SYMBOL_UNKNOWN')
    require(raw.get('is_short', False) is False and float(raw.get('leverage', 1) or 1) == 1,
            'RAW_LONG_1X_REQUIRED')
    entry, exit_ = stamp(raw['open_date']), stamp(raw['close_date'])
    require(start <= entry < end and entry <= exit_ <= end, 'RAW_CALENDAR_INVALID')
    require(entry == raw['open_timestamp'] and exit_ == raw['close_timestamp'], 'RAW_CLOCK_DISAGREEMENT')
    entry_price, raw_exit_price = float(raw['open_rate']), float(raw['close_rate'])
    require(all(math.isfinite(x) and x > 0 for x in (entry_price, raw_exit_price)), 'RAW_INVALID_PRICE')
    reason = str(raw['exit_reason'])
    opened = reason == 'force_exit'
    intrabar = not opened and reason in INTRABAR_REASONS
    lower = end if opened else exit_
    upper = end if opened else min(end, exit_ + BAR_MS) if intrabar else exit_
    mark = context['final_marks'][symbol]
    require(mark['bar_close_ts'] == end and mark['bar_open_ts'] + BAR_MS == end, 'CONTEXT_FINAL_MARK_TIME')
    price = float(mark['close']) if opened else raw_exit_price
    require(math.isfinite(price) and price > 0, 'CONTEXT_FINAL_MARK_PRICE')
    gross = (price / entry_price - 1) * 10000
    lo = charge(entry, lower, context['costs'][symbol])
    hi = charge(entry, upper, context['costs'][symbol])
    return {'symbol': symbol, 'origin': f'{symbol}:{entry}',
            'entry_ts': entry, 'entry_price': entry_price,
            'exit_ts': upper, 'exit_ts_lower': lower, 'exit_price': price,
            'closed': not opened, 'reason': reason, 'intrabar_time_unobserved': intrabar,
            'gross_bps': gross, 'cost_bps': hi['total_bps'], 'cost_lower_bps': lo['total_bps'],
            'net_bps': gross - hi['total_bps'], 'cost2_bps': gross - 2 * hi['total_bps'],
            'net_upper_bps': gross - lo['total_bps'], 'cost2_upper_bps': gross - 2 * lo['total_bps'],
            'cost_breakdown_lower': lo, 'cost_breakdown_upper': hi,
            'engine': {key: raw.get(key) for key in ENGINE_FIELDS},
            'engine_open_rate': entry_price, 'engine_close_rate': raw_exit_price}

def validate_raw_link(result, archive, context, spec):
    for key in ('input_file_sha256', 'input_rows_sha256', 'cost_sha256', 'period'):
        require(context[key] == spec[key], 'CONTEXT_SOURCE_BINDING:' + key)
    require(digest(context['costs']) == spec['cost_sha256'], 'CONTEXT_COST_BINDING')
    require(set(context['costs']) == set(context['final_marks']), 'CONTEXT_SYMBOL_BINDING')
    raw = archive['trades']
    normalized = result['normalized_trades']
    require(len(raw) == len(normalized), 'RAW_REPORT_CARDINALITY')
    expected = {}
    for record in raw:
        item = normalize_raw_trade(record, context)
        key = item['origin']
        require(key not in expected, 'RAW_DUPLICATE_ORIGIN')
        expected[key] = (item, record)
    require(len({row['origin'] for row in normalized}) == len(normalized), 'REPORT_DUPLICATE_ORIGIN')
    require(set(expected) == {row['origin'] for row in normalized}, 'RAW_REPORT_ORIGINS')
    for row in normalized:
        reference, record = expected[row['origin']]
        for key, value in reference.items():
            require(key in row, 'RAW_LINK_MISSING_FIELD:' + key)
            equal(row[key], value, key)
        require(stamp(row['engine_open_date']) == stamp(record['open_date'])
                and stamp(row['engine_close_date']) == stamp(record['close_date']), 'RAW_LINK_ENGINE_DATES')
    for key in ('resolved', 'engine_views'):
        require(result[key] == archive[key], 'RAW_REPORT_METADATA:' + key)
    expected_ft = {'profit_abs_sum_including_force_exit': sum(float(row['profit_abs']) for row in raw),
                   'profit_ratio_sum_including_force_exit': sum(float(row['profit_ratio']) for row in raw),
                   'fee_per_side': float(archive['config']['fee'])}
    equal(result['ft_native_accounting'], expected_ft, 'ft_native_accounting')
    audit = archive.get('audit')
    if audit:
        require(not audit['callback_errors'], 'RAW_CALLBACK_ERRORS')
        require(len(audit['entries']) == len(raw), 'RAW_AUDIT_ENTRY_COUNT')
    return {'raw_trades': len(raw), 'normalized_trades': len(normalized),
            'one_to_one_identity': True, 'independent_raw_normalization': True,
            'engine_or_market_replay': False}
