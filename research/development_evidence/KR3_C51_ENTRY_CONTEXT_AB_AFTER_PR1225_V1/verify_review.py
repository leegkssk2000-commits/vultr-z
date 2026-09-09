"""PR1226 P2 follow-up: independently derive interpretation; no price replay."""
import argparse,fnmatch,hashlib,json,math
from collections import Counter
from pathlib import Path
import verify_saved as s


def derive(parent,child,v):
    p,c=v.complete_index(parent),v.complete_index(child)
    pn=sum(v.values(t)['net_bps'] for t in p.values());cn=sum(v.values(t)['net_bps'] for t in c.values())
    dn=cn-pn
    def sign(item):
        if item is None:return 'ABSENT'
        if item[0]=='O':return 'OPEN'
        n=item[1]['net_bps'];return 'WIN' if n>0 else 'LOSS' if n<0 else 'FLAT'
    changes=[]
    for k in sorted(p.keys()|c.keys()):
        row=c.get(k,p.get(k))[1]
        changes.append(dict(origin=row['origin_key'],symbol=k[0],signal_ts=k[2],delta_bps=v.values(c.get(k))['net_bps']-v.values(p.get(k))['net_bps']))
    largest=max(changes,key=lambda x:(x['delta_bps'],x['origin']))
    winners=sorted((t for t in p.values() if t[0]=='C' and t[1]['net_bps']>0),key=lambda t:(-t[1]['net_bps'],t[1]['origin_key']))
    def retention(items):
        return sum(min(t[1]['net_bps'],max(0,v.values(c.get(v.identity(t[1])))['net_bps'])) for t in items)/sum(t[1]['net_bps'] for t in items)
    hype=sum(x['delta_bps'] for x in changes if x['symbol']=='HYPE-USDT')
    pm,cm=parent['metrics'],child['metrics'];pb,cb=pm['base_cost'],cm['base_cost']
    removed=[t for k,t in p.items() if k not in c]
    result=dict(net_delta_bps=dn,cost2_delta_bps=sum(v.values(t)['cost2x_net_bps'] for t in c.values())-sum(v.values(t)['cost2x_net_bps'] for t in p.values()),
        WR_delta_pp=100*(cb['win_rate']-pb['win_rate']),DD_delta_bps=cm['marked_DD_trade_sum_bps']-pm['marked_DD_trade_sum_bps'],
        avoided_closed_loss_bps=-sum(t[1]['net_bps'] for t in removed if t[0]=='C' and t[1]['net_bps']<0),
        foregone_closed_win_bps=sum(t[1]['net_bps'] for t in removed if t[0]=='C' and t[1]['net_bps']>0),
        avoided_open_mark_bps=-sum(v.values(t)['net_bps'] for t in removed if t[0]=='O'),
        winner_amount_retention=retention(winners),large_winner_retention=retention(winners[:math.ceil(.1*len(winners))]),
        largest_positive_origin=largest,net_without_largest_increment_bps=dn-largest['delta_bps'],top_positive_increment_over_net=largest['delta_bps']/dn,
        hype_delta_bps=hype,without_hype_delta_bps=dn-hype,parent_average_loss_bps=pb['average_loss_bps'],child_average_loss_bps=cb['average_loss_bps'],
        sign_transitions=dict(Counter(sign(p.get(k))+'->'+sign(c.get(k)) for k in p.keys()|c.keys())),
        daily_DD_interpretation='UNCHANGED_WITHIN_EXISTING_VERIFIER_PRECISION' if v.near(pm['marked_DD_trade_sum_bps'],cm['marked_DD_trade_sum_bps']) else 'REDUCED' if cm['marked_DD_trade_sum_bps']<pm['marked_DD_trade_sum_bps'] else 'INCREASED')
    return result


