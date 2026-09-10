"""As-of daily context from PR1251 saved bytes; no network or economic replay."""
from decimal import Decimal
from urllib.parse import urlparse,parse_qs
from math import fsum
from backend.research.rebuild import jc_lifecycle_v1 as native
f=native.f;DAY=native.DAY;BAR=native.BAR


def bind_boundary(raw,receipt,rows,start,*,raw_sha256):
    if receipt['sha256']!=raw_sha256:raise ValueError('RAW_RECEIPT_HASH_MISMATCH')
    u=urlparse(receipt['url']);q=parse_qs(u.query)
    if u.scheme!='https' or u.netloc!='open-api.bingx.com' or u.path!='/openApi/swap/v3/quote/klines':raise ValueError('VENUE_ENDPOINT')
    if q.get('symbol')!=[receipt['symbol']] or q.get('interval')!=['1d']:raise ValueError('SYMBOL_INTERVAL_BINDING')
    if raw.get('code')!=0:raise ValueError('SOURCE_CODE')
    stamp=start//DAY*DAY;matches=[x for x in raw['data'] if int(x['time'])==stamp]
    if len(matches)!=1:raise ValueError('BOUNDARY_DAY_MISSING_OR_DUPLICATE')
    b=matches[0];suffix=[x for x in rows if start<=x['bar_open_ts']<stamp+DAY]
    if not suffix or suffix[0]['bar_open_ts']!=start or suffix[-1]['bar_close_ts']!=stamp+DAY:raise ValueError('BOUNDARY_SUFFIX_NOT_COMPLETE')
    for a,c in zip(suffix,suffix[1:]):
        if a['bar_close_ts']!=c['bar_open_ts']:raise ValueError('BOUNDARY_SUFFIX_GAP')
    D=lambda x:Decimal(str(x))
    tests=dict(close_exact=D(b['close'])==D(suffix[-1]['close']),
               high_contains=D(b['high'])>=max(D(x['high']) for x in suffix),
               low_contains=D(b['low'])<=min(D(x['low']) for x in suffix),
               volume_contains=D(b['volume'])>=sum((D(x['volume']) for x in suffix),Decimal(0)))
    if not all(tests.values()):raise ValueError('BOUNDARY_OVERLAP_MISMATCH:'+','.join(k for k,v in tests.items() if not v))
    bar=f.Bar(stamp,*[float(b[k]) for k in ('open','high','low','close','volume')]);f.validate([bar],DAY)
    return bar,dict(symbol=receipt['symbol'],venue='BingX_USDT_M_SWAP',raw_sha256=raw_sha256,source_uri=receipt['url'],
        open_ts=stamp,available_at=stamp+DAY,context_only=True,first_usable_at=stamp+DAY,
        evaluation_4h_changed=False,suffix_rows=len(suffix),checks=tests,
        comparison='DECIMAL_EXACT_CLOSE_AND_CONTAINMENT_NO_TOLERANCE',
        unverified=['00:00_AND04:00_4H_OHLCV','FULL_DAY_FIRST_OPEN','FULL_DAY_PREFIX_HIGH_LOW_VOLUME'],
        listing_origin_verified=False)


def rows_to_bars(rows,asof):
    prefix=[r for r in rows if r['bar_close_ts']<=asof]
    for r in prefix:
        if r['bar_close_ts']!=r['bar_open_ts']+BAR:raise ValueError('FOUR_HOUR_CLOCK')
    bars=[f.Bar(r['bar_open_ts'],*[float(r[k]) for k in ('open','high','low','close','volume')]) for r in prefix]
    # Segment validation deliberately happens only on the observed prefix.
    for i,b in enumerate(bars):
        f.validate([b])
        if i and b.open_ts<=bars[i-1].open_ts:raise ValueError('UNORDERED_OR_DUPLICATE')
    return bars


def complete_days(rows,asof):
    bars=rows_to_bars(rows,asof);groups={}
    for b in bars:groups.setdefault(b.open_ts//DAY*DAY,[]).append(b)
    result=[]
    for ts,group in sorted(groups.items()):
        if ts+DAY>asof:continue
        if [x.open_ts for x in group]!=[ts+i*BAR for i in range(6)]:continue
        result.append(f.Bar(ts,group[0].open,max(x.high for x in group),min(x.low for x in group),group[-1].close,fsum(x.volume for x in group)))
    return result


def timeline(rows,warmup,boundary,asof,*,start):
    """No future record is validated, reset on, or used before its completion."""
    known=[x for x in warmup if x.open_ts+DAY<=asof]
    if any(x.open_ts+DAY>start for x in known):raise ValueError('WARMUP_CROSSES_EVALUATION_START')
    if boundary is not None and boundary.open_ts+DAY<=asof:known.append(boundary)
    known+=complete_days(rows,asof)
    unique={}
    for b in known:
        f.validate([b],DAY)
        if b.open_ts in unique and b!=unique[b.open_ts]:raise ValueError('DUPLICATE_DAILY_SOURCE_MISMATCH')
        unique[b.open_ts]=b
    return [unique[t] for t in sorted(unique)]


def segments(days):
    result=[]
    for b in days:
        if not result or b.open_ts-result[-1][-1].open_ts!=DAY:result.append([])
        result[-1].append(b)
    return result


def asof_context(rows,warmup,boundary,asof,*,start):
    pieces=segments(timeline(rows,warmup,boundary,asof,start=start))
    return pieces[-1] if pieces else []


def coverage(days,start,end):
    decisions=[];continuous=[]
    pieces=segments(days)
    for piece in pieces:
        ready=piece[364].open_ts+DAY if len(piece)>=365 else None
        if ready is not None:
            left=max(start,ready);right=min(end,piece[-1].open_ts+DAY)
            if right>=left:continuous.append([left,right])
        decisions.extend(b.open_ts+DAY for i,b in enumerate(piece) if i>=364 and start<=b.open_ts+DAY<=end)
    # The last completed day remains the current daily context through the window end.
    if continuous and pieces and len(pieces[-1])>=365 and days[-1].open_ts+DAY<=end:continuous[-1][1]=end
    return dict(history_qualified_intervals=continuous,history_qualified_calendar_days=sum(b-a for a,b in continuous)/DAY,
        eligible_daily_decisions=len(decisions),first_eligible_decision=min(decisions) if decisions else None,
        listing_origin_verified=False,alltime_substitute=False)
