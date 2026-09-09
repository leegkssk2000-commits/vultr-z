"""Deterministic stored-only tables and decision/path charts; no economic engine."""
import argparse, collections, datetime, gzip, hashlib, importlib.util, json, math
from pathlib import Path
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2]
PERIODS=('DEV2025','SEEN2026');VARIANTS=('T1','M1','R1','F1','F0')
PARENT='research/development_evidence/KR3_C51_ENTRY_CONTEXT_AB_AFTER_PR1225_V1/B'
def read(p):return json.loads(Path(p).read_bytes())
def gz(p):return json.loads(gzip.decompress(Path(p).read_bytes()))
def put(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def fmt(x):return 'NA' if x is None else f'{x:.2f}'
def checks(p,c):
    def up(x,y):return x is not None and y is not None and x>y and not math.isclose(x,y,rel_tol=1e-11,abs_tol=1e-7)
    return dict(WR_up=up(c['base_cost']['win_rate'],p['base_cost']['win_rate']),
        terminal_net_up=up(c['terminal_net_bps'],p['terminal_net_bps']),cost2_up=up(c['terminal_cost2x_net_bps'],p['terminal_cost2x_net_bps']),
        daily_DD_down=up(p['marked_DD_trade_sum_bps'],c['marked_DD_trade_sum_bps']))
def risk(result):
    m=result['metrics'];symbols=collections.defaultdict(float);events=collections.defaultdict(float)
    values=[]
    for kind,key in [('trades','net_bps'),('open_observations','hypothetical_liquidation_net_mark_bps')]:
        for t in result[kind]:
            value=t[key];symbols[t['symbol']]+=value;events[t['entry_ts']]+=value;values.append((value,t['symbol'],t['signal_ts']))
    positive=sum(max(0,v[0]) for v in values)
    return dict(exposure=m['exposure'],closed_loss_groups=m['closed_loss_groups'],symbol_net_bps=dict(symbols),entry_event_net_bps=dict(events),
        maximum_positive_trade_bps=max([v[0] for v in values]+[0]),maximum_loss_bps=min([v[0] for v in values]+[0]),
        max_positive_trade_share_of_positive_net=max([v[0] for v in values]+[0])/positive if positive else None,
        largest_winners=sorted(values,reverse=True)[:10],largest_losses=sorted(values)[:10],
        marked_DD_trade_sum_bps=m['marked_DD_trade_sum_bps'],account_return_claimed=False)

def samples(result):
    pools={'WIN':[t for t in result['trades'] if t['net_bps']>0], 'LOSS':[t for t in result['trades'] if t['net_bps']<0],
        'OPEN':result['open_observations'],'EXCLUDED':[e for e in result['events'] if e['status']=='EXCLUDED']}
    return {label:(min(rows,key=lambda t:(t['signal_ts'],t['symbol'],t['signal_index'])) if rows else None) for label,rows in pools.items()}

def draw_chart(rows,event,position,variant,period,label,path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    import matplotlib.dates as md
    i=event['signal_index'];low=max(0,i-45);high=min(len(rows),max(i+24,(position or {}).get('exit_index',i)+3))
    high=min(high,i+61)
    fig=plt.figure(figsize=(12,6.2));grid=fig.add_gridspec(2,2,height_ratios=[3,1],wspace=.17,hspace=.12)
    for col,indices in enumerate((range(low,i+1),range(i,high))):
        ax=fig.add_subplot(grid[0,col]);vol=fig.add_subplot(grid[1,col],sharex=ax);xs=[]
        for j in indices:
            r=rows[j];x=md.date2num(datetime.datetime.fromtimestamp(r['bar_open_ts']/1000,datetime.timezone.utc));xs.append(x)
            color='#0c8b80' if r['close']>=r['open'] else '#c7504f';ax.vlines(x,r['low'],r['high'],color=color,lw=.8)
            ax.add_patch(Rectangle((x-.052,min(r['open'],r['close'])),.104,max(abs(r['close']-r['open']),r['close']*1e-6),facecolor=color,edgecolor=color,lw=.5))
            vol.bar(x,r['volume'],width=.11,color=color,alpha=.6)
        ax.plot(xs,[rows[j]['close'] for j in indices],lw=.8,color='#26394b',label='Original close')
        ctx=event.get('entry_context',{}).get('chart_context',{});feature=event.get('feature',{})
        for name,value in [('Decision AVWAP BAR_PROXY',ctx.get('avwap')),('Fixed floor',(position or event).get('fixed_floor',event.get('floor'))),
                           ('Fixed target',(position or event).get('fixed_target',event.get('target'))),('BB upper at decision',feature.get('bb_upper')),
                           ('KC upper at decision',feature.get('kc_upper')),('Prior 20 UTC-day low',feature.get('previous_low'))]:
            if value is not None:ax.axhline(value,lw=.8,ls='--',label=name)
        anchor=ctx.get('anchor')
        if anchor:
            for key in ('low','high'):ax.axhline(anchor[key]['price'],lw=.6,ls=':',label='Confirmed anchor '+key)
        if col==1 and position:
            for field,price,color in [('entry_ts','entry_price','#1555b5'),('exit_ts','exit_price','#b12c83')]:
                if field in position:
                    stamp=md.date2num(datetime.datetime.fromtimestamp(position[field]/1000,datetime.timezone.utc))
                    if xs and xs[0]<=stamp<=xs[-1]+1/6:ax.scatter([stamp],[position[price]],marker='^' if field=='entry_ts' else 'v',color=color,s=55,zorder=5,label=field)
        ax.set_title('Decision prefix only' if col==0 else 'Observed path after decision (display only)',fontsize=10)
        ax.grid(alpha=.15);vol.grid(alpha=.15);vol.set_ylabel('Source volume');ax.tick_params(labelbottom=False)
        vol.xaxis.set_major_formatter(md.DateFormatter('%m-%d\n%H:%M',tz=datetime.timezone.utc));vol.tick_params(axis='x',labelsize=7)
        if col==0:ax.legend(fontsize=6,loc='best')
    stamp=datetime.datetime.fromtimestamp(event['signal_ts']/1000,datetime.timezone.utc).isoformat()
    ident=f'{variant}/{period}/{event["symbol"]}/{event["signal_index"]}/{event["signal_ts"]}'
    fig.suptitle(f'{ident}\n{label}; decision {stamp}; earliest deterministic member',fontsize=10)
    fig.text(.02,.015,'Actual OHLC candles + close + original volume. No synthetic fills. Separate right panel never enters strategy inputs.',fontsize=8)
    fig.savefig(path,dpi=120,bbox_inches='tight');plt.close(fig)
    return dict(trade_id=ident,decision_ts=event['signal_ts'],symbol=event['symbol'],signal_index=i,category=label,file=str(path.relative_to(HERE)),
        left_last_source_index=i,right_first_source_index=i,selection='EARLIEST_BY_SIGNAL_TIME_SYMBOL_INDEX',display_only=True)

def generate(inputs=None,finalize=False):
    spec=read(HERE/'SPEC.json');budget=read(HERE/'BUDGET.json');summary=dict(scope=spec['scope'],periods={},decisions={},weighted_closed_WR={},
        new_economic_replays=0,formal_credit=0,independent=False,risk={},charts=[])
    lines=['# Source chart mechanisms — actual USED_DEV results','',
        'Equal fixed research notional; trade-bps sums. Open marks include hypothetical modeled liquidation costs; they are not actual exits. '+
        'Marked DD is a same-calendar sum of fixed-notional trade marks, not an account return. The two windows are not a continuous account curve.','',
        '|Period|Lane|Closed/open|WR %|Avg win|Avg loss|Payoff|PF|Closed net|Open mark|Total net|Cost ×2|Marked DD|',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    results={};weighted=collections.defaultdict(lambda:[0,0]);chart_dir=HERE/'CHARTS'
    if inputs:chart_dir.mkdir(exist_ok=True)
    for period in PERIODS:
        parent=gz(REPO/PARENT/period/'RESULT.json.gz');pm=parent['metrics'];summary['periods'][period]={};packet=gz(Path(inputs)/(period+'.json.gz')) if inputs else None
        if inputs:
            if hashlib.sha256((Path(inputs)/(period+'.json.gz')).read_bytes()).hexdigest()!=spec['input_packet_sha256'][period]:raise ValueError('INPUT_PACKET_DRIFT')
        for variant in ('C54',)+VARIANTS:
            path=HERE/variant/period/'RESULT.json.gz'
            result=parent if variant=='C54' else gz(path) if path.exists() else None
            if result is None:
                status=spec.get('lane_status',{}).get(variant,'NOT_RUN')
                summary['periods'][period][variant]=dict(status=status);lines.append('|'+ '|'.join([period,variant]+['NOT_RUN']*11)+'|');continue
            results[variant,period]=result;m=result['metrics'];b=m['base_cost'];weighted[variant][0]+=b['wins'];weighted[variant][1]+=m['closed_T']
            row=dict(status='STORED_C54_REUSED' if variant=='C54' else 'ACTUAL_USED_DEV',metrics=m,checks=None if variant=='C54' else checks(pm,m))
            summary['periods'][period][variant]=row;summary['risk'][variant+'/'+period]=risk(result)
            values=[period,variant,f"{m['closed_T']}/{m['open_T']}",fmt(None if b['win_rate'] is None else b['win_rate']*100),
                *[fmt(b[k]) for k in ('average_win_bps','average_loss_bps','realized_payoff','PF')],fmt(b['net_bps']),fmt(m['open_hypothetical_net_mark_bps']),
                fmt(m['terminal_net_bps']),fmt(m['terminal_cost2x_net_bps']),fmt(m['marked_DD_trade_sum_bps'])]
            lines.append('|'+ '|'.join(values)+'|')
            ap=HERE/variant/period/'ACCOUNTING_C54.json'
            if variant in ('T1','F1','F0') and ap.exists():row['full_attribution']=read(ap)
            if packet and variant!='C54':
                byorigin={(e['symbol'],e['signal_index']):e for e in result['events']}
                for label,position in samples(result).items():
                    if position is None:summary['charts'].append(dict(variant=variant,period=period,category=label,status='NO_OBSERVATION'));continue
                    event=byorigin[(position['symbol'],position['signal_index'])];path=chart_dir/f'{variant}_{period}_{label}.png'
                    summary['charts'].append(draw_chart(packet['rows_by'][position['symbol']],event,position if label!='EXCLUDED' else None,variant,period,label,path))
    for variant in VARIANTS:
        c=[summary['periods'][p][variant].get('checks') for p in PERIODS]
        summary['decisions'][variant]=('BLOCKED_OR_NOT_RUN' if any(x is None for x in c) else 'STRICT_8_CONDITION_DEVELOPMENT_GOAL_MET' if all(all(x.values()) for x in c)
            else 'PARTIAL_TRADEOFF' if all(x['terminal_net_up'] and x['cost2_up'] for x in c) else 'REJECT_NO_ECONOMIC_IMPROVEMENT')
    summary['weighted_closed_WR']={k:dict(wins=v[0],closed=v[1],win_rate=v[0]/v[1] if v[1] else None) for k,v in weighted.items()}
    summary['candidate_total']=budget['cumulative_actual'];summary['evaluation_total']=budget['cumulative_actual_evaluations'];summary['allocation']=budget['chart_allocation']
    lines+=['','## Frozen goal and two-window interpretation','',json.dumps(summary['decisions'],sort_keys=True),'',
        'The eight existing conditions are WR up, terminal net up, cost ×2 up and marked DD down in each window. Equality does not pass. '+
        'M1/R1 are standalone signal pools and their results cannot be added to C54 as an improvement. T1/F1/F0 full common/new/removed/closed-open accounting is preserved per cell.','',
        '|Lane|Combined closed wins/trades|Weighted WR %|','|---|---:|---:|']
    for variant,v in summary['weighted_closed_WR'].items():lines.append(f"|{variant}|{v['wins']}/{v['closed']}|{fmt(None if v['win_rate'] is None else 100*v['win_rate'])}|")
    lines+=['','## Risk, attribution and selection limits','',
        'SUMMARY.json preserves all per-window metrics, symbol/event concentration, ten largest winners/losses, maximum-trade concentration, exposure and grouped loss streaks. '+
        'T/F accounting preserves every winner harmed, large-winner damage and eight exhaustive common/new/removed/state-transition groups. No period DD is summed.','',
        'F1/F0 use one frozen equal-width interval each. Differences are descriptive USED_DEV evidence; a profitable F1 alone does not establish golden-ratio causality. '+
        'CHARTS contains the earliest win/loss/open/excluded observation by decision timestamp, symbol and original index, with explicit missing-category records. '+
        'All signals remain machine-readable in RAW and RESULT events, including excluded signals. These post-outcome plots are not blind OOS evidence.','',
        'Costs are the inherited research model, including its floor, spread/impact and funding proxy. No new actual fill, tick-volume, exchange-resident stop or live-futures execution is claimed. '+
        'No initial SL, TP, leverage, sizing, source collection, unused OOS, paid AI, orders or deployment was authorized by these results.','']
    if inputs:lines+=['## Deterministic source charts','']+[f"- [{x['trade_id']} — {x['category']}]({x['file']})" for x in summary['charts'] if x.get('file')]+['']
    put(HERE/'SUMMARY.json',summary);(HERE/'REPORT.md').write_text('\n'.join(lines));put(HERE/'CHART_MANIFEST.json',summary['charts'])
    if finalize:
        files={str(p.relative_to(HERE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.rglob('*')) if p.is_file() and p.name!='FINAL_HASHES.json' and '__pycache__' not in p.parts and p.suffix!='.pyc'}
        put(HERE/'FINAL_HASHES.json',files)
    print('\n'.join(lines[:20]));return summary
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--inputs');p.add_argument('--finalize',action='store_true');x=p.parse_args();generate(inputs=x.inputs,finalize=x.finalize)