def check_derived(actual, expected, v, where='INTERPRETATION'):
    if isinstance(expected,dict):
        s.require(isinstance(actual,dict) and set(actual)==set(expected),'DERIVED_KEYS:'+where)
        for k,value in expected.items():check_derived(actual[k],value,v,where+'.'+str(k))
    elif isinstance(expected,int):s.require(type(actual) is type(expected) and actual==expected,'DERIVED_INTEGER:'+where)
    else:v.same(actual,expected,where)


def markdown_checks(text,parents,children,ds,v):
    """Bind each quantitative economic paragraph/table in original human report."""
    def need(fragment):s.require(fragment in text,'INTERPRETATION_MARKDOWN:'+fragment[:90])
    metrics=[('WR','win_rate',100,2),('PF','PF',1,3),('Mean loss','average_loss_bps',1,2)]
    for label,key,mul,dec in metrics:
        cells=[]
        for per in s.PERIODS:
            p,c=parents[per]['metrics']['base_cost'],children[per]['metrics']['base_cost']
            cells.append(f"{mul*p[key]:.{dec}f}→{mul*c[key]:.{dec}f}"+('%' if key=='win_rate' else ''))
        need('|'+label+'|'+'|'.join(cells)+'|')
    for label,key in [('Terminal net','terminal_net_bps'),('All-cost2','terminal_cost2x_net_bps'),('Daily markedDD','marked_DD_trade_sum_bps')]:
        cells=[]
        for per in s.PERIODS:
            p,c=parents[per]['metrics'],children[per]['metrics']
            cells.append(f'{p[key]:.2f}→{c[key]:.2f}'+(' unchanged' if key=='marked_DD_trade_sum_bps' and v.near(p[key],c[key]) else ''))
        need('|'+label+'|'+'|'.join(cells)+'|')
    cells=[f"{len(parents[per]['trades'])}/{len(parents[per]['open_observations'])}→{len(children[per]['trades'])}/{len(children[per]['open_observations'])}" for per in s.PERIODS]
    need('|Closed/open|'+'|'.join(cells)+'|')
    for per,year in zip(s.PERIODS,(2025,2026)):
        d=ds[per];t=d['sign_transitions']
        need(f"{year}: avoided{t['LOSS->ABSENT']} completed losses+{d['avoided_closed_loss_bps']:.2f}, missed{t['WIN->ABSENT']} wins−{d['foregone_closed_win_bps']:.2f}, excluded{t['OPEN->ABSENT']} hypothetical open loss+{d['avoided_open_mark_bps']:.2f} = +{d['net_delta_bps']:.2f}bps." if year==2025 else f"{year}: avoided{t['LOSS->ABSENT']} completed losses+{d['avoided_closed_loss_bps']:.2f}, missed{t['WIN->ABSENT']} win−{d['foregone_closed_win_bps']:.2f}, excluded{t['OPEN->ABSENT']} hypothetical open losses+{d['avoided_open_mark_bps']:.2f} = +{d['net_delta_bps']:.2f}bps.")
    d1,d2=[ds[p] for p in s.PERIODS]
    need(f"Closed-only increment is+{d1['net_delta_bps']-d1['avoided_open_mark_bps']:.2f}/+{d2['net_delta_bps']-d2['avoided_open_mark_bps']:.2f}bps")
    need(f"General original positive-profit retention{100*d1['winner_amount_retention']:.2f}%/{100*d2['winner_amount_retention']:.2f}%; top-decile{100*d1['large_winner_retention']:.0f}%/{100*d2['large_winner_retention']:.0f}%")
    need(f"2025 net increment without HYPE's+{d1['hype_delta_bps']:.2f} contribution is only+{d1['without_hype_delta_bps']:.2f}bps.")
    need(f"Removing the single largest positive increment(+{d1['largest_positive_origin']['delta_bps']:.2f} PEPE avoided loss) gives−{abs(d1['net_without_largest_increment_bps']):.2f}bps.")
    need(f"2026's largest positive increment is+{d2['largest_positive_origin']['delta_bps']:.2f}, leaving+{d2['net_without_largest_increment_bps']:.2f}")
    need(f"HYPE increment{d2['hype_delta_bps']:.0f}")
    wins=[(parents[p]['metrics']['base_cost']['wins'],children[p]['metrics']['base_cost']['wins']) for p in s.PERIODS]
    losses=[(parents[p]['metrics']['base_cost']['losses'],children[p]['metrics']['base_cost']['losses']) for p in s.PERIODS]
    need(f"Total win count declines{wins[0][0]}→{wins[0][1]} and{wins[1][0]}→{wins[1][1]} while loss counts decline{losses[0][0]}→{losses[0][1]} and{losses[1][0]}→{losses[1][1]}")
    need('Strict 8/8 success is NOT established.')


