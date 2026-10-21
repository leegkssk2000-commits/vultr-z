# C2: closed downside failure and later range recovery

Source/code-ready internal adaptation. Economic result NOT_RUN. No adoption.

## Primary provenance

Existing S309: TradingMarkets Editors, *Today's Trading Lesson From TradingMarkets*, 2004-09-09, https://tradingmarkets.com/recent/todays_trading_lesson_from_tradingmarkets-649736 . Re-read once on 2026-10-21. Larry Connors methodology; original market futures, timeframe daily. This page describes aged 20-day extreme reversals, tick-based stop entry and protective stops. Plus One requires an outside close followed by the next session's recovery and discusses short-lived reversal exits. It is publisher methodology evidence, not an audited author profit ledger.

Existing code reference: `backend/research/rebuild/scalp7_exact25_reference_v1.py#SOURCES.liquidity_sweep`, reference base `3f4a798f15fbb3a21f3f6063db1b063b95d182e0`. The existing daily Soup model in `scalp7_exact25_reference_models_v1.py` remains unchanged and depends on historical point-in-time ticks; this adapter does not pretend to satisfy that contract.

## Explicit ZEL adaptation

All exact lifecycle choices are in SPEC.json, saved before implementation and synthetic tests. Daily periods are replaced by 30m completed bars. A closed downside break then a later closed recovery replaces a same-session tick stop order. No tick value is inferred. Frozen-range midpoint close exit, three-bar recovery deadline, twelve-bar holding cap and one-consumed-reference rule are internal hypotheses. Long-only applies to this new identity and does not reinterpret K/S controls. No public performance figure is used as an acceptance threshold.

## Preserved failure lineage

At base ref above, `research/campaigns/scalp7_20260917/source_fidelity_v1/audits/MATERIAL_HOLD_SOURCES.json` records failed RangeFade and BBRevert donor identities. Those 5m recovered receipts are failure lineage only; their full data/window/cost seals are not proved by the summary rows and are not matched 30m controls here.

`research/campaigns/scalp7_20260915/broad_rebuild_v2/results_binding_repair/` retains exact rbreaker/RSI/Rider/Break/Supertrend failures; `SCALP7_BROAD_REBUILD_V2_FINAL_REPORT.md` and `CAMPAIGN_PREREGISTERED_V2.json` bind identity, windows and reference costs. The later Sep17 source-fidelity `FINAL_DECISION.json` also rejects RSI oscillator-failure and Break shallow-repair adaptations. None are rerun or renamed.

C2 requires close-below then a later close-inside an aged fixed range, unlike same-bar RBreaker wick reclamation or RSI-turn confirmation. Extreme stop and geometric close exit replace their ATR/indicator templates. K/S trend-continuation controls are preserved. Whether C2 adds other days or improves net returns is unmeasured.

## Input and accounting

Existing six-symbol certified 30m OHLC/availability/segment fields only; no volume, L2, OI or historical tick fiction. Unchanged Scalp7 engine supplies next-open fills, hard-stop precedence, adverse gap-stop pricing, unresolved gap/end ownership, duplicate rejection and positive reference costs. Shared adapter keeps original independent windows: validation30 days separate; rolling245 days, six symbols. Cost2x reuses the same fills. Costs are reference scenarios, not actual historical fees/funding/latency proof. Existing owner alone performs its authority, budget, capacity and consumption checks before running the supplied CLI.
