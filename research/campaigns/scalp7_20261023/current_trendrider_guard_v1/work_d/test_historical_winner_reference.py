"""Synthetic saved-row comparison tests; no strategy/native economic execution."""
import copy
import unittest

from historical_winner_reference import compare_reference, seal_reference


def fixture():
    old = {"symbol": "SYNTHETIC-USDT", "side": "long", "signal_ts": 1000, "entry_ts": 2000,
           "gross_bps": 20, "net_bps": 15, "realized_cost_bps": 5, "feature_sha": "synthetic-old"}
    ref = seal_reference({
        "schema_version": "work_d.historical_published_top10_reference.v1",
        "fixture_only": True, "historical_completion_commit": "SYNTHETIC_NOT_SSOT",
        "historical_source_file_pins": {"SYNTHETIC": "fixture"},
        "expected_challenger_id": "synthetic", "old_input_binding": {"schema_version": "synthetic.v1"},
        "published_topk_1x": [{"top_k": 1, "row_identity_sha256s": ["published-id"], "positive_contribution_trade_bps": "15"}],
        "rows": [{"published_rank": 1, "row_identity_sha256": "published-id", "saved_row": old,
                  "retrospective_outcomes_not_execution_features": {"net_1x_recomputed_trade_bps": "15"}}],
    })
    receipt = {"challenger_id": "synthetic", "schema_version": "synthetic.v1", "trades": [copy.deepcopy(old)],
               "source": {"symbols": [{"symbol": "SYNTHETIC-USDT", "first_post_boundary_ts": 500, "last_post_boundary_ts": 5000}]}}
    return ref, receipt


class PublishedReferenceTests(unittest.TestCase):
    def test_proxy_matches_despite_changed_hash_and_outcome(self):
        ref, current = fixture()
        current["trades"][0].update(feature_sha="synthetic-new", net_bps=14, realized_cost_bps=6)
        row = compare_reference(ref, current)["rows"][0]
        self.assertEqual(row["status"], "PRESENT_EVENT_PROXY")
        self.assertEqual(row["changed_hash_fields"]["feature_sha"]["current"], "synthetic-new")
        self.assertEqual(row["outcomes"]["net_bps"]["current_minus_historical_saved_value"], "-1")
        self.assertTrue(row["same_proxy_does_not_establish_same_feature_body"])

    def test_outside_window_absence_qualified(self):
        ref, current = fixture()
        current["trades"] = []
        current["source"]["symbols"][0]["first_post_boundary_ts"] = 3000
        result = compare_reference(ref, current)
        self.assertEqual(result["rows"][0]["status"], "ABSENT_BEFORE_CURRENT_VISIBLE_SOURCE_WINDOW")
        self.assertTrue(result["rows"][0]["absence_does_not_establish_strategy_filter_effect"])
        self.assertFalse(result["limitations"]["strategy_filter_effect_established"])

    def test_inside_window_absence_still_not_causal(self):
        ref, current = fixture()
        current["trades"] = []
        result = compare_reference(ref, current)
        self.assertEqual(result["rows"][0]["status"], "ABSENT_WITHIN_CURRENT_VISIBLE_SOURCE_WINDOW")
        self.assertEqual(result["limitations"]["causal_absence_explanation"], "NOT_ESTABLISHED")

    def test_straddling_signal_not_mislabeled_within(self):
        ref, current = fixture()
        current["trades"] = []
        current["source"]["symbols"][0]["first_post_boundary_ts"] = 1500
        self.assertEqual(compare_reference(ref, current)["rows"][0]["status"], "ABSENT_STRADDLES_CURRENT_VISIBLE_SOURCE_WINDOW")

    def test_entry_timestamp_is_part_of_proxy(self):
        ref, current = fixture()
        current["trades"][0]["entry_ts"] += 1
        self.assertFalse(compare_reference(ref, current)["rows"][0]["event_proxy_match"])

    def test_duplicate_proxy_rejected(self):
        ref, current = fixture()
        current["trades"].append(copy.deepcopy(current["trades"][0]))
        with self.assertRaisesRegex(ValueError, "DUPLICATE_CURRENT_EVENT_PROXY"):
            compare_reference(ref, current)

    def test_reference_tampering_rejected(self):
        ref, current = fixture()
        ref["rows"][0]["saved_row"]["net_bps"] = 99
        with self.assertRaisesRegex(ValueError, "REFERENCE_CONTENT_DIGEST_MISMATCH"):
            compare_reference(ref, current)

    def test_purity_and_published_groups_preserved(self):
        ref, current = fixture()
        original = copy.deepcopy((ref, current))
        result = compare_reference(ref, current)
        self.assertEqual((ref, current), original)
        self.assertEqual(result["historical_topk_correspondence"][0]["historical_published_group_verbatim"], ref["published_topk_1x"][0])
        result["rows"][0]["historical_saved_row"]["net_bps"] = -1
        self.assertEqual((ref, current), original)

    def test_unknown_window_and_wrong_lane(self):
        ref, current = fixture()
        current["trades"] = []
        current["source"]["symbols"] = []
        self.assertEqual(compare_reference(ref, current)["rows"][0]["status"], "ABSENT_SOURCE_WINDOW_UNBOUND")
        current["challenger_id"] = "WR80_OTHER_LANE"
        with self.assertRaisesRegex(ValueError, "CURRENT_LANE_MISMATCH"):
            compare_reference(ref, current)

    def test_invalid_numeric_inputs_rejected(self):
        for field, value in (("net_bps", float("nan")), ("net_bps", True), ("entry_ts", True)):
            with self.subTest(field=field, value=value):
                ref, current = fixture()
                current["trades"][0][field] = value
                with self.assertRaises(ValueError):
                    compare_reference(ref, current)


if __name__ == "__main__":
    unittest.main()
