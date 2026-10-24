"""Existing Work D's bounded HGL1 DEV entry point. No network/collector/order API."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from collections import Counter
from datetime import datetime, timezone

from input_gate import GateError, preflight
from reference import run, costs

HERE = Path(__file__).resolve().parent
CANDIDATE = 'HGL1_RASCHKE_FIRST_PULLBACK_LONG_ZEL_V1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metrics(rows, key):
    values = [r[key] for r in rows]
    wins = sum(v > 0 for v in values)
    plus, minus = sum(max(v, 0) for v in values), -sum(min(v, 0) for v in values)
    eq = peak = dd = 0.0
    streak = worst = 0
    for v in values:
        eq += v
        peak = max(peak, eq)
        dd = max(dd, peak-eq)
        streak = streak+1 if v < 0 else 0
        worst = max(worst, streak)
    return {'T':len(values), 'sum_trade_bps':sum(values),
            'expectancy_bps':sum(values)/len(values) if values else None,
            'WR_pct':100*wins/len(values) if values else None,
            'PF':plus/minus if minus else None,
            'PF_note':'NO_LOSSES_UNDEFINED' if not minus else None,
            'exit_order_trade_bps_DD':dd, 'max_loss_streak':worst}


def evaluate(bound, manifest):
    all_rows, all_censored, per_symbol, intervals = [], [], {}, []
    for symbol in manifest['symbols']:
        bars = bound['bars_by_symbol'][symbol]
        result = run(bars, manifest['tick_sizes'][symbol])
        for row in result['trades']:
            row.update(symbol=symbol,
                       entry_bar_open_ms=bars[row['entry_index']]['timestamp_ms'],
                       exit_bar_open_ms=bars[row['exit_index']]['timestamp_ms'])
            all_rows.append(row)
            intervals.append((row['entry_bar_open_ms'],row['exit_bar_open_ms']+3600000,symbol))
        for row in result['censored']:
            row['symbol'] = symbol
            if row['kind'] == 'OPEN_POSITION':
                row['hypothetical_mark_liquidation'] = costs(row['mark_gross_bp'])
                intervals.append((bars[row['entry_index']]['timestamp_ms'],
                                  bars[-1]['timestamp_ms']+3600000,symbol))
            all_censored.append(row)
        per_symbol[symbol] = result
    # Exit timestamps are bar intervals, not execution timestamps. This is a declared tie order.
    rows = sorted(all_rows, key=lambda r:(r['exit_bar_open_ms'],r['symbol'],r['entry_bar_open_ms']))
    events = Counter(r['entry_bar_open_ms'] for r in rows)
    # Include censored entries in frequency, never quietly discard open losing exposure.
    for row in all_censored:
        if row['kind'] == 'OPEN_POSITION':
            bars=bound['bars_by_symbol'][row['symbol']]
            events[bars[row['entry_index']]['timestamp_ms']] += 1
    days = (manifest['dev_end_ms']-manifest['dev_start_ms'])/86400000
    top2 = sorted((r['net2_bp'] for r in rows if r['net2_bp']>0),reverse=True)[:2]
    net2=sum(r['net2_bp'] for r in rows)
    endpoints=sorted([(a,1,s) for a,b,s in intervals]+[(b,-1,s) for a,b,s in intervals],key=lambda x:(x[0],x[1]))
    overlap=peak=0
    for _,delta,_ in endpoints:
        overlap+=delta
        peak=max(peak,overlap)
    disposition='REVIEW_REQUIRED_MODEL_ONLY' if rows and net2>0 else 'CLOSE_NO_POSITIVE_COST2_EVIDENCE'
    if all_censored:
        disposition='INCOMPLETE_CENSORED_NO_PROMOTION'
    return {'classification':'MODELLED_DEV_ONLY_NO_G5_NO_NAV',
            'candidate_id':CANDIDATE,'disposition':disposition,
            'gross':metrics(rows,'gross_bp'),'cost1':metrics(rows,'net1_bp'),'cost2':metrics(rows,'net2_bp'),
            'frequency':{'entry_count_including_censored':sum(events.values()),'distinct_entry_hour_epochs':len(events),
                         'distinct_entry_epochs_per_day':len(events)/days,'multi_symbol_entry_hours':sum(v>1 for v in events.values())},
            'max_bar_overlap_positions_upper_bound':peak,
            'largest_cost2_wins_bps':top2,'top2_sum_div_net2':sum(top2)/net2 if net2>0 else None,
            'censored':all_censored,'per_symbol':per_symbol,
            'completed_ledger':rows,'account_NAV':None,'actual_funding':None,
            'limitations':bound.get('limitations',[])+[
                'Fixed20/40bp scenarios are not observed complete funding/fees/fills.',
                'Same-bar chronology is conservative model; DD/streak symbol tie order is not actual execution ordering.',
                'No counterfactual winner-preservation result exists for this independent single candidate.']}


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=['preflight','dev'])
    p.add_argument('--manifest',required=True,type=Path)
    p.add_argument('--input-sha256',required=True)
    p.add_argument('--repo-root',type=Path,default=HERE.parents[3])
    p.add_argument('--out',type=Path)
    p.add_argument('--claim-dir',type=Path)
    a=p.parse_args(argv)
    try:
        bound=preflight(a.manifest,a.repo_root,expected_manifest_sha256=a.input_sha256)
        if a.mode=='preflight':
            print(json.dumps({k:v for k,v in bound.items() if k!='bars_by_symbol'},indent=2))
            return 0
        if a.out is None or a.claim_dir is None:
            raise GateError('HOLD_REQUIRE_EXISTING_D_CLAIM_DIR_AND_NEW_OUTPUT')
        manifest_raw=a.manifest.read_bytes()
        if hashlib.sha256(manifest_raw).hexdigest()!=a.input_sha256:
            raise GateError('HOLD_MANIFEST_CHANGED_AFTER_PREFLIGHT')
        manifest=json.loads(manifest_raw)
        if not a.claim_dir.is_dir() or a.out.exists() or not a.out.parent.is_dir():
            raise GateError('HOLD_INVALID_OUTPUT_OR_EXISTING_CLAIM_DIRECTORY')
        snapshot=Path(manifest['snapshot_root']).resolve()
        if a.out.resolve().is_relative_to(snapshot) or a.claim_dir.resolve().is_relative_to(snapshot):
            raise GateError('HOLD_OUTPUT_MUST_NOT_TOUCH_SOURCE_SNAPSHOT')
        claim=a.claim_dir/(CANDIDATE+'.claim.json')
        # Existing D owns the supplied directory. Permanent candidate-level exclusion;
        # failure never deletes it or silently grants another evaluation.
        fd=os.open(claim,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        receipt={'candidate_id':CANDIDATE,'manifest_sha256':a.input_sha256,
                 'bound_input_sha256':bound['input_sha256'],
                 'code_sha256':{name:sha(HERE/name) for name in ('reference.py','input_gate.py','dev_runner.py')},
                 'rule_sha256':sha(HERE/'FROZEN_SPEC.json'),'runner_sha256':sha(__file__),
                 'out':str(a.out.resolve()),'started_at':datetime.now(timezone.utc).isoformat(),
                 'no_owner_change':True,'recovery':'read saved output; do not delete claim/retry'}
        with os.fdopen(fd,'w') as handle:
            json.dump(receipt,handle,indent=2)
        result=evaluate(bound,manifest)
        result['binding']={k:v for k,v in bound.items() if k!='bars_by_symbol'}
        result['execution_receipt']=receipt
        with a.out.open('x') as handle:
            json.dump(result,handle,indent=2,allow_nan=False)
            handle.write('\n')
        print(json.dumps({'state':result['disposition'],'output_sha256':sha(a.out),'output':str(a.out)}))
        return 0
    except (GateError,ValueError,KeyError,FileNotFoundError,FileExistsError) as exc:
        print(json.dumps({'state':'HOLD','reason':str(exc)}))
        return 2


if __name__=='__main__':
    sys.exit(main())
