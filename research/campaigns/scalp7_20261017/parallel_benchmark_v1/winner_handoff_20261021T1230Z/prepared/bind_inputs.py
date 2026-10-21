"""Read-only source/feature binding while the shared economic slot is occupied.
No candidate replay, no changed-rule PnL, no order/network/secret access.
"""
from pathlib import Path
import gzip,hashlib,json,sys
import handoff_comparison as h
import run_chronological as old
S=Path(__file__).resolve().parent

def sha(b):return hashlib.sha256(b).hexdigest()
def write(name,obj):
 raw=(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
 with (S/name).open('xb') as f:f.write(raw)
 return sha(raw)
old.save=lambda n,v:write('PREP_'+n,v)
frames=old.full_frames()
previous_binding=json.loads((h.BASE/'CHRONO_SOURCE_BINDING.json').read_text())
index={};enriched={}
for symbol,frame in frames.items():
 raw=frame.to_csv(index=False).encode()
 if sha(raw)!=previous_binding[symbol]['full_csv_sha256']:raise ValueError('FULL_YEAR_CACHE_MISMATCH')
 filename='INPUT_'+symbol+'_30m.csv.gz';packed=gzip.compress(raw,mtime=0)
 with (S/filename).open('xb') as f:f.write(packed)
 index[symbol]={'path':filename,'sha256':sha(packed),'csv_sha256':sha(raw),'rows':len(frame)}
 enriched[symbol]={int(row['open_ts_ms']):row for seg in h.positive.enriched_segments(frame) for row in seg.to_dict('records')}
trades=json.loads((h.BASE/'CONTROL_RESULT.json').read_text())['result']['trade_rows']
joined=[]
for t in trades:
 symbol=t['symbol'];signal=t['signal'];stamp=int(signal['signal_open_ts_ms']);row=enriched[symbol][stamp];prev=enriched[symbol].get(stamp-h.TF)
 if prev is None:raise ValueError('ENTRY_PREFIX_MISSING')
 side=int(t['side']);entry=float(t['entry_prices'][symbol]);range_=float(row['high']-row['low'])
 features={'adx14':float(row['adx14']),'previous_adx14':float(prev['adx14']),'ema20':float(row['g20']),
  'ema20_delta':float(row['g20']-prev['g20']),'signal_open':float(row['open']),'signal_high':float(row['high']),
  'signal_low':float(row['low']),'signal_close':float(row['close']),'previous_high':float(prev['high']),
  'previous_low':float(prev['low']),'entry_open':entry,'side':side,
  'directional_body':side*float(row['close']-row['open']),
  'directional_fill_gap':side*(entry-float(row['close'])),
  'directional_fill_distance_ema20':side*(entry-float(row['g20'])),
  'close_location_in_direction':(float(row['close']-row['low'])/range_ if side==1 else float(row['high']-row['close'])/range_) if range_ else None}
 if int(row['feature_available_ts_ms'])>int(t['entry_ts_ms']):raise ValueError('FUTURE_FEATURE_AT_ENTRY')
 joined.append({'key':list(h.key(t)),'feature_available_ts_ms':int(row['feature_available_ts_ms']),
   'entry_ts_ms':int(t['entry_ts_ms']),'available_at_entry':features,
   'analysis_only_labels_not_features':{'net1x':t['net_bps'],'net2x':t['gross_bps']-2*t['cost_bps'],'mfe_R':t['mfe_R'],
    'cohort':'large35' if t['mfe_R']>=2 else 'remainder93','reason':t['reason']}})
write('ENTRY_FIELDS128.json',{'classification':'OBSERVED_PREFIX_JOIN_NOT_NEW_FILTER_OR_ECONOMICS','rows':joined,
 'lookahead_features':False,'rule_selected':False,'trade_removal':False,'new_economic_comparisons':0})
write('INPUT_CACHE.json',{'symbols':index,'exact_original365day_context':True,'existing_control_entries_joined':len(joined),
 'new_candidate_replays':0,'current_shadow_changed':False})
print('PREP_COMPLETE_EXACT_SOURCE_AND128_ENTRY_FIELDS_NO_NEW_ECONOMIC_RESULT',flush=True)
