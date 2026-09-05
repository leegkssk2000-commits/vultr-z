"""Prefix-only diagnostic features; existing native owners and risk are unchanged."""
from bisect import bisect_right
from backend.research.rebuild import policy_kernel_v1 as kernel


def rma(values, length):
    out = [None] * len(values)
    if len(values) < length:
        return out
    out[length-1] = sum(values[:length]) / length
    for i in range(length, len(values)):
        out[i] = (out[i-1] * (length-1) + values[i]) / length
    return out


def directional_movement(rows, length=14):
    """TA-Lib ADX seed: exclude row zero TR; first ADX at 2*n-1.

    The initial n-1 directional/TR sum is smoothed before the first DI.
    Zero directional sum retains ADX, matching the published C recurrence.
    This is an additional research feature, never a native-owner replacement.
    """
    if length < 2:
        raise ValueError('DMI_LENGTH')
    trs = kernel.true_ranges(rows)
    plus = [0.]; minus = [0.]
    for a, b in zip(rows, rows[1:]):
        up = b['high'] - a['high']; down = a['low'] - b['low']
        plus.append(up if up > down and up > 0 else 0.)
        minus.append(down if down > up and down > 0 else 0.)
    dp = [None]*len(rows); dm = dp.copy(); dx = dp.copy(); adx = dp.copy(); atr = dp.copy()
    tr = sum(trs[1:length]); p = sum(plus[1:length]); m = sum(minus[1:length])
    for i in range(length, len(rows)):
        tr = tr-tr/length+trs[i]; p = p-p/length+plus[i]; m = m-m/length+minus[i]
        atr[i] = tr/length
        dp[i] = 100*p/tr if tr else 0.; dm[i] = 100*m/tr if tr else 0.
        dx[i] = 100*abs(dp[i]-dm[i])/(dp[i]+dm[i]) if dp[i]+dm[i] else 0.
        if i == 2*length-1:
            adx[i] = sum(dx[length:i+1])/length
        elif i > 2*length-1:
            adx[i] = (adx[i-1]*(length-1)+dx[i])/length if dp[i]+dm[i] else adx[i-1]
    return {'plus_di':dp, 'minus_di':dm, 'adx':adx, 'atr14':atr}


def supertrend(rows, length=10, multiplier=3.):
    """TradingView documented band recurrence; not the native owner's quirky seed."""
    atr = rma(kernel.true_ranges(rows), length)
    upper = [None]*len(rows); lower = upper.copy(); line = upper.copy(); direction = [-1]*len(rows)
    for i in range(length-1, len(rows)):
        center = (rows[i]['high']+rows[i]['low'])/2
        bu = center+multiplier*atr[i]; bl = center-multiplier*atr[i]
        if i == length-1:
            upper[i] = bu; lower[i] = bl; line[i] = bu
            continue
        upper[i] = bu if bu < upper[i-1] or rows[i-1]['close'] > upper[i-1] else upper[i-1]
        lower[i] = bl if bl > lower[i-1] or rows[i-1]['close'] < lower[i-1] else lower[i-1]
        if line[i-1] == upper[i-1]:
            direction[i] = 1 if rows[i]['close'] > upper[i] else -1
        else:
            direction[i] = -1 if rows[i]['close'] < lower[i] else 1
        line[i] = lower[i] if direction[i] == 1 else upper[i]
    return {'line':line, 'direction':direction, 'upper':upper, 'lower':lower}


def aggregate_closed(rows, interval_ms, source_interval_ms):
    buckets = {}; out = []
    for row in rows:
        ts = row.get('bar_open_ts', row.get('ts_ms'))
        key = ts//interval_ms*interval_ms
        buckets.setdefault(key, []).append(row)
    for ts, group in sorted(buckets.items()):
        expected = list(range(ts, ts+interval_ms, source_interval_ms))
        if [r.get('bar_open_ts',r.get('ts_ms')) for r in group] != expected:
            continue
        out.append({'bar_open_ts':ts,'bar_close_ts':ts+interval_ms,
                    'open':group[0]['open'],'close':group[-1]['close'],
                    'high':max(r['high'] for r in group),'low':min(r['low'] for r in group),
                    'volume':sum(r['volume'] for r in group)})
    return out


class Features:
    def __init__(self, rows, interval):
        self.rows = rows; self.interval = interval
        self.dmi = directional_movement(rows)
        self.st = supertrend(rows)
        self.ema20 = kernel.ema([r['close'] for r in rows],20)
        self.htf = aggregate_closed(rows, 14_400_000, interval)
        self.htf_closes = [r['bar_close_ts'] for r in self.htf]
        self.htf_ema = kernel.ema([r['close'] for r in self.htf],50)

    def at(self, i, side='long'):
        sign = 1 if side == 'long' else -1
        row = self.rows[i]; close_ts = row.get('bar_close_ts',row.get('ts_ms',0)+self.interval)
        h = bisect_right(self.htf_closes,close_ts)-1
        adx = self.dmi['adx']; p = self.dmi['plus_di']; m = self.dmi['minus_di']
        return {'ADX14_rising':i>0 and adx[i-1] is not None and adx[i] > adx[i-1],
                'prior_DMI14_direction_aligned':i>0 and p[i-1] is not None and sign*(p[i-1]-m[i-1])>0,
                'closed_4h_EMA50_direction_aligned':h>=49 and sign*(self.htf[h]['close']-self.htf_ema[h])>0,
                'prior_Supertrend10x3_bull_state':i>=10 and self.st['direction'][i-1]==1,
                'previous_EMA20_slope_positive':i>=2 and self.ema20[i-1]>self.ema20[i-2],
                'adx14':adx[i], 'prior_plus_di14':p[i-1] if i else None,
                'prior_minus_di14':m[i-1] if i else None,
                'prior_supertrend_direction':self.st['direction'][i-1] if i else None,
                'htf_available_close_ts':self.htf_closes[h] if h>=0 else None,
                'htf_ema50':self.htf_ema[h] if h>=49 else None,
                'runtime_uses_outcome_labels':False}
