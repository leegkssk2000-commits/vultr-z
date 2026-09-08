"""Actual FT on artificial data only; no market replay is a unit test."""
import json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import boundary as b
RECEIPTS=[]
def artificial(kind,length):
    dates=pd.date_range('2003-01-01',periods=length,freq='4h',tz='UTC')
    close=([100+j*.08+(2 if j%9==0 else -2 if j%9==1 else 0) for j in range(length)] if kind=='D2'
           else [100-.2*(j%60)+(20 if j%60>=30 else 0) for j in range(length)])
    return pd.DataFrame({'date':dates,'open':close,'close':close,'high':[x+.1 for x in close],
                         'low':[x-.1 for x in close],'volume':100.})
class BoundaryTests(unittest.TestCase):
    def smoke(self,kind,offset):
        data=artificial(kind,offset+720)
        start=int(data.date.iloc[offset].timestamp()*1000);end=int(data.date.iloc[-1].timestamp()*1000)+b.BAR
        with tempfile.TemporaryDirectory() as out:
            result,views=b.run_frame(kind,{'SYNTH/USDT':data},start,end,out)
        trades,audit=result[0]['results'],result[2]
        self.assertGreater(len(trades),0)
        self.assertTrue(all(start<=int(x.timestamp()*1000)<end for x in trades.open_date))
        if audit:
            self.assertEqual(audit['callback_errors'],[])
            self.assertEqual(len(audit['entries']),len(trades))
            self.assertTrue(all(t['decision_index']>=239 for t in audit['entries']))
        RECEIPTS.append({'kind':kind,'offset':offset,'length':len(data),'trades':len(trades),
                         'callback_errors':[] if audit is None else audit['callback_errors'],
                         'views':views,'synthetic_only':True,'market_reads':0,'economic_runs':0})
    def test_d2_start0(self):self.smoke('D2',0)
    def test_d2_middle120(self):self.smoke('D2',120)
    def test_d2_full_geometry3028(self):self.smoke('D2',3028)
    def test_hlhb_start0(self):self.smoke('HLHB',0)
    def test_hlhb_middle120(self):self.smoke('HLHB',120)
    def test_hlhb_full_geometry3028(self):self.smoke('HLHB',3028)
    def test_preserve_indicators_and_original_coordinates(self):
        data=artificial('D2',3748);data['zel_index']=range(len(data));data['feature']=data['close']*1.234
        start=int(data.date.iloc[3028].timestamp()*1000);end=int(data.date.iloc[-1].timestamp()*1000)+b.BAR
        for startup,first in [(0,3027),(30,2997)]:
            pd.testing.assert_frame_equal(b.aligned_view({'X':data},start,end,startup)['X'],data.iloc[first:])
    def test_duplicate_timestamp_rejected(self):
        data=artificial('D2',360);data.loc[10,'date']=data.loc[9,'date']
        with self.assertRaisesRegex(ValueError,'NONCONTIGUOUS'):
            b.aligned_view({'X':data},int(data.date.iloc[120].timestamp()*1000),int(data.date.iloc[-1].timestamp()*1000)+b.BAR,0)
    def test_exact_start_allowed_end_forbidden(self):
        start=pd.Timestamp('2003-01-01',tz='UTC');ms=int(start.timestamp()*1000)
        b.ensure_entry_calendar(start,ms,ms+b.BAR)
        for t in [start-pd.Timedelta(milliseconds=1),start+pd.Timedelta(hours=4)]:
            with self.assertRaises(b.FatalBenchmarkBoundary):b.ensure_entry_calendar(t,ms,ms+b.BAR)
    def test_keyword_and_positional_callback_clock(self):
        t=pd.Timestamp('2003-01-01',tz='UTC')
        self.assertEqual(b.entry_time(('pair','market',1,100,'GTC',t,'tag','long'),{}),t)
        self.assertEqual(b.entry_time((),{'current_time':t}),t)
    def test_callback_failure_cannot_be_swallowed(self):
        obj=object.__new__(b.GuardedD2)
        with patch.object(b.D2Independent,'order_filled',side_effect=ValueError('injected')):
            with self.assertRaisesRegex(b.FatalBenchmarkBoundary,'injected'):obj.order_filled()
        self.assertFalse(issubclass(b.FatalBenchmarkBoundary,Exception))
    def test_exit_failure_stops_first_bad_callback(self):
        obj=object.__new__(b.GuardedD2)
        with patch.object(b.D2Independent,'custom_exit',side_effect=ValueError('missing-state')) as fn:
            with self.assertRaisesRegex(b.FatalBenchmarkBoundary,'missing-state'):obj.custom_exit()
            self.assertEqual(fn.call_count,1)
    def test_fresh_location_no_original_scratch_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'different-checkout'/'research'/'benchmarks';root.mkdir(parents=True)
            shutil.copytree(b.FROZEN,root/b.FROZEN.name)
            new=root/b.HERE.name;new.mkdir();shutil.copy(b.HERE/'boundary.py',new/'boundary.py')
            env=dict(os.environ,PYTHONPATH=str(new),PYTHONDONTWRITEBYTECODE='1')
            proc=subprocess.run([sys.executable,'-c','import boundary; boundary.strategy("HLHB"); boundary.installed_core_identity(); print("FRESH_LOCATION_OK")'],
                                cwd=tmp,env=env,text=True,capture_output=True,timeout=30)
            self.assertEqual(proc.returncode,0,proc.stderr)
            self.assertIn('FRESH_LOCATION_OK',proc.stdout)
    def test_hlhb_economic_parameters_unchanged(self):
        old=b.ft.external_class(b.FROZEN/'hlhb.py');new=b.strategy('HLHB')
        for field in ['timeframe','minimal_roi','stoploss','startup_candle_count','trailing_stop',
                      'trailing_stop_positive','trailing_stop_positive_offset','order_types','ignore_roi_if_entry_signal']:
            self.assertEqual(getattr(old,field),getattr(new,field),field)
if __name__=='__main__':
    suite=unittest.main(exit=False)
    target=Path(os.environ.get('QA_RECEIPT','SYNTHETIC_QA.json'));target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps({'success':suite.result.wasSuccessful(),'tests':suite.result.testsRun,
                                 'cases':RECEIPTS,'source':'ARTIFICIAL_PRICES_ONLY'},indent=2)+'\n')
    sys.exit(not suite.result.wasSuccessful())
