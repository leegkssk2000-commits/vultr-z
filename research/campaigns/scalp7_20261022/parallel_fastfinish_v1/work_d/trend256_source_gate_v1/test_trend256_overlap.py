"""Saved-row tests only. No native evaluator, strategy replay or market access."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
CONTRIBUTION=HERE.parents[3]/"scalp7_20261021"/"portfolio_coverage_v1"/"work_d"/"contribution_report.py"
# HERE is campaigns/scalp7_20261022/parallel_fastfinish_v1/work_d/gate;
# campaigns is parents[3]. The exact library is required, not a substituted copy.


def load_module():
    spec=importlib.util.spec_from_file_location("trend256_overlap_test_module",HERE/"trend256_overlap.py")
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Trend256OverlapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m=load_module()
        cls.long=HERE/"inputs"/"long_only_prospective.json"
        cls.liquid=HERE/"inputs"/"liquid6_child.json"
        cls.contribution=cls.m.load_contribution(CONTRIBUTION)
        cls.report=cls.m.run(cls.long,cls.liquid,CONTRIBUTION)

    def test_exact_receipts_and_parent_scope_stay_separate(self):
        self.assertEqual(self.report["input_bindings"]["long256"]["completed_trades"],256)
        self.assertEqual(self.report["input_bindings"]["liquid123"]["completed_trades"],123)
        parent=self.report["inherited_parent_scope_excluded_from_closed_comparison"]
        self.assertEqual((parent["long256_parent_admitted_completed"],parent["long256_parent_open"],parent["long256_parent_rejected"]),(301,1,1889))
        self.assertTrue(parent["not_child_admission_or_occupancy_counts"])
        for lane,n in (("long256",256),("liquid123",123)):
            self.assertEqual(self.report["coverage"][lane]["UTC"]["entries"],n)

    def test_legacy_106_is_reproduced_with_two_zero_span_caveats(self):
        legacy=self.report["legacy_stamp_predicate_reproduction"]
        self.assertEqual(legacy["pairs"],107)
        self.assertEqual(legacy["liquid123_rows_with_overlap"],106)
        self.assertEqual(legacy["liquid123_closed_row_denominator"],123)
        points=legacy["zero_span_pairs_not_strict_positive_intersections"]
        self.assertEqual(len(points),2)
        self.assertEqual({p["symbol"] for p in points},{"XRP-USDT","DOGE-USDT"})

    def test_physical_exit_ambiguity_produces_two_diagnostic_models(self):
        models=self.report["holding_models"]
        strict=models["stored_exit_stamp_half_open"]
        upper=models["exit_bar_end_upper_model"]
        self.assertEqual((strict["same_symbol_same_side_pairs"],strict["liquid123_rows_with_overlap"]),(105,104))
        self.assertEqual((upper["same_symbol_same_side_pairs"],upper["liquid123_rows_with_overlap"]),(115,113))
        self.assertIsNone(strict["measured_physical_overlap"])
        self.assertIsNone(upper["measured_physical_overlap"])
        self.assertEqual(self.report["exit_stamp_ambiguity"]["zero_span_closed_rows"],{"long256":29,"liquid123":5})
        self.assertEqual(self.report["exact_same_symbol_side_entry_timestamp_pairs"],[])

    def test_37_dates_are_exit_date_union_not_intersection(self):
        daily=self.report["exit_bar_daily_diagnostic"]
        union=daily["comparisons"]["exit_date_union_zero_filled"]
        both=daily["comparisons"]["both_have_exit_rows_intersection"]
        self.assertEqual(union["days"],37)
        self.assertAlmostEqual(union["pearson"],0.9237247419824631,places=13)
        self.assertEqual(both["days"],28)
        self.assertAlmostEqual(both["pearson"],0.9436779569987106,places=13)
        self.assertEqual(union["both_saved_daily_net_negative_days"],19)
        self.assertIsNone(daily["measured_simultaneous_losses"])
        self.assertEqual(len(daily["daily_rows"]),42)

    def test_actual_outcome_availability_and_independence_are_unknown(self):
        self.assertIsNone(self.report["exit_stamp_ambiguity"]["outcome_available_ts"])
        self.assertIsNone(self.report["opportunities"]["independent_count"])
        self.assertIn("UNKNOWN",self.report["opportunities"]["status"])
        for model in self.report["holding_models"].values():
            self.assertIsNone(model["measured_simultaneous_outcomes"])
            for pair in model["pairs"]:
                self.assertIsNone(pair["long256_row"]["outcome_available_ts_ms"])
                self.assertIsNone(pair["liquid123_row"]["outcome_available_ts_ms"])
        shared=self.report["shared_account"]
        self.assertEqual(shared["status"],"UNKNOWN")
        for key in ("NAV","MTM_DD","incremental_net","independent_eligible_entries","combined_net"):
            self.assertIsNone(shared[key])
        self.assertFalse(shared["allocation_run"])
        self.assertTrue(all(v==0 for v in self.report["activity"].values()))

    def test_metadata_window_difference_is_preserved_in_common_denominator(self):
        windows=self.report["source_windows"]
        self.assertEqual(windows["comparison_window_utc"],["2026-08-29T07:00:00+00:00","2026-10-09T22:00:00+00:00"])
        starts={v["first_bar_open_ms"] for v in windows["lanes"]["liquid123"]["symbols"]}
        self.assertEqual(len(starts),2)
        for lane in ("long256","liquid123"):
            utc=self.report["coverage"][lane]["UTC"]
            self.assertEqual(utc["calendar_days"],42)
            self.assertEqual([r["covered_hours"] for r in utc["partial_dates"]],[17,22])

    def test_library_source_tamper_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"source.py"
            path.write_bytes(CONTRIBUTION.read_bytes()+b'\nraise AssertionError("must not execute")\n')
            with self.assertRaisesRegex(ValueError,"CONTRIBUTION_SOURCE_SHA256_MISMATCH"):
                self.m.load_contribution(path)

    def test_trade_or_source_metadata_tamper_is_rejected(self):
        original=json.loads(self.long.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            for field in ("trade","source"):
                value=copy.deepcopy(original)
                if field=="trade":value["trades"][0]["net_bps"]+=1
                else:value["source"]["symbols"][0]["first_post_boundary_ts"]+=3600000
                path=Path(tmp)/(field+".json");path.write_text(json.dumps(value))
                with self.subTest(field=field),self.assertRaisesRegex(ValueError,"RAW_FILE_IDENTITY_MISMATCH"):
                    self.m.run(path,self.liquid,CONTRIBUTION)

    def test_exclusive_output_cannot_overwrite_existing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"report.json";path.write_text("preserve")
            with self.assertRaises(FileExistsError):
                self.m.run(self.long,self.liquid,CONTRIBUTION,path)
            self.assertEqual(path.read_text(),"preserve")

    def test_zero_span_synthetic_labels_are_not_real_zero_holding(self):
        # A point label strictly inside B passes legacy inequalities but is an
        # empty half-open interval; only the +one-bar model gives positive hold.
        def receipt(identity,entry,exit):
            return {"challenger_id":identity,"trades":[{"symbol":"BTC-USDT","side":"long",
                "signal_ts":entry-3600000,"entry_ts":entry,"exit_ts":exit,"intent_sha":identity}]}
        a=receipt("A",7200000,7200000);b=receipt("B",3600000,10800000)
        stored={lane:self.m.adapt_rows(r,lane,self.contribution,lambda x:x["intent_sha"])[0]
                for lane,r in (("long256",a),("liquid123",b))}
        upper={lane:self.m.adapt_rows(r,lane,self.contribution,lambda x:x["intent_sha"],3600000)[0]
               for lane,r in (("long256",a),("liquid123",b))}
        self.assertEqual(self.m.legacy_overlap(stored)["pairs"],1)
        self.assertEqual(self.m.interval_report(stored,0,18000000,self.contribution)["same_symbol_same_side_pairs"],0)
        self.assertEqual(self.m.interval_report(upper,0,18000000,self.contribution)["same_symbol_same_side_pairs"],1)
        self.assertTrue(all(r["net1x"] is None and r["opportunity_id"] is None and r["outcome_available_ts_ms"] is None for rows in upper.values() for r in rows))


if __name__=="__main__":unittest.main()
