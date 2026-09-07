"""Stored-ledger causal opportunity diagnosis. Never calls a strategy replay."""
from collections import Counter,defaultdict
from pathlib import Path
import gzip
import json
from backend.research.rebuild import top5_mechanism_a_v1 as a


def load(kind,period):
    return a.prior.read_artifact(a.OUTPUT+'/'+kind+'/receipt.json',period)


def all_positions(view):
    return view['trades']+view['open_observations']


def diagnosis(periods):
    out={'basis':'STORED_PATHS_AND_BOUNDED_EXISTING_OBSERVATIONS_ONLY','new_market_paths':0,
         'initial_analysis_correction':'KR2 artifact effects[M2] targets KR2, so KR1 effects are independently formed from stored M2 and KR1_FULL views. No candidate economics observed.',
         'periods':{}}
    for period,rows in periods.items():
        k=load('KR2',period);v=k['views']['KR1_FULL'];effects=a.metrics.effects(k['views']['M2'],v)
        perorigin={e['origin_key']:e for e in effects['per_origin']};decisions=[]
        for t in all_positions(v):
            ext=t.get('runner_extension',{})
            if not ext.get('allowed'):continue
            history=[z for z in v['trace'] if z['symbol']==t['symbol'] and z['signal_index']==t['signal_index']
              and z['kind']=='FIRST_LOW_BREACH_CONTEXT' and z['ts']<=ext['ts']]
            status=history[-1]['status'] if history else 'FIRST_LOW_BREACH_UNCHECKED'
            row={'origin_key':t['origin_key'],'symbol':t['symbol'],'signal_index':t['signal_index'],
              'extension_decision':ext,'state_available_at_decision':status,
              'state_observation':history[-1] if history else None,'stored_parent_effect':perorigin[t['origin_key']]}
            decisions.append(row)
        groups={}
        for status in sorted({x['state_available_at_decision'] for x in decisions}):
            es=[x['stored_parent_effect'] for x in decisions if x['state_available_at_decision']==status]
            groups[status]={'T':len(es),'help_T':sum(e['delta']['net_bps']>0 for e in es),
              'harm_T':sum(e['delta']['net_bps']<0 for e in es),
              'positive_net_delta':sum(max(0,e['delta']['net_bps']) for e in es),
              'negative_net_delta':sum(min(0,e['delta']['net_bps']) for e in es),
              'ordinary_winner_harm_T':sum(e['parent_winner'] and not e['parent_large_winner'] and e['delta']['net_bps']<0 for e in es),
              'large_winner_harm_T':sum(e['parent_large_winner'] and e['delta']['net_bps']<0 for e in es)}
        windows={}
        for owner in ('M2','KR1_FULL'):
            w=k['stages'][owner]['marked_diagnostics']['worst_window'];changes={}
            for name in ('M2','KR1_FULL'):
                days={d['mark_ts']:d for d in k['stages'][name]['daily']}
                changes[name]={field:days[w['end_ms']][field]-days[w['start_ms']][field]
                    for field in ('cumulative_net_mark_bps','cumulative_gross_mark_bps','full_cost_bps_at_valuation')}
            windows[owner]={'fixed_window':w,'same_window_changes':changes}
        br=load('BR1',period);full=br['views']['FULL'];pv=br['views']['P'];collisions=[]
        for event in full['events']:
            if event['status']!='EXCLUDED':continue
            candidates=[t for t in all_positions(full) if t['symbol']==event['symbol'] and
              t['signal_index']<event['signal_index']<=t.get('exit_index',t.get('mark_index'))]
            if not candidates:continue
            owner=max(candidates,key=lambda t:t['signal_index'])
            if not owner.get('runner_extension',{}).get('allowed') or event['signal_index']<owner['signal_index']+6:continue
            parent=next((t for t in all_positions(pv) if t['symbol']==event['symbol'] and t['signal_index']==event['signal_index']),None)
            nxt={n:next(({'signal_index':t['signal_index'],'entry_ts':t['entry_ts'],'origin_key':t['origin_key']}
                 for t in sorted(all_positions(view),key=lambda t:t['entry_ts']) if t['symbol']==event['symbol'] and t['signal_index']>event['signal_index']),None)
                 for n,view in (('V2',pv),('BR1',full))}
            rr=rows[event['symbol']][event['signal_index']]
            cap=owner.get('exit_index')==owner['signal_index']+12 and owner.get('exit_ts')==event['signal_ts'] and owner.get('exit_reason')!=a.finite.EXIT
            collisions.append({'symbol':event['symbol'],'event':event,'owner_origin':owner['origin_key'],
              'owner_entry':owner['entry_ts'],'owner_signal_index':owner['signal_index'],
              'owner_actual_exit_or_mark':owner.get('exit_ts',owner.get('mark_ts')),
              'current_completed_bar':rr,'owner_entry_price':owner['entry_price'],
              'already_completed_extension_cap':cap,
              'stored_V2_admitted_trade':parent,'next_stored_admitted':nxt,
              'missing_V2_trade_is_not_zero_return':parent is None})
        out['periods'][period]={'KR1':{'all_extension_decisions':decisions,'state_groups':groups,
             'M2_to_KR1_all_origins':effects,'same_window_DD':windows,
             'KR2_to_KR1_saved_effect':k['effects']['KR1_FULL']},
             'BR1':{'all_extension_collisions':collisions,'collision_T':len(collisions),
             'completed_cap_collisions_T':sum(c['already_completed_extension_cap'] for c in collisions),
             'existing_fixed_full_bridge':br['fixed_full_bridge']['terminal'],
             'no_counterfactual_trades_computed':True}}
    return out