def coverage(workflow,spec):
    import re
    patterns=re.findall(r"^\s+- '([^']+)'\s*$",workflow,re.M)
    files=set(spec['source_files_sha256'])|{s.PRIOR,s.PARENT+'/COSTS.json',s.PARENT+'/SPEC.json',s.PARENT+'/verify_saved.py'}
    files|={s.PARENT+'/'+p+'/RESULT.json.gz' for p in s.PERIODS}
    for path in files:s.require(any(fnmatch.fnmatchcase(path,q) for q in patterns),'UNTRIGGERED_DEPENDENCY:'+path)


def verify(root=s.HERE):
    root=Path(root);repo=root.parents[2];v=s.load_checker(repo)
    parents={p:s.gz(repo/s.PARENT/p/'RESULT.json.gz') for p in s.PERIODS}
    children={p:s.gz(root/'B'/p/'RESULT.json.gz') for p in s.PERIODS}
    derived={p:derive(parents[p],children[p],v) for p in s.PERIODS}
    saved=s.read(root/'INTERPRETATION.json');check_derived(saved['periods'],derived,v)
    markdown_checks((root/'INTERPRETATION.md').read_text(),parents,children,derived,v)
    for mode in ('A','AB'):
        for per in s.PERIODS:
            child=s.gz(root/mode/per/'RESULT.json.gz');a=s.read(root/mode/per/'ACCOUNTING_C51.json')
            v.compare_parent(parents[per],child,a)
            s.require(child['metrics']['terminal_net_bps']<0,'REJECTED_VARIANT_IS_NOT_NEGATIVE')
    text=(root/'INTERPRETATION.md').read_text()
    aq=[s.gz(root/'A'/p/'RESULT.json.gz')['metrics']['base_cost'] for p in s.PERIODS]
    ab=[s.gz(root/'AB'/p/'RESULT.json.gz')['metrics']['base_cost'] for p in s.PERIODS]
    removed=[s.read(root/'A'/p/'ACCOUNTING_C51.json')['sign_transitions']['WIN->ABSENT'] for p in s.PERIODS]
    s.require(f"A retained{aq[0]['completed_T']}closed2025 and{aq[1]['completed_T']}closed2026" in text,'MARKDOWN_A_COUNT')
    s.require(f"it rejected{removed[0]}/{removed[1]} original winners and kept only{aq[0]['wins']}/{aq[1]['wins']}" in text,'MARKDOWN_A_WINNERS')
    s.require(f"Net−{abs(aq[0]['net_bps']):.2f}/−{abs(aq[1]['net_bps']):.2f}bps" in text,'MARKDOWN_A_NET')
    s.require(f"AB retained{ab[0]['completed_T']}/{ab[1]['completed_T']} and still{ab[0]['wins']}/{ab[1]['wins']} wins; net−{abs(ab[0]['net_bps']):.2f}/−{abs(ab[1]['net_bps']):.2f}" in text,'MARKDOWN_AB')
    coverage((repo/'.github/workflows/kr3-c51-entry-context-v1.yml').read_text(),s.read(root/'SPEC.json'))
    return {'interpretation_recomputed':True,'pinned_dependency_trigger_coverage':True,'economic_replays':0}

if __name__=='__main__':
    print(json.dumps(verify(),indent=2))
