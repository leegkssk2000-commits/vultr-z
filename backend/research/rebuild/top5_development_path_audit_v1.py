"""NO-CREDIT held-bar path report; never selects or optimizes an exit."""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
from backend.research.rebuild import top5_development_repair_v1 as core


def run(data_dir,verify_only=False):
    p=core.read(core.POLICY);old=core.read(core.probe.POLICY)
    dev=core.require_development(core.read(core.probe.STAGE),core.ROOT)
    root=core.ROOT/core.OUTPUT;out=root/'path_audit'
    native_manifest=json.loads((root/'native_1h/manifest.json').read_text())
    if core.file_sha(root/'native_1h/manifest.json')!=p['native_manifest_file_sha256']:raise RuntimeError('NATIVE_MANIFEST_SHA')
    if not verify_only:out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((data_dir/'development_manifest.json').read_text())
    allowed=[data_dir/'development_manifest.json']+[data_dir/x for x in manifest['dataset_files']]+[data_dir/x['path'] for x in manifest['cost_snapshots'].values()]
    allowed += [root/'native_1h'/(s+'.json.gz') for s in p['native_symbols']]
    allowed += [root/'comparison/trades.jsonl.gz',root/'comparison/receipt.json']
    with core.probe.io_boundary(allowed,out):
        four,_=core.probe.load_development(data_dir,old,dev)
        one={s:json.loads(gzip.decompress((root/'native_1h'/(s+'.json.gz')).read_bytes())) for s in p['native_symbols']}
        for s in one:
            if core.file_sha(root/'native_1h'/(s+'.json.gz'))!=native_manifest['symbols'][s]['file_sha256']:raise RuntimeError('NATIVE_DATA_SHA')
        trades=[json.loads(x) for x in gzip.decompress((root/'comparison/trades.jsonl.gz').read_bytes()).splitlines()]
        result=json.loads((root/'comparison/receipt.json').read_text());groups=defaultdict(list);exit_groups=defaultdict(list)
        core.probe.verify_seal(result,'COMPARISON')
        if core.file_sha(root/'comparison/trades.jsonl.gz')!=result['artifacts']['trades']['file_sha256']:raise RuntimeError('TRADE_LEDGER_SHA')
        for t in trades:
            rows=(one if t['native_interval_ms']==3600000 else four)[t['symbol']]
            sign=1 if t['side']=='long' else -1
            for j in range(t['entry_index'],t['exit_index']+1):
                terminal=j==t['exit_index'];price=t['exit_price'] if terminal else rows[j]['close']
                gross=sign*(price/t['entry_price']-1)*10000
                key=(t['lane_id'],t['scenario'],(j-t['entry_index']+1)*t['native_interval_ms']//3600000)
                groups[key].append(gross)
                if terminal:exit_groups[key].append(t['net_bps'])
        rows=[]
        for (lane,scenario,hour),values in sorted(groups.items()):
            exits=exit_groups[(lane,scenario,hour)]
            rows.append({'lane_id':lane,'scenario':scenario,'elapsed_bar_close_upper_bound_hours':hour,
                         'trades_still_held_through_this_bar':len(values),'mean_gross_path_bps':sum(values)/len(values),
                         'trades_ending_in_this_bar':len(exits),'ending_trade_mean_net_bps':sum(exits)/len(exits) if exits else None})
        receipt=core.seal({'schema':'top5.development.path_observer.v1','comparison_receipt_sha256':result['receipt_sha256'],
                           'scope':'G5_NO_CREDIT_OBSERVER','exit_candidates_tested':0,'exit_optimization':False,
                           'rows':rows,'price_semantics':'INTERMEDIATE_CLOSED_BAR_MARK; TERMINAL_NATIVE_EXIT_PRICE',
                           'time_semantics':'EXIT_BAR_CLOSE_UPPER_BOUND; EXACT_INTRABAR_NATIVE_FILL_TIME_UNKNOWN',
                           'selection_bias':'LATER_NATIVE_HORIZONS_CONTAIN_ONLY_STILL_HELD_TRADES; DO_NOT_RANK_HORIZONS',
                           'formal_credit':0,'G6_authorized':False,**core.probe.DEV_AUTH})
        core.probe.write_immutable(out/'receipt.json',core.probe.canonical(receipt),verify_only=verify_only)
    return receipt


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--data-dir',type=Path,required=True);ap.add_argument('--verify-only',action='store_true');a=ap.parse_args()
    print(run(a.data_dir,a.verify_only)['receipt_sha256'])
