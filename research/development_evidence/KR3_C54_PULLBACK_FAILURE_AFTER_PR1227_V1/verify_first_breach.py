"""P1: verify FIRST exit predicates on pinned original held bars.

Reads already executed positions and original stored inputs. No strategy import,
new trades, admission replay, candidate PnL computation or market requests.
"""
from pathlib import Path
import argparse,gzip,hashlib,json,math
HERE=Path(__file__).resolve().parent
PERIODS=('DEV2025','SEEN2026');BAR=14400000;HOLD=12
FLOOR='C54_ORIGINAL_PULLBACK_FLOOR_LOST_CLOSE'
FILL='C54_ORIGINAL_PULLBACK_FLOOR_LOST_NEXT_OPEN'
EMA='EMA20_NOT_ABOVE_EMA50_NEXT_OPEN'
LOW='CONTEXT_SIGNAL_LOW_INVALIDATION_NEXT_OPEN'
RUNNER='RUNNER_EMA20_NEXT_OPEN'
GUARD='KR3_PROFIT_ZONE_SUPPORT_LOST_NEXT_OPEN'
def need(ok,reason):
    if not ok:raise ValueError(reason)
def read(p):return json.loads(Path(p).read_bytes())
def gz(p):return json.loads(gzip.decompress(Path(p).read_bytes()))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def bounded_ema(rows,n):
    a=2./(n+1.);values=[float(r['close']) for r in rows];out=[]
    for j in range(len(rows)):
        start=max(0,j-4*n+1);x=values[start]
        for value in values[start+1:j+1]:x=a*value+(1.-a)*x
        out.append(x)
    return out

