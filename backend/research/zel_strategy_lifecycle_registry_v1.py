from __future__ import annotations

from backend.contracts.zel_strategy_lifecycle_v1 import seal_registry

SOURCE_REF = "r7a4d-strategy11-data-wait-pool-compute-v1/backend/strategy25/canonical_strategy_registry_v1.json"
SOURCE_BLOB_SHA = "b68cdf7e433bd7c2e6364526f8e2f49f68a0ed8c"
SOURCE_SEMANTIC_SHA256 = "30e4e16f97fd6fbd54aa9fdd2744e0a956cbd0f03e5cc8852aa5a4395a7d5c3d"
REOPEN = ["NEW_EXACT_LEDGER_SHA", "NEW_FAILURE_FINGERPRINT", "NEW_W1_MANIFEST_SHA"]
ROWS = (
    ("alpha_combo", "HYBRID", "AlphaComboLBotStrategy.decide", "backend/strategies/alpha_combo.py", "2cdf64e5e66cf9e2151fbf6d82546d2a9b65a024d1acb1d53bd3d4a62fac30e3", "RESEARCH_ACTIVE", "W1_FRESH_PENDING"),
    ("anchor_vwap_trend", "TREND", "AnchorVwapTrendLBotStrategy.decide", "backend/strategies/anchor_vwap_trend.py", "37712baa33d8ccb8588c4ac7ddf7b17b143d83d4a0050ca164fb9f1655db32e3", "IMMUTABLE_CONTROL", "UNCLASSIFIED_PENDING_LIVENESS"),
    ("bb_revert", "MEAN_REVERSION", "BbRevertLBotStrategy.decide", "backend/strategies/bb_revert.py", "7bbf728f3624eb2960ab37245ab39762918e1ed3512b1c1d3ae1d595e8977f3c", "IMMUTABLE_CONTROL", "GATE_OVERFILTER_OR_ENTRY_TRACE_PENDING"),
    ("break_and_continue", "BREAKOUT", "BreakAndContinueLBotStrategy.decide", "backend/strategies/break_and_continue.py", "74950c1f68ef9d261a71421590c671532908d003839482409ebfb99a920d832d", "IMMUTABLE_CONTROL", "WINDOW_OVERLAP_REPAIR_EVIDENCE_PENDING"),
    ("ema_ribbon_scalp", "HYBRID", "EmaRibbonScalpLBotStrategy.decide", "backend/strategies/ema_ribbon_scalp.py", "e1f7c9560de1435a9d86a059ec316ba6e9e110f2fbfe9d1d376587f6e999e975", "IMMUTABLE_CONTROL", "W1_PRIMARY_EVIDENCE_PENDING"),
    ("fvg_revert", "MEAN_REVERSION", "FvgRevertLBotStrategy.decide", "backend/strategies/fvg_revert.py", "d755efdcebf45e0b26e9ec8ff988226d3e85a13789b512ea5f9a705fc579bb54", "IMMUTABLE_CONTROL", "UNCLASSIFIED_PENDING_LIVENESS"),
    ("grid_rebalance", "MEAN_REVERSION", "GridRebalanceLBotStrategy.decide", "backend/strategies/grid_rebalance.py", "738e63b45dd8a9f47b826632448a9443b56e7660aaec52725468db93e1d6c29f", "IMMUTABLE_CONTROL", "NEAR_BREAKEVEN_ECONOMICS"),
    ("keltner_trend", "TREND", "KeltnerTrendLBotStrategy.decide", "backend/strategies/keltner_trend.py", "cddfeacdface8efbb40eae62b716e6bb9ccbb38d6c8dec0b5f9fd4ebb639da4a", "IMMUTABLE_CONTROL", "UNCLASSIFIED_PENDING_LIVENESS"),
    ("liquidity_sweep", "BREAKOUT", "LiquiditySweepLBotStrategy.decide", "backend/strategies/liquidity_sweep.py", "67d177b02776ec159d34e83fc346c495a87e0d76648901165895bcc83af9b18f", "IMMUTABLE_CONTROL", "UNCLASSIFIED_PENDING_LIVENESS"),
    ("mfi_rsi_div", "MEAN_REVERSION", "MfiRsiDivLBotStrategy.decide", "backend/strategies/mfi_rsi_div.py", "6fb03cb262197dde22e286d08c7a98479552f318a0eb2f4409d673eaf484ec7c", "IMMUTABLE_CONTROL", "UNCLASSIFIED_PENDING_LIVENESS"),
    ("obv_trend", "TREND", "ObvTrendLBotStrategy.decide", "backend/strategies/obv_trend.py", "21810678967758ac1236ab691a4f3ba76e3ec3486fa16e1fdc708f2e0194b6e3", "IMMUTABLE_CONTROL", "NEAR_PASS_LOSS_SHAPE"),
    ("pivot_reversal", "MEAN_REVERSION", "PivotReversalLBotStrategy.decide", "backend/strategies/pivot_reversal.py", "d6d16767b1932a3b6b049f9254f78e7159154461d5d0eb30575570028d736c9e", "IMMUTABLE_CONTROL", "SHORT_OBSERVER_LINEAGE_PENDING"),
    ("range_fade", "MEAN_REVERSION", "RangeFadeLBotStrategy.decide", "backend/strategies/range_fade.py", "9aa21be541dfb47496d67b60f6675e23c7e80095d3747c246eb6ba0d028b5c7d", "IMMUTABLE_CONTROL", "UNCLASSIFIED_PENDING_LIVENESS"),
    ("rbreaker_like", "HYBRID", "RBreakerLikeLBotStrategy.decide", "backend/strategies/rbreaker_like.py", "4460902b968ebcbb7547a3a6e5b45931f4e44b480c8d0403424f2b795026390b", "IMMUTABLE_CONTROL", "UNCLASSIFIED_PENDING_LIVENESS"),
    ("rsi_swing_fail", "MEAN_REVERSION", "RsiSwingFailLBotStrategy.decide", "backend/strategies/rsi_swing_fail.py", "5add278976593751a788c905a8232e0b87daee16fe782fc58f18eb5c6838e23d", "IMMUTABLE_CONTROL", "UNCLASSIFIED_PENDING_LIVENESS"),
    ("scalp_snap", "BREAKOUT", "ScalpSnapLBotStrategy.decide", "backend/strategies/scalp_snap.py", "c39847a06899a2e5f7c925069dbf643078da11a8d59eea9e04722d42bc7d20a4", "IMMUTABLE_CONTROL", "SHORT_DURATION_EVENT_LINEAGE_REQUIRED"),
    ("session_bias", "HYBRID", "SessionBiasLBotStrategy.decide", "backend/strategies/session_bias.py", "de9314ca72f686c8793a3f0a56b81937302b9a89de4ea11edd3ec33e90efe123", "IMMUTABLE_CONTROL", "SESSION_COVERAGE_PENDING"),
    ("squeeze_break", "BREAKOUT", "SqueezeBreakLBotStrategy.decide", "backend/strategies/squeeze_break.py", "c22b4016601ce37fc28999ca7690804c92d3f04997b4d01f06775aa49837ed38", "IMMUTABLE_CONTROL", "UNCLASSIFIED_PENDING_LIVENESS"),
    ("sr_levels", "MEAN_REVERSION", "SrLevelsLBotStrategy.decide", "backend/strategies/sr_levels.py", "81961254c685e735d90df418fb9e75d527199017370237efda8614ef74d680f1", "IMMUTABLE_CONTROL", "UNCLASSIFIED_PENDING_LIVENESS"),
    ("supertrend_pullback", "TREND", "SupertrendPullbackLBotStrategy.decide", "backend/strategies/supertrend_pullback.py", "b5398dfce04260422f04a758736d210763dc8c6097eeca953af82a56eb80fe25", "DORMANT", "NO_GENERALIZABLE_EDGE_REOPEN_ON_NEW_DATA"),
    ("trend_ma_macd", "TREND", "TrendMaMacdLBotStrategy.decide", "backend/strategies/trend_ma_macd.py", "04d98299bd3bd869c379585ba3aed364e2448e180cacaaf21277a4f88a63ec94", "RESEARCH_ACTIVE", "W1_V3_SURVIVOR_CONFIRMATION_PENDING"),
    ("trend_rider", "TREND", "TrendRiderLBotStrategy.decide", "backend/strategies/trend_rider.py", "0fcb0e42b843cd4cdc388a680b809388acf210482547a1d4790af5f688cff290", "DORMANT", "NO_GENERALIZABLE_EDGE_REOPEN_ON_NEW_DATA"),
    ("turtle_trend", "TREND", "TurtleTrendLBotStrategy.decide", "backend/strategies/turtle_trend.py", "c9373eb1b6ea12464c027f177d6d8e49be0ad33635a22442bed9ff605807a80b", "IMMUTABLE_CONTROL", "W1_PRIMARY_EVIDENCE_PENDING"),
    ("vol_spike_fade", "BREAKOUT", "VolSpikeFadeLBotStrategy.decide", "backend/strategies/vol_spike_fade.py", "d1f04e7633cc1cd0f54cd1321c27c21f4b6b98a90f2fac83feafceee5dc2d09b", "IMMUTABLE_CONTROL", "UNCLASSIFIED_PENDING_LIVENESS"),
    ("vwap_revert", "MEAN_REVERSION", "VWAPRevertLBotStrategy.decide", "backend/strategies/vwap_revert.py", "52d2a4454311a604edcb9d74596dc65d092c84267e5fc439b794becd5432e338", "IMMUTABLE_CONTROL", "UNCLASSIFIED_PENDING_LIVENESS"),
)


