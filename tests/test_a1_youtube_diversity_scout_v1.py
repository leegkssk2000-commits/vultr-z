"""Scoped scout regressions, separate from legacy market-replay trigger paths."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.research.architecture_factory import a1_youtube_diversity_scout_v1 as s

CONTEXT = dict(
    blocker="FADING_REENTRY",
    lane=["primary"],
    candidate="frozen_parent",
    failure_signature="loss_cluster_and_dropped_winners",
    required_sources=["DMI"],
    development_evidence_ref="dev/receipt.json",
    implementation_sha256="a" * 64,
    buckets=["trend"],
)


class ScopedScout(unittest.TestCase):
    def test_all_existing_buckets_accept_structured_manual_context(self):
        existing_buckets = {
            "trend",
            "breakout",
            "mean_reversion",
            "volatility",
            "funding_oi_basis",
            "order_flow",
            "liquidity",
            "session_intraday",
            "exit_management",
            "trailing_stop",
            "risk_management",
            "portfolio_risk",
            "short_selling",
            "regime_detection",
            "validation_oos",
        }
        for bucket in existing_buckets:
            with self.subTest(bucket=bucket):
                ctx = {**CONTEXT, "buckets": [bucket]}
                self.assertEqual(s.validate_context(ctx), ctx)
                self.assertIn(bucket, s.BUCKETS)

    def test_chart_buckets_normalize_context_and_search_rows_together(self):
        aliases = {
            "PRICE_ACTION/CHART_STRUCTURE": "price_action",
            "chart structure": "price_action",
            " Fibonacci ": "fibonacci",
            "Candlestick": "candlestick",
            "classic-chart-patterns": "classic_chart_patterns",
            "MULTI_TIMEFRAME": "multi_timeframe",
            "Oscillator Context": "oscillator_context",
            "RISK/MANAGEMENT": "risk_management",
        }
        for raw, canonical in aliases.items():
            with self.subTest(bucket=raw):
                ctx = {**CONTEXT, "buckets": [raw]}
                normalized = s.validate_context(ctx)
                self.assertEqual(normalized["buckets"], [canonical])
                self.assertEqual(ctx["buckets"], [raw])
                rows = s._normalize_search_rows(
                    {
                        "videos": [
                            {
                                "bucket": raw,
                                "url": "https://youtu.be/exact",
                                "claimed_view_count": 999999,
                            },
                        ]
                    },
                    {},
                )
                self.assertEqual(rows[0]["bucket"], canonical)
                self.assertFalse(rows[0]["view_count_verified"])
                self.assertIsNone(rows[0]["observed_views"])
                prompt = s._search_prompt(
                    [(canonical, s.BUCKETS[canonical])], normalized
                )
                self.assertIn("FADING_REENTRY", prompt)
                self.assertIn(canonical, prompt)
        self.assertEqual(
            s.validate_context(
                {**CONTEXT, "buckets": ["chart_structure", "price_action"]}
            )["buckets"],
            ["price_action"],
        )

    def test_unknown_or_malformed_buckets_fail_before_transport(self):
        invalid = [
            None,
            [],
            "fibonacci",
            {"fibonacci": True},
            [["fibonacci"]],
            [1],
            ["future_bucket"],
            ["fibonacci", "candlestick", "price_action", "trend"],
        ]
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            s, "call_gemini_search"
        ) as search, patch.object(s, "call_gemini_video") as video:
            out = Path(tmp) / "receipt.json"
            for buckets in invalid:
                with self.subTest(buckets=buckets), self.assertRaises(ValueError):
                    s.run(out, context={**CONTEXT, "buckets": buckets})
            search.assert_not_called()
            video.assert_not_called()
            self.assertFalse(out.exists())
        self.assertEqual(
            s._normalize_search_rows(
                {
                    "videos": [
                        {"bucket": "unknown", "url": "https://youtu.be/a"},
                        {"bucket": ["fibonacci"], "url": "https://youtu.be/b"},
                    ]
                },
                {},
            ),
            [],
        )

    def test_new_topics_retain_manual_pool_and_review_ceiling(self):
        rows = {
            "videos": [
                {
                    "bucket": "Fibonacci",
                    "url": f"https://youtu.be/v{i}",
                    "claimed_view_count": i,
                }
                for i in range(40)
            ]
        }
        context = {
            **CONTEXT,
            "buckets": ["Fibonacci", "Candlestick", "chart_structure"],
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "test",
                "YOUTUBE_DIVERSITY_MAX_POOL": "999",
                "YOUTUBE_DIVERSITY_MAX_VIDEO_REVIEWS": "999",
            },
        ), patch.object(
            s, "call_gemini_search", return_value=("test", rows, [])
        ) as search, patch.object(
            s, "call_gemini_video", side_effect=RuntimeError("FIXTURE_ONLY")
        ) as video:
            result = s.run(
                Path(tmp) / "receipt.json",
                registry_path=Path(tmp) / "no_registry.json",
                context=context,
            )
        self.assertEqual(search.call_count, 1)
        self.assertEqual(video.call_count, 3)
        self.assertEqual(result["metrics"]["candidate_pool_count"], 30)
        self.assertEqual(result["metrics"]["reviewed_now"], 3)
        self.assertEqual(
            set(result["buckets"]), {"fibonacci", "candlestick", "price_action"}
        )
        self.assertTrue(result["research_only"])
        self.assertFalse(result["selection_authority"])
        self.assertFalse(result["promotion_authority"])
        self.assertEqual(result["execution_authority"], "NONE")
        self.assertEqual(result["order_authority"], "BLOCKED")

    def test_rule_declarations_are_untested_and_missing_rules_are_parked(self):
        rule = {
            "exact_formula": "close[t] > high[t-1]",
            "market": "crypto futures",
            "timeframe": "30m",
            "native_entry": "completed bar breakout",
            "native_exit": "close below prior low",
            "native_stop": "NONE",
            "native_target": "NONE",
            "native_holding": "until source exit",
            "signal_availability": "after bar close",
            "earliest_fill": "next bar open",
            "anchor_selection": "NOT_APPLICABLE",
        }
        review = {
            "source_rule": rule,
            "evidence_segments": [
                {"timestamp": "01:23", "rule": "close[t] > high[t-1]"},
            ],
            "creator_claims": ["I make a million dollars a year"],
        }
        complete = s._source_rule_readiness(review)
        self.assertEqual(
            complete["source_rule_readiness"], "SOURCE_RULE_DECLARED_UNTESTED"
        )
        self.assertFalse(complete["screening_eligible"])
        self.assertEqual(complete["economic_evidence"], "UNTESTED_HYPOTHESIS")
        for replacement in [
            {"source_rule": {**rule, "exact_formula": "UNSPECIFIED"}},
            {"source_rule": {**rule, "native_exit": "UNKNOWN"}},
            {"source_rule": {**rule, "signal_availability": "UNKNOWN"}},
            {"source_rule": {**rule, "native_stop": "UNKNOWN"}},
            {"evidence_segments": [{"timestamp": "UNKNOWN", "rule": "a chart line"}]},
            {
                "evidence_segments": [
                    {"timestamp": "10:01", "rule": "outside supplied clip"}
                ]
            },
        ]:
            with self.subTest(replacement=replacement):
                incomplete = s._source_rule_readiness({**review, **replacement})
                self.assertEqual(
                    incomplete["source_rule_readiness"], "SOURCE_RULE_INCOMPLETE"
                )
                self.assertFalse(incomplete["screening_eligible"])

    def test_discretionary_anchor_review_is_vetoed_without_economic_run(self):
        review = {
            "status": "USE",
            "analysis_mode": "DIRECT_VIDEO",
            "analyzed_video_id": "a",
            "source_rule": {"anchor_selection": "EX_POST"},
            "creator_claims": ["This Fibonacci chart proves large profits"],
            "reproducible_mechanisms": [
                {
                    "mechanism": "re-anchor after the winner",
                    "local_test_needed": "test a causal rule",
                }
            ],
        }
        for anchor in ["EX_POST", "DISCRETIONARY"]:
            classified = s._source_rule_readiness(
                {**review, "source_rule": {"anchor_selection": anchor}}
            )
            self.assertEqual(
                classified["source_rule_readiness"], "UNIMPLEMENTABLE_DISCRETIONARY"
            )
            self.assertFalse(classified["screening_eligible"])
        candidate = {
            "video_id": "a",
            "url": "https://youtu.be/a",
            "bucket": "fibonacci",
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"GEMINI_API_KEY": "test"}
        ), patch.object(
            s, "call_gemini_search", return_value=("test", {"videos": [candidate]}, [])
        ), patch.object(
            s, "call_gemini_video", return_value=("test", review)
        ):
            result = s.run(
                Path(tmp) / "receipt.json",
                registry_path=Path(tmp) / "no_registry.json",
                context={**CONTEXT, "buckets": ["fibonacci"]},
            )
        self.assertEqual(result["accepted_sources"], [])
        self.assertEqual(result["reviews"]["a"]["status"], "REJECT_SOURCE")
        self.assertEqual(result["execution_authority"], "NONE")

    def test_missing_views_and_profit_claim_cannot_acquire_authority(self):
        source = s._accepted_source(
            {
                "video_id": "a",
                "url": "https://youtu.be/a",
                "bucket": "candlestick",
                "view_count_verified": True,
                "observed_views": None,
                "claimed_view_count_unverified": 1000000,
            },
            {
                "analysis_mode": "DIRECT_VIDEO",
                "analyzed_video_id": "a",
                "creator_claims": ["Guaranteed profit"],
                "reported_pnl": 1000000,
            },
            "test",
        )
        self.assertFalse(source["view_count_verified"])
        self.assertIsNone(source["observed_views"])
        self.assertEqual(source["claimed_view_count_unverified"], 1000000)
        self.assertEqual(source["source_rule_readiness"], "SOURCE_RULE_INCOMPLETE")
        self.assertTrue(source["accepted_for_hypothesis_only"])
        self.assertEqual(source["economic_evidence"], "UNTESTED_HYPOTHESIS")
        self.assertFalse(source["screening_eligible"])
        self.assertFalse(source["selection_authority"])
        self.assertFalse(source["promotion_authority"])