def first_termination(t,rows,e20,e50,cost,last):
    """Assertion oracle limited to the ALREADY RECORDED holding window."""
    i=t['signal_index'];entry=t['entry_index'];q=i-1
    while q>=0 and rows[q]['close']<=e20[q]:q-=1
    available=q>=0 and q<i-1
    floor=min(r['low'] for r in rows[q+1:i+1]) if available else None
    anchor=t['original_pullback_floor']
    need(anchor['available']==available,'SOURCE_FLOOR_AVAILABILITY')
    if available:
        need(anchor['trend_index']==q and anchor['price']==floor,'SOURCE_FLOOR_MISMATCH')
        expected=[dict(index=k,bar_close_ts=rows[k]['bar_close_ts'],low=rows[k]['low']) for k in range(q+1,i+1)]
        need(anchor['source']==expected,'SOURCE_FLOOR_BARS')
    state='UNCHECKED';armed=None;line=None;extended=False;final=i+HOLD;checked=0
    def done(kind,j):return dict(kind=kind,index=j,armed_index=armed,protected_line=line,checked_closes=checked)
    for j in range(entry,last+1):
        row=rows[j];close=float(row['close']);checked+=1
        if j==final:return done('TIME',j)
        if e20[j]<=e50[j]:return done(EMA,j)
        if state=='UNCHECKED' and close<rows[i]['low']:
            state='ALLOWED' if close<e50[j] else 'SUPPRESSED'
        if state=='ALLOWED' and close<rows[i]['low']:return done(LOW,j)
        if extended and j>=i+HOLD and close<=e20[j]:return done(RUNNER,j)
        if armed is None:
            count=max(0,row['bar_close_ts']//(2*BAR)-t['entry_ts']//(2*BAR))
            charge=max(20.,cost['fee_bps']+cost['spread_bps']+cost['impact_bps']+count*cost['funding_p95_per_settlement_bps'])
            if close>e20[j]>e50[j] and e20[j]>t['entry_price']*(1.+charge/10000.):
                armed=j;line=e20[j]
        elif close<line:
            return done(GUARD,j)
        else:line=max(line,e20[j])
        if armed is None and available and close<floor:return done(FILL,j)
        if j==i+HOLD-1 and state!='SUPPRESSED' and close>t['entry_price'] and close>e20[j]>e50[j]:
            extended=True;final=i+2*HOLD
    return done(None,None)

def check_position(t,trace,rows,e20,e50,cost,end):
    i=t['signal_index'];entry=t['entry_index'];closed='exit_price' in t
    next_open=closed and t.get('exit_timestamp_semantics')=='OBSERVED_4H_OPEN'
    last=t['exit_index']-int(next_open) if closed else t['mark_index']
    need(entry==i+1 and entry<=last<len(rows),'RECORDED_HOLDING_BOUNDS')
    need(rows[entry]['bar_open_ts']==t['entry_ts'] and rows[entry]['open']==t['entry_price'],'SOURCE_ENTRY')
    for j in range(entry,last+1):
        need(rows[j]['bar_close_ts']==t['signal_ts']+(j-i)*BAR,'SOURCE_HELD_CLOSE_CLOCK')
    expected=first_termination(t,rows,e20,e50,cost,last)
    hits=[x for x in trace if x['kind']==FLOOR]
    if expected['kind']==FILL:
        need(len(hits)==1 and hits[0]['index']==expected['index'],'MISSING_OR_DELAYED_FIRST_FLOOR_BREACH')
        need(hits[0]['observed_close']==rows[expected['index']]['close'],'SOURCE_TRIGGER_CLOSE')
    else:need(not hits,'UNSUPPORTED_FLOOR_BREACH')
    need(expected['armed_index']==t['profit_zone_state']['armed_index'],'MISSED_OR_EARLY_C51_ACTIVATION')
    if closed:
        if next_open:
            need(expected['kind']==t['exit_reason'] and expected['index']==last,'MISSED_OR_DELAYED_TERMINATING_EVENT')
            need(rows[last+1]['open']==t['exit_price'] and rows[last+1]['bar_open_ts']==t['exit_ts'],'SOURCE_NEXT_OPEN')
        else:
            need(expected['kind']=='TIME' and expected['index']==last,'MISSED_BREACH_BEFORE_TIME_EXIT')
            need(rows[last]['close']==t['exit_price'] and rows[last]['bar_close_ts']==t['exit_ts']<end,'SOURCE_TIME_CLOSE')
    else:
        need(rows[last]['close']==t['mark_price'] and rows[last]['bar_close_ts']==t['mark_ts']==end,'SOURCE_OPEN_MARK')
        if expected['kind'] is not None:
            need(expected['index']==last,'MISSED_EXIT_BEFORE_OPEN_MARK')
            if expected['kind']!='TIME':need(t['pending_exit_signal_ts']==end,'PENDING_EXIT_MISSING')
    return expected

def verify(inputs,root=HERE):
    root=Path(root);inputs=Path(inputs);spec=read(root/'SPEC.json');summary={}
    for per in PERIODS:
        p=inputs/(per+'.json.gz');need(sha(p)==spec['input_packet_sha256'][per],'ORIGINAL_PACKET_HASH:'+per)
        packet=gz(p);raw=gz(root/per/'RAW.json.gz');receipt=read(root/per/'RECEIPT.json')
        need(sha(root/per/'RAW.json.gz')==receipt['raw_sha256'],'FROZEN_RAW_CHANGED')
        need(sha(root/'SPEC.json')==receipt['spec_sha256'],'FROZEN_SPEC_CHANGED')
        end=spec['periods'][per]['runoff_end_ms'];n=bars=floors=nonfloor=0
        for sym,r in sorted(raw.items()):
            rows=packet['rows_by'][sym];e20=bounded_ema(rows,20);e50=bounded_ema(rows,50)
            for t in r['trades']+r['open_positions']:
                trace=[x for x in r['trace'] if x['signal_index']==t['signal_index']]
                x=check_position(t,trace,rows,e20,e50,packet['costs'][sym],end)
                n+=1;bars+=x['checked_closes'];floors+=int(x['kind']==FILL);nonfloor+=int(x['kind']!=FILL)
        summary[per]=dict(positions=n,held_closes_checked=bars,first_floor_intents=floors,nonfloor_paths_checked=nonfloor,
                           original_packet_sha256=spec['input_packet_sha256'][per],missed_or_delayed_intents=0)
    return dict(status='FIRST_EVENTS_SOURCE_VERIFIED',new_economic_replays=0,periods=summary)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--inputs',required=True);p.add_argument('--out');a=p.parse_args()
    answer=verify(a.inputs);text=json.dumps(answer,indent=2)+'\n'
    if a.out:Path(a.out).write_text(text)
    print(text)