def build_registry() -> dict:
    entries = []
    for strategy_id, family, callable_name, path, source_sha, state, fingerprint in ROWS:
        entries.append({
            "strategy_id": strategy_id, "family": family, "state": state,
            "observer_allowed": True, "capital_allowed": False,
            "canonical_source": {
                "implementation_path": path, "callable": callable_name,
                "source_sha256": source_sha,
                "source_ref": f"r7a4d-strategy11-data-wait-pool-compute-v1/{path}",
            },
            "parent_sha256": source_sha, "current_child_sha256": None,
            "failure_fingerprint": fingerprint,
            "native_profile_status": "SOURCE_DERIVATION_REQUIRED_NO_INFERENCE",
            "reopen_conditions": list(REOPEN), "evidence_refs": [],
        })
    return seal_registry({
        "schema_version": "zel.strategy_lifecycle.registry.v1", "registry_revision": 1,
        "source_registry_ref": SOURCE_REF, "source_registry_blob_sha": SOURCE_BLOB_SHA,
        "source_registry_semantic_sha256": SOURCE_SEMANTIC_SHA256, "strategy_count": 25,
        "entries": entries,
        "authority": {
            "research_only": True, "runtime_bound": False, "promotion_authority": False,
            "execution_authority": "NONE", "order_authority": "BLOCKED",
            "paper_allowed": False, "live_allowed": False,
        },
    })


REGISTRY = build_registry()
