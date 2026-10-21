"""Small invented candles only; PnL here tests arithmetic, never economics."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
import unittest

REPO = next(p for p in Path(__file__).resolve().parents if (p / "backend").is_dir())
sys.path.insert(0, str(REPO))
import pandas as pd
from backend.research.rebuild import scalp7_execution_v2 as engine
spec = importlib.util.spec_from_file_location("c1_box_adapter_tested", Path(__file__).with_name("adapter.py"))
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
TF = 1800000
SYMBOL = "BTC-USDT"


def frame(candles):
    return pd.DataFrame([{"open_ts_ms": i*TF, "close_ts_ms": (i+1)*TF,
       "available_ts_ms": (i+1)*TF, "segment_id": "synthetic", "open": o,
       "high": h, "low": low, "close": c} for i,(o,h,low,c) in enumerate(candles)])


def setup():
    return [
      (102,104,100,103),(104,107,103,106),(108,110,107,109),
      (107,109,104,105),(102,104,100.5,103),(104,107,103,106),
      (108,109.5,107,108),(105,108,104,106),(102,104,100.5,103),
      (104,107,103,106),(108,110,107,109),(104,106,101.5,102),
      (102,104,101,103)]


def result(tail, signals=None):
    x = frame(setup()+tail)
    sig = a.generate_signals({SYMBOL:x}) if signals is None else signals
    return engine.replay(sig,{SYMBOL:x},{SYMBOL:15.0},identity=a.IDENTITY,
                         exit_update=a.exit_update,entry_update=a.entry_update)


class BoxTests(unittest.TestCase):
    def test_first_signal_uses_previous_completed_box(self):
        x=frame(setup())
        s=a.generate_signals({SYMBOL:x})
        self.assertEqual(len(s),1)
        self.assertEqual(s[0]["signal_ts_ms"],13*TF)
        self.assertEqual(s[0]["meta"]["box_available_ts_ms"],12*TF)
        self.assertEqual(s[0]["stop_price"],100)
        self.assertEqual(s[0]["meta"]["target_price"],105)
        self.assertEqual(a.generate_signals({SYMBOL:x.iloc[:12]}),[])

    def test_center_close_exits_next_open_and_cost_debit(self):
        out=result([(103,105,102,104),(104,106,103,105.5),(106,107,105,106)])
        t=out["trades"][0]
        self.assertEqual(t["entry_ts_ms"],13*TF)
        self.assertEqual(t["exit_ts_ms"],15*TF)
        self.assertEqual(t["exit_prices"][SYMBOL],106)
        self.assertEqual(t["reason"],"BOX_CENTER_CLOSE_NEXT_OPEN")
        self.assertAlmostEqual(t["gross_bps"],(106/103-1)*10000)
        self.assertAlmostEqual(t["net_bps"],t["gross_bps"]-15)

    def test_intrabar_center_touch_does_not_exit(self):
        out=result([(103,106,102,104)])
        self.assertEqual(out["trades"],[])
        self.assertEqual(len(out["unresolved"]),1)

    def test_stop_loss(self):
        out=result([(103,104,99,101)])
        self.assertEqual(out["trades"][0]["reason"],"STOP_FIRST")
        self.assertEqual(out["trades"][0]["exit_prices"][SYMBOL],100)
        self.assertLess(out["trades"][0]["net_bps"],0)

    def test_same_bar_stop_wins_center_recovery(self):
        out=result([(103,107,99,106),(106,107,105,106)])
        self.assertEqual(out["trades"][0]["reason"],"STOP_FIRST")
        self.assertEqual(out["trades"][0]["exit_prices"][SYMBOL],100)

    def test_adverse_open_gap_stop(self):
        out=result([(103,104,102,103),(98,99,97,98)])
        self.assertEqual(out["trades"][0]["reason"],"OPEN_GAP_STOP")
        self.assertEqual(out["trades"][0]["exit_prices"][SYMBOL],98)

    def test_entry_beyond_floor_rejected(self):
        out=result([(99,104,98,103)])
        self.assertEqual(out["rejections"]["BOX_ENTRY_AT_OR_BELOW_FLOOR"],1)
        self.assertEqual(out["trades"],[])

    def test_entry_above_center_rejected(self):
        out=result([(106,108,105,107)])
        self.assertEqual(out["rejections"]["BOX_ENTRY_AT_OR_ABOVE_CENTER"],1)

    def test_duplicate_signal_is_not_second_entry(self):
        sig=a.generate_signals({SYMBOL:frame(setup())})
        out=result([(103,104,99,101)],signals=sig+sig)
        self.assertEqual(len(out["trades"]),1)
        self.assertEqual(out["rejections"]["DUPLICATE_SIGNAL"],1)

    def test_no_box_and_zero_trades(self):
        x=frame([(100,101,99,100)]*30)
        sig=a.generate_signals({SYMBOL:x})
        self.assertEqual(sig,[])
        out=engine.replay(sig,{SYMBOL:x},{SYMBOL:15})
        self.assertEqual(out["closed_trade_count"],0)

    def test_missing_bar_during_position_is_unresolved(self):
        x=frame(setup()+[(103,104,102,103),(103,104,102,103),(103,104,102,103)])
        x=x.drop(index=14)
        sig=a.generate_signals({SYMBOL:x})
        out=engine.replay(sig,{SYMBOL:x},{SYMBOL:15},exit_update=a.exit_update,entry_update=a.entry_update)
        self.assertEqual(out["trades"],[])
        self.assertEqual(len(out["unresolved"]),1)

    def test_missing_next_bar_rejects_entry(self):
        x=frame(setup()+[(103,104,102,103),(103,104,102,103)]).drop(index=13)
        sig=a.generate_signals({SYMBOL:x})
        out=engine.replay(sig,{SYMBOL:x},{SYMBOL:15},exit_update=a.exit_update,entry_update=a.entry_update)
        self.assertEqual(out["rejections"]["ENTRY_GAP"],1)

    def test_missing_bar_or_segment_during_formation_resets(self):
        x=frame(setup()).drop(index=5)
        self.assertEqual(a.generate_signals({SYMBOL:x}),[])
        x=frame(setup());x.loc[5:,"segment_id"]="new-segment"
        self.assertEqual(a.generate_signals({SYMBOL:x}),[])

    def test_late_signal_and_late_formation_data_suppress(self):
        for index in (5,12):
            x=frame(setup());x.loc[index,"available_ts_ms"]+=1
            self.assertEqual(a.generate_signals({SYMBOL:x}),[])

    def test_recovery_after_box_breach_is_not_new_range_entry(self):
        c=setup();c[-1]=(102,104,99,103)
        x=frame(c+[(102,104,101,103),(102,104,101,103)])
        self.assertEqual(a.generate_signals({SYMBOL:x}),[])

    def test_signal_not_repeated_from_same_box(self):
        x=frame(setup()+[(102,104,101,103)]*6)
        self.assertEqual(len(a.generate_signals({SYMBOL:x})),1)

    def test_full_later_prefix_preserves_first_signal(self):
        initial=a.generate_signals({SYMBOL:frame(setup())})
        future=a.generate_signals({SYMBOL:frame(setup()+[(200,220,180,210)]*20)})
        self.assertEqual(initial,future[:1])

    def test_time_exit_and_final_unresolved(self):
        out=result([(103,104.5,102,104)]*9)
        t=out["trades"][0]
        self.assertEqual(t["reason"],"MAX_HOLD_NEXT_OPEN")
        self.assertEqual(t["exit_ts_ms"],21*TF)
        final=result([(103,104.5,102,104)]*8)
        self.assertEqual(final["trades"],[])
        self.assertEqual(len(final["unresolved"]),1)

    def test_duplicate_candle_and_premature_availability_rejected(self):
        x=frame(setup())
        with self.assertRaisesRegex(ValueError,"CANDLE_DUPLICATE"):
            a.generate_signals({SYMBOL:pd.concat([x,x.iloc[-1:]],ignore_index=True)})
        x.loc[1,"available_ts_ms"]-=1
        with self.assertRaisesRegex(ValueError,"CANDLE_AVAILABLE_BEFORE_CLOSE"):
            a.generate_signals({SYMBOL:x})

    def test_missing_segment_identity_rejected(self):
        for missing in (None, "", "   ", float("nan")):
            x=frame(setup());x["segment_id"]=missing
            with self.assertRaisesRegex(ValueError,"BOX_SEGMENT_REQUIRED"):
                a.generate_signals({SYMBOL:x})

    def test_missing_column_and_nonfinite_price_rejected(self):
        x=frame(setup())
        with self.assertRaisesRegex(ValueError,"CANDLE_SCHEMA_INCOMPLETE"):
            a.generate_signals({SYMBOL:x.drop(columns="available_ts_ms")})
        x.loc[1,"close"]=float("nan")
        with self.assertRaisesRegex(ValueError,"NONFINITE"):
            a.generate_signals({SYMBOL:x})

if __name__=="__main__": unittest.main(verbosity=2)
