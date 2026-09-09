"""Recompute post-run interpretation from preserved rows, no strategy replay."""
import json,math
from collections import Counter
import verify_saved as s

def derive(parent,child,accounting,v):
    pi,ci=v.complete_index(parent),v.complete_index(child);changed=[]
    for key in sorted(pi.keys()|ci.keys()):
        old,new=v.values(pi.get(key)),v.values(ci.get(key));delta=new['net_bps']-old['net_bps']
        if delta:
            row=ci.get(key,pi.get(key))[1]
            changed.append(dict(symbol=row['symbol'],origin=row['origin_key'],signal_ts=row['signal_ts'],delta_bps=delta,
                                old_net=old['net_bps'],new_net=new['net_bps'],reason=row.get('exit_reason')))
    by={sym:sum(x['delta_bps'] for x in changed if x['symbol']==sym) for sym in sorted({x['symbol'] for x in changed})}
    peak=worst=0.;peakrow=None;window=None
    for row in parent['metrics']['daily']:
        equity=row['cumulative_net_mark_bps']
        if equity>peak:peak=equity;peakrow=row
        if peak-equity>worst:worst=peak-equity;window=(peakrow,row)
    s.need(window is not None,'PARENT_DD_WINDOW_MISSING');start,end=window
    daily={r['mark_ts']:r for r in child['metrics']['daily']}
    pc=end['cumulative_net_mark_bps']-(start['cumulative_net_mark_bps'] if start else 0.)
    cc=daily[end['mark_ts']]['cumulative_net_mark_bps']-(daily[start['mark_ts']]['cumulative_net_mark_bps'] if start else 0.)
    effects={k:x for k,x in accounting['resolved_common_effects'].items() if isinstance(x,(int,float))}
    dn=child['metrics']['terminal_net_bps']-parent['metrics']['terminal_net_bps']
    s.need(bool(changed),'NO_CHANGED_ORIGINS');largest=max(changed,key=lambda x:x['delta_bps'])
    return dict(net_delta_bps=dn,cost2_delta_bps=child['metrics']['terminal_cost2x_net_bps']-parent['metrics']['terminal_cost2x_net_bps'],
        checks=s.checks(parent['metrics'],child['metrics'],v),changed_trades=len(changed),
        net_improves_T=sum(x['delta_bps']>0 for x in changed),net_worsens_T=sum(x['delta_bps']<0 for x in changed),
        sign_transitions=accounting['sign_transitions'],effects=effects,by_symbol=by,
        parent_DD_window=dict(start_ts=start['mark_ts'] if start else None,end_ts=end['mark_ts'],parent_change_bps=pc,child_change_bps=cc,delta_bps=cc-pc),
        largest_positive_change=largest,net_without_largest_positive=dn-largest['delta_bps'],net_without_hype=dn-by.get('HYPE-USDT',0.))

def check_tree(actual,expected,v):
    if isinstance(expected,dict):
        s.need(isinstance(actual,dict) and set(actual)==set(expected),'DERIVED_KEYS')
        for k,value in expected.items():check_tree(actual[k],value,v)
    elif type(expected) is int:s.need(type(actual) is int and actual==expected,'DERIVED_INTEGER')
    else:v.same(actual,expected,'DERIVED_DETAILS')

def table(per,label,result):
    m=result['metrics'];b=m['base_cost'];fmt=lambda x:'NA' if x is None else f'{x:.2f}'
    return '|'+ '|'.join([per,label,f"{len(result['trades'])}/{len(result['open_observations'])}",fmt(None if b['win_rate'] is None else 100*b['win_rate'])]+[fmt(b[k]) for k in ('average_win_bps','average_loss_bps','realized_payoff','PF')]+[fmt(m[k]) for k in ('terminal_net_bps','terminal_cost2x_net_bps','marked_DD_trade_sum_bps')])+'|'

def verify(root=s.HERE):
    root=s.Path(root);repo=root.parents[2];v=s.checker(repo);saved=s.read(root/'DETAILS.json');report=(root/'REPORT.md').read_text();interpretation=(root/'INTERPRETATION.md').read_text();answer={};derived={}
    old_manifest=repo/s.PARENT/'FINAL_HASHES.json'
    s.need(s.sha(old_manifest)=='6aed19ef05f68518c1257916b6239f04120de636e4fd386fb9727fa056d25d64','C54_MANIFEST_DRIFT')
    for per in s.PERIODS:
        parent=s.gz(repo/s.PARENT/'B'/per/'RESULT.json.gz');child=s.gz(root/per/'RESULT.json.gz');account=s.read(root/per/'ACCOUNTING_C54.json')
        v.compare_parent(parent,child,account);d=derive(parent,child,account,v);check_tree(saved[per],d,v);derived[per]=d
        s.need(table(per,'C54',parent) in report and table(per,'C57',child) in report,'REPORT_TABLE')
        # KR3 cumulative bridge uses immutable original C54-to-KR3 controls.
        rel='B/'+per+'/ACCOUNTING_KR3.json';path=repo/s.PARENT/rel
        s.need(s.sha(path)==s.read(old_manifest)[rel],'KR3_REFERENCE_DRIFT')
        original=s.read(path)['bridges'];current=s.read(root/per/'ACCOUNTING_KR3.json');ci=v.complete_index(child)
        for basis,closed in [('marked',False),('closed',True)]:
            pv=original[basis]['parent'];cv={k:sum(v.values(t,closed)[k] for t in ci.values()) for k in v.values(None)}
            delta={k:cv[k]-pv[k] for k in cv}
            v.subset(current['bridges'][basis],dict(parent=pv,child=cv,delta=delta),'KR3_CUMULATIVE_BRIDGE')
            v.same({k:sum(g[basis]['delta'][k] for g in current['groups'].values()) for k in cv},delta,'KR3_GROUP_SUM')
        answer[per]={k:d[k] for k in ('net_delta_bps','cost2_delta_bps','checks','changed_trades','parent_DD_window','net_without_largest_positive','net_without_hype')}
    for label,key,negative in [('Old-loss improvement','saved_common_loss_bps',False),('Old-loss deterioration','worsened_common_loss_bps',True),('Original winner positive profit lost','cut_positive_winner_profit_bps',True),('Additional loss on original winners','additional_loss_on_parent_winners_bps',True)]:
        cells=[f"{(-1 if negative else 1)*derived[per]['effects'][key]:+.2f}" for per in s.PERIODS]
        s.need('|'+label+'|'+'|'.join(cells)+'|' in interpretation,'INTERPRETATION_CONTRIBUTION')
    cells=[f"{derived[per]['net_delta_bps']:+.2f}" for per in s.PERIODS]
    s.need('|Total terminal net increment|'+'|'.join(cells)+'|' in interpretation,'INTERPRETATION_TOTAL')
    return dict(postrun_interpretation_recomputed=True,economic_replays=0,periods=answer)
if __name__=='__main__':print(json.dumps(verify(),indent=2))
