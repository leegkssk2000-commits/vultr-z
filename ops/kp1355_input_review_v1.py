"""Review already consumed inputs, never generate a signal or replay a strategy."""
from __future__ import annotations
import argparse
import base64
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from ops import kp_connected_research_validation_v1 as fixed


def verify(input_path: Path, original_runner: Path, original_signals: Path):
    assert hashlib.sha256(original_runner.read_bytes()).hexdigest()=='232cff3478f70aa5b96272944abc0a037a1cbc1d726d35b7727f2bd94e197218'
    raw=fixed.bounded_gunzip(input_path.read_bytes(),64*1024*1024)
    assert hashlib.sha256(raw).hexdigest()==fixed.PRICE_SHA
    data=fixed.load(raw)
    differences={}
    for symbol,seed in data['context'].items():
        body=gzip.decompress(base64.b64decode(seed['gzip_base64'],validate=True))
        before=pd.read_csv(io.BytesIO(body));after=pd.read_csv(io.BytesIO(body),float_precision='round_trip')
        pd.testing.assert_frame_equal(before.drop(columns='volume'),after.drop(columns='volume'),check_exact=True)
        different=(before.volume!=after.volume)&~(before.volume.isna()&after.volume.isna())
        differences[symbol]={'changed_volume_cells':int(different.sum()),
                             'max_abs_volume_difference':float(abs(before.volume-after.volume).max()),
                             'all_nonvolume_columns_bit_equal':True}
    spec=importlib.util.spec_from_file_location('executed_runner_for_input_only',original_runner)
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    # Both calls only normalize and enrich already-consumed input. No generator,
    # economic execution, entry/exit callback or direct main is called.
    old_frames,old_clocks,_=old.build_frames(data)
    new_frames,clocks,_=fixed.build_frames(data)
    from backend.research.rebuild import scalp7_positive_lanes_v2 as parent
    enriched_checks={}
    for symbol in fixed.SYMBOLS:
        pd.testing.assert_frame_equal(old_frames[symbol].drop(columns='volume'),new_frames[symbol].drop(columns='volume'),check_exact=True)
        a=parent.enriched_segments(old_frames[symbol]);b=parent.enriched_segments(new_frames[symbol])
        assert len(a)==len(b)
        for x,y in zip(a,b):pd.testing.assert_frame_equal(x.drop(columns='volume'),y.drop(columns='volume'),check_exact=True)
        enriched_checks[symbol]={'segments':len(a),'rows':sum(len(x) for x in a),'all_causal_nonvolume_features_bit_equal':True}
    assert old_clocks==clocks
    signal_raw=original_signals.read_bytes();assert hashlib.sha256(signal_raw).hexdigest()=='f85d6ba97d729dcd9b475e5c3a1a24d49d655bdf1dafd7a836d58e7033d271e9'
    signals=json.loads(signal_raw)
    assert len(signals)==32
    witnesses=[fixed.causal_clock_witness(s,clocks) for s in signals]
    assert all(w['historical_next_open_available_in_realtime'] is False for w in witnesses)
    delays=sorted(w['recorded_causal_prefix_available_ms']-w['decision_close_ms'] for w in witnesses)
    return {'schema':'kp1355.consumed_input_review.v1','input_sha256':fixed.PRICE_SHA,
            'seed_parser_differences':differences,'enriched_frame_comparison':enriched_checks,
            'scope_of_equivalence':'This input and pinned Keltner/context/engine do not consume volume; not a general CSV parser equivalence.',
            'full_six_symbol_price_prefix_lateness_ms':{'min':min(delays),'median':(delays[15]+delays[16])/2,'max':max(delays)},
            'witnesses':witnesses,'timely_next_open_claims':0,'original_events_changed':0,
            'signals_generated':0,'economic_replays':0,'seed_config_live_availability_certified':False,
            'original_result_recomputed_by_replay':False,'new_execution_authorized':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('input','original-runner','original-signals','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();r=verify(a.input,a.original_runner,a.original_signals)
    with a.output.open('x') as f:json.dump(r,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
    print(json.dumps({k:v for k,v in r.items() if k!='witnesses'},indent=2))

if __name__=='__main__':main()