def historical_rows_bridge(path):
    rows=json.loads(path.read_text())['trades'];ordered=sorted(rows,key=lambda t:(t['entry_ts'],t['symbol']))
    kept=[];blocked={};overlaps=[]
    for t in ordered:
        prior=[q for q in rows if q['symbol']==t['symbol'] and q['entry_ts']<t['entry_ts']<q['exit_ts']]
        if prior:overlaps.append({'symbol':t['symbol'],'entry_ts':t['entry_ts'],'prior_entry_ts':[q['entry_ts'] for q in prior]})
        if t['entry_ts']<=blocked.get(t['symbol'],-1):continue
        kept.append(t);blocked[t['symbol']]=t['exit_ts']+2*3600000
    def dd(ts):
        eq=peak=maximum=0.
        for t in ts:eq+=t['net_bps'];peak=max(peak,eq);maximum=max(maximum,peak-eq)
        return maximum
    return {'file_sha256':a.old.file_sha(path),'T':len(rows),'wins':sum(t['net_bps']>0 for t in rows),
      'gross':sum(t['gross_bps'] for t in rows),'net':sum(t['net_bps'] for t in rows),
      'cost':sum(t['realized_cost_bps'] for t in rows),'side':dict(Counter(t['side'] for t in rows)),
      'duplicate_intents':len(rows)-len({t['intent_sha'] for t in rows}),
      'gross_error':max(abs((1 if t['side']=='long' else -1)*(t['exit']/t['entry']-1)*10000-t['gross_bps']) for t in rows),
      'net_error':max(abs(t['gross_bps']-t['realized_cost_bps']-t['net_bps']) for t in rows),
      'overlap_incoming_T':len(overlaps),'overlaps':overlaps,'stored_order_DD':dd(rows),
      'closed_exit_order_DD':dd(sorted(rows,key=lambda t:(t['exit_ts'],t['entry_ts'],t['symbol']))),
      'saved_rows_subset_only':{'T':len(kept),'wins':sum(t['net_bps']>0 for t in kept),
       'net':sum(t['net_bps'] for t in kept),'keys':[(t['symbol'],t['entry_ts']) for t in kept]},
      'full_market_replay':False,'same_historical_raw_bridge':'UNRESOLVED'}


def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--data-dir',required=True);p.add_argument('--out',required=True);args=p.parse_args()
    c=a.old.read(a.SPEC);_,_,periods,_=a.account.load_inputs(Path(args.data_dir),c)
    data=diagnosis(periods);out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    a.old.probe.write_immutable(out,gzip.compress(a.old.probe.canonical(data),mtime=0))
    print(json.dumps({per:{'KR1_groups':d['KR1']['state_groups'],'BR1_collisions':d['BR1']['collision_T'],
      'BR1_completed_cap_collisions':d['BR1']['completed_cap_collisions_T']} for per,d in data['periods'].items()}))


if __name__=='__main__':main()
