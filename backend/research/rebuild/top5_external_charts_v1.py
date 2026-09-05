"""Fixed hash-selected real-bar development cases; no synthetic chart or exit tuning."""
import argparse,json,gzip
from pathlib import Path
from backend.research.rebuild import top5_external_repair_v1 as r
from backend.research.rebuild.top5_external_metrics_v1 import diagnostics
from backend.research.rebuild.top5_external_features_v1 import Features,kernel
NAMES=dict(zip(r.old.LANES,['TrendRider Primary','TrendRider Broad','Break & Continue','Keltner','Supertrend']))


def build(data_dir):
    p,_,four,one,_=r.load_inputs(data_dir);r.verify_previous()
    trades=r.read_lines(r.ROOT/r.old.OUTPUT/'baseline/trades.jsonl.gz')
    previous=r.read_lines(r.ROOT/r.old.OUTPUT/'comparison/trades.jsonl.gz')
    new=r.read_lines(r.ROOT/r.OUTPUT/'comparison/trades.jsonl.gz')
    result=[]
    for lane in r.old.LANES:
        parent=[t for t in trades if t['lane_id']==lane]
        child_ids={t['identity'] for t in (previous if lane==r.old.LANES[2] else new) if t['lane_id']==lane and t['scenario']=='child'}
        _,loss=diagnostics(parent,*p['development_interval_ms'])
        _,win=diagnostics([{**t,'net_bps':-t['net_bps']} for t in parent],*p['development_interval_ms'])
        pools={'loss_streak':[t for t in parent if loss.get(t['identity'],0)>=2],
               'win_streak':[t for t in parent if win.get(t['identity'],0)>=2],
               'ordinary':[t for t in parent if loss.get(t['identity'],0)<2 and win.get(t['identity'],0)<2]}
        for category,pool in pools.items():
            if not pool:
                result.append({'lane':lane,'category':category,'state':'NO_SAMPLE'});continue
            t=min(pool,key=lambda t:r.old.digest(['chart_fixed_20260905',lane,category,t['identity']]))
            rows=(one if lane in r.old.LANES[:2] else four)[t['symbol']];i=t['signal_index']
            lo=max(0,i-20);hi=min(len(rows),i+61);features=Features(rows,t['native_interval_ms'])
            closes=[x['close'] for x in rows];ema20=kernel.ema(closes,20);ema50=kernel.ema(closes,50)
            result.append(dict(lane=lane,category=category,state='SELECTED',pool_size=len(pool),trade=t,
                retained_by_child=t['identity'] in child_ids,posthoc_stratum_never_entry_input=True,
                source_start_index=lo,source_end_index_exclusive=hi,bars=rows[lo:hi],
                ema20=ema20[lo:hi],ema50=ema50[lo:hi],adx14=features.dmi['adx'][lo:hi],
                plus_di14=features.dmi['plus_di'][lo:hi],minus_di14=features.dmi['minus_di'][lo:hi],
                research_atr_state_line=features.st['line'][lo:hi],entry_features=features.at(i,t['side']),
                winner_or_loss_stratum='RETROSPECTIVE_DIAGNOSTIC_ONLY',
                price_semantics='ACTUAL_FROZEN_OHLCV; MODELLED_NATIVE_FILLS; NATIVE_EXIT_TIME_IS_BAR_CLOSE_UPPER_BOUND'))
    return r.old.seal({'batch_id':'TOP5_EXTERNAL_20260905_V1','sample_rule':'HASH_MIN_PER_LANE_AND_STREAK_STRATUM; WINDOW_SIGNAL_MINUS20_PLUS60_CLIPPED_TO_DEV','rows':result,'validation_OOS_read':False,'no_G6_exit_optimization':True,'new_G5B_T':0})


