import unittest
from backend.research.prep.a3_regime_labeler_v1 import label_regime, coverage_manifest, RegimeInputError

BASE = {
    "ts_utc":"2026-08-17T00:00:00Z", "closed_bar_ts_utc":"2026-08-16T23:55:00Z", "symbol":"BTCUSDT",
    "trend_strength":0.5, "realized_vol_pct":1.2, "spread_bps":4, "depth_usdt":250000,
    "funding_8h_pct":0.01, "oi_change_pct":1.0
}
NOW="2026-08-17T00:05:00Z"

class TestA3Regime(unittest.TestCase):
    def test_labels_and_coverage(self):
        x=label_regime(dict(BASE), now_utc=NOW)
        self.assertEqual((x["trend_state"],x["vol_state"],x["liquidity_state"]),("TREND","HIGH_VOL","NORMAL"))
        self.assertEqual(x["outcome_fields_used"], [])
        m=coverage_manifest([dict(BASE)], now_utc=NOW)
        self.assertFalse(m["outcome_metrics_inspected"])
    def test_future_outcome_cannot_change_label(self):
        a=dict(BASE); b=dict(BASE)
        a["future_pnl_r"]=-99; b["future_pnl_r"]=99
        self.assertEqual(label_regime(a,now_utc=NOW), label_regime(b,now_utc=NOW))
    def test_fail_closed_missing(self):
        x=dict(BASE); x.pop("depth_usdt")
        with self.assertRaises(RegimeInputError): label_regime(x,now_utc=NOW)
    def test_fail_closed_future_bar(self):
        x=dict(BASE); x["closed_bar_ts_utc"]="2026-08-17T00:01:00Z"
        with self.assertRaises(RegimeInputError): label_regime(x,now_utc=NOW)
    def test_stale_rejected(self):
        with self.assertRaises(RegimeInputError): label_regime(dict(BASE),now_utc="2026-08-17T03:00:01Z")

if __name__ == "__main__": unittest.main()
