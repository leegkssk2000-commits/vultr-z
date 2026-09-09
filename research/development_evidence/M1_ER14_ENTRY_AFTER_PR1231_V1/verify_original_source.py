"""Optional original packet verification; no engine/alternative PnL/network.
Use the two exactly pinned USED_DEV packets delivered with the report.
"""
import argparse,hashlib
from pathlib import Path
import verify_saved as v

def verify(inputs,root=v.HERE):
    root=Path(root);repo=root.parents[2];spec=v.read(root/'SPEC.json');checker=v.checker(repo);answer={}
    for per in v.PERIODS:
        path=Path(inputs)/f'{per}.json.gz';v.need(v.sha(path)==spec['input_packet_sha256'][per],'SOURCE_PACKET_SHA')
        packet=v.gz(path);raw=v.gz(root/per/'RAW.json.gz');result=v.gz(root/per/'RESULT.json.gz')
        original=v.gz(repo/v.OLD/'M1'/per/'RAW.json.gz');witness={}
        for symbol,data in raw.items():
            rows=packet['rows_by'][symbol];keep=set()
            for e in data['events']:
                i=e['signal_index'];keep.update(range(max(0,i-15),min(len(rows),i+2)));keep.update(range(e['episode_start'],i+1))
            for t in data['trades']+data['open_positions']:
                last=t.get('exit_index',t.get('mark_index'));keep.update(range(max(0,t['entry_index']-14),last+1))
            witness[symbol]={str(i):{k:rows[i][k] for k in ('bar_open_ts','bar_close_ts','open','high','low','close')} for i in sorted(keep)}
        count,signals=v.check_raw(raw,result,original,packet['costs'],spec['periods'][per],witness,checker)
        projection=sorted([[e['symbol'],e['signal_index'],e['er_context']['source_closes']] for e in result['events']],key=lambda x:(x[0],x[1]))
        answer[per]=dict(original_input_sha256=v.sha(path),source_projection_sha256=hashlib.sha256(v.canon(projection)).hexdigest(),raw_sha256=v.sha(root/per/'RAW.json.gz'),result_sha256=v.sha(root/per/'RESULT.json.gz'),positions=count,signals=signals,source_rows=sum(len(x) for x in witness.values()),source_first_exit_check=True,economic_replays=0)
    v.need(answer==v.read(root/'SOURCE_PROOF.json'),'SOURCE_REPRODUCTION_MISMATCH')
    return answer
if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('--inputs',required=True);x=q.parse_args()
    print(v.json.dumps(verify(x.inputs),indent=2))