def plot(value,out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    from datetime import datetime,timezone
    for lane,name in NAMES.items():
        cases=[x for x in value['rows'] if x['lane']==lane]
        fig,axs=plt.subplots(3,3,figsize=(18,10),gridspec_kw={'height_ratios':[3,1,1.6]})
        for col,case in enumerate(cases):
            if case['state']!='SELECTED':
                axs[0,col].text(.1,.5,case['category']+': no sample');continue
            rows=case['bars'];t=case['trade'];lo=case['source_start_index'];x=list(range(len(rows)))
            price=axs[0,col]
            for j,bar in enumerate(rows):
                color='#007f73' if bar['close']>=bar['open'] else '#bf4b45'
                price.vlines(j,bar['low'],bar['high'],color=color,linewidth=.6)
                price.add_patch(Rectangle((j-.32,min(bar['open'],bar['close'])),.64,max(abs(bar['close']-bar['open']),bar['close']*.00001),color=color,alpha=.85))
            price.plot(x,case['ema50'],label='EMA50',lw=1,color='#335cbb')
            if lane==r.old.LANES[3]:
                price.plot(x,case['ema20'],label='EMA20',lw=1,color='#925ab5')
                price.plot(x,case['research_atr_state_line'],label='Research ATR10x3',lw=.8,color='#b58c15')
            signal=t['signal_index']-lo;entry=t['entry_index']-lo;exit=t['exit_index']-lo
            price.axvline(signal,color='#666666',ls=':',lw=.8)
            price.scatter([entry],[t['entry_price']],marker='^',c='black',s=35,label='Entry fill')
            price.scatter([exit],[t['exit_price']],marker='x',c='black',s=35,label='Exit fill')
            price.set_title(f"{case['category']} | {t['symbol']} | {t['side']}\nnet {t['net_bps']:.1f} bps | child {'kept' if case['retained_by_child'] else 'removed'}",fontsize=11)
            price.legend(fontsize=7,loc='best');price.ticklabel_format(axis='y',style='plain',useOffset=False)
            axs[1,col].bar(x,[b['volume'] for b in rows],color='#6d90a2',width=.7)
            axs[1,col].set_ylabel('Total volume',fontsize=8)
            for key,color,label in [('adx14','#6a4c93','ADX14'),('plus_di14','#007f73','+DI14'),('minus_di14','#bf4b45','-DI14')]:axs[2,col].plot(x,case[key],color=color,lw=1,label=label)
            axs[2,col].legend(fontsize=8)
            stamps=[0,len(rows)//2,len(rows)-1]
            def timestamp(row):return row.get('bar_open_ts',row.get('ts_ms'))
            axs[2,col].set_xticks(stamps,[datetime.fromtimestamp(timestamp(rows[j])/1000,timezone.utc).strftime('%m-%d\n%H:%M') for j in stamps])
            for ax in axs[:,col]:ax.grid(alpha=.15);ax.tick_params(labelsize=8)
            axs[0,col].set_xticklabels([]);axs[1,col].set_xticklabels([])
        fig.suptitle(name+' | Fixed development case sample | UTC',fontsize=16)
        fig.text(.5,.018,'Strata use completed-trade outcomes for diagnosis only. Native stops may fill before the exit-bar close; later OHLC is not an actionable excursion.',ha='center',fontsize=9)
        fig.tight_layout(rect=[0,.05,1,.95]);fig.savefig(out/(lane+'.png'),dpi=140);plt.close(fig)


def run(data_dir,verify_only=False):
    out=r.ROOT/r.OUTPUT/'charts';out.mkdir(parents=True,exist_ok=True)
    value=build(data_dir);path=out/'cases.json'
    r.old.probe.write_immutable(path,r.old.probe.canonical(value),verify_only=verify_only)
    if not verify_only:plot(value,out)
    return value

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--data-dir',type=Path,required=True);ap.add_argument('--verify-only',action='store_true');a=ap.parse_args()
    print(run(a.data_dir,a.verify_only)['receipt_sha256'])
