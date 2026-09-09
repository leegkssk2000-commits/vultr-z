# Public source and duplicate review

Scope: `TOP5_SOURCE_CHART_MECHANISMS_AFTER_PR1228_V1`. Reviewed before new economics. Source research creates no candidate or evaluation allocation. This review does not assert profitability or formal G5 qualification.

All five requested public originals were readable through web extraction. `SOURCE_RECEIPTS.json` records authors, exact short excerpts, source locations, fetch times and hashes. S2/S4/S5 additionally returned HTTP 200 with whole response-body SHA256. Direct S1/S3 requests returned HTTP 403; their hashes are explicitly short-excerpt hashes from successful web extraction, not invented whole-page hashes.

| Source | What it supports | What ZEL adds |
|---|---|---|
| [Brian Shannon / Alphatrends](https://alphatrends.net/anchored-vwap/) | Meaningful anchored volume weighting; price above an advancing AVWAP indicates buyer control. | Strict confirmed radius2 pivots, C54 q/i restrictions, identical low anchor for consecutive AVWAP, HLC3 on completed 4h bars, exact admission/occupancy/exits. |
| [Simpler Trading / Dirty Squeeze](https://www.simplertrading.com/st-dirty-squeeze) | BB20 with ±2 deviations; KC20 with1.5ATR; momentum14; contraction inside KC followed by release. | Population SD, seeded EMA20 and Wilder ATR20, simple14bar price difference, upper-band close test, episode low, next-open fills and20heldbar80h timeout. |
| [TradingMarkets Editors / Larry Connors method](https://tradingmarkets.com/recent/todays_trading_lesson_from_tradingmarkets-649736) | Plus One's new20day low, priorlow at least3 sessions old, setup close at/below priorlow, next-day reclaim entry and same-day expiry. | Completed UTC days from6 contiguous4h bars; completed4h reclaim replaces original intraday buy-stop; next-open fills, midpoint target and12bar48h exit. R1 is an adaptation. |
| [Fidelity / Fibonacci Retracement](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/fibonacci-retracement) | Two extreme anchors and38.2%/61.8% levels as possible support/resistance references. | Fixed inclusive depth interval, causal pivot coordinates and equal-width .350–.586 control. Similar F1/F0 results would not establish special Fibonacci efficacy. |
| [John Bollinger / Band Rules](https://www.bollingerbands.com/bollinger-band-rules) | Traditional SMA bands; squeeze use; price distributions and small samples do not justify automatic statistical claims. | No creator-exact strategy, audited returns or formal significance credit is inferred from the educational source. |

## Volume gate

The canonical manifest at `6d6335d1c9ad7ecb1e9597da85c2eb87635561e1:research/data/g5a_stage_v1/development_manifest.json` binds the seven symbols' requests, payload and normalized dataset hashes. It does not label volume as base asset, quote asset or fixed contracts. Existing positive volume values, previous RVOL work and a local variable named `last_base_volume` are not independent proof of units.

A bounded official lookup found [BingX's swap market reference](https://github.com/BingX-API/api-ai-skills/blob/main/skills/swap-market/api-reference.md), immutable Git blob `53e345a26fe6b79a448c6f848124834ad2c3c404`, section6. For the exact `/openApi/swap/v3/quote/klines` endpoint it labels array element5 as base-asset volume and element7 as quote volume. The archived manifest does not retain whether original responses were that array schema or the runtime object schema. The collector normalizes either object `volume` or array element5. The official excerpt does not explicitly type object `volume`.

Therefore `volume_bindings` remains empty, `basis_verified=false`, and T1/F1/F0 remain source-blocked unless the single integration writer connects an original array payload/schema or obtains explicit object-volume authority before freeze. M1/R1 do not depend on AVWAP volume units and can proceed independently. No market-data request was made. AVWAP, when admitted, must remain a 4h HLC3 **BAR_PROXY**, never tick VWAP.

## Actual legacy code and receipt comparison

Four original canonical owners were fetched read-only by immutable Git blob from the existing recovery ref `r7a4d-strategy11-cause-aware-rotation-l090-v6`. Their computed SHA256 values exactly match `backend/research/zel_strategy_lifecycle_registry_v1.py`: this establishes the historical source identity rather than relying on strategy names. Current lifecycle/source-pin/factory receipts and the existing `evidence_packet_vwap_revert_v1.json` remain preserved.

| Existing owner | Actual code differences from the new frozen lane | Duplicate finding |
|---|---|---|
| `anchor_vwap_trend.py` | Most recent120bar extrema via `idxmin`/`idxmax`; EMA21/55, beam/reclaim tests, ATR stops/trailing, variable size and adds. T1 uses confirmed ordered pivots and exact C54/B entry context and C51 exits. | Not the same economic rule. |
| `squeeze_break.py` | BB20/2 and KC20/1.5 overlap, but ATR14 is rolling-mean TR, EMA34 trend/impulse/retest filters, ATR stops/trailing, variable sizing and adds. M1 has seeded ATR20, MOM14, fixed episode low and80h exit. | Shared source mechanism; not an exact duplicate. |
| `vwap_revert.py` | Cumulative VWAP displacement with RSI14 extension/reclaim, EMA20/55 trend veto, ATR stops, adds and sizing. It does not implement R1's UTC daily20day low/next-day setup or T1's confirmed pivot trend filter. | Not an exact duplicate. |
| `liquidity_sweep.py` |20input-bar extrema, wick/ATR and RSI thresholds, EMA21/55 trend veto, ATR stops, sizing and adds. R1 explicitly needs20 complete UTC days and the Plus One next-day reclaim contract. | Not an exact duplicate. |

No original economic evaluation was rerun. This is a bounded comparison against the four requested existing owners and their receipts, not a claim about every possible unseen strategy. No paid AI, candidate search, new quote collection, OOS access, order or deployment occurred in this source audit.
