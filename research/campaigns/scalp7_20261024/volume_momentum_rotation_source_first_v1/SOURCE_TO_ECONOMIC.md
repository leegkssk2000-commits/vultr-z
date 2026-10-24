# Source-to-costed DEV: long-only daily volume-weighted relative momentum

Scope: 2026-10-24 one pre-frozen numerical hypothesis and a price-only control. No paper's published returns were copied. No paid AI, orders, market requests or economic FULL.

## Source intake and authenticity
1. **Research / economic hypothesis:** Huang, Sangiorgi & Urquhart (2024), *Cryptocurrency Volume-Weighted Time Series Momentum*, SSRN https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4825389 . The abstract reports a volume/TSMOM premium, but their long/short portfolio, factor universe and reported returns are not our single-long setup. Numeric score, 24h lookback and 7-day volume normalization in our FREEZE are **ZEL authored**, NOT their literal strategy.
2. **Negative external replication:** Arefev (2026), *Cross-Sectional Momentum in Cryptocurrency: A Net-of-Costs Replication*, https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7404139 . The abstract reports that selected recent momentum specifications fail robust net-of-cost inference; this is not direct validation of our one-asset ranking.
3. **Practical forum discussion, low evidence:** Reddit r/algotradingcrypto, https://www.reddit.com/r/algotradingcrypto/comments/1ug70gp/we_tested_crosssectional_momentum_on_20_crypto/ (June 2026). User claims a 20-coin test and random-ranking control. Not independently verified. Do not import their Sharpe, 90-parameter grid, thresholds or claim performance.
4. **YouTube dedup audit:** Quantified Strategies *Ranging Trading Strategies (NR7) Since 1990*, https://www.youtube.com/watch?v=MHbAliaJo-c (2023; indexed chapter metadata 0:44 rules and 1:23 backtest; no transcript verified). Toby Crabel NR7/ORB already benchmarked in project v8, source backend/research/rebuild/benchmark_web_crabel_orb_v8_results.json: 35 trades, NetExp -43.04 bps/trade and PF0.486. Do not rerun or treat video popularity as evidence of edge.
5. **Crabel original recent source:** https://tobycrabel.substack.com/p/opening-range-breakout-a-century. Different daily ORB design. It is NOT the methodology claimed for our volume-momentum calculation.

## Implemented test
- Pre-outcome FREEZE.json SHA256 2a6160d0a5952e24ffd916961df87a14c231242f7965143d0f817aeeea294825.
- Original archived BingX **used** hourly source manifest SHA256 bce71f9b39dee91d7ebe074da0407d672f1ead645ade5ccd788c45f96cee5bf7; six symbols, 5,115 exact validated source bars each, no interpolated bars.
- Daily UTC 00:00 decision using previous 24 complete candles; entry next hour 01:00 open; fixed two ATR14 stop, following day 01:00 full exit, max 1 simultaneous position.
- Volume adjusted score vs price-only score on same entry calendar, costs and stop; 11 focused synthetic tests PASS. No parameter grid.
- Used historical TRAIN 88 calendar days, subsequent used LATER 90 days. No independent untouched OOS or live receipts.
- All-in roundtrip scenario 20/40bps, actual historical funding and market fills unknown. Full trade rows/pins in RESULT.json.

## Economic result
| Variant | TRAIN T | TRAIN Net2 bp | TRAIN PF2 | LATER T | LATER Net2 bp | LATER PF2 |
|---|---:|---:|---:|---:|---:|---:|
| Price only | 59 | -2306.1550 | .6501 | 59 | +1157.4006 | 1.1780 |
| Volume adjusted | 59 | -2227.0448 | .6656 | 59 | +1350.6748 | 1.2150 |

Volume weighting increased Net2 by +79.11bp TRAIN and +193.27bp LATER, selecting different coins on respectively 10 and 9 daily entry decisions. But the sum of both used periods is still **negative Net2 -876.3700 trade-bps**. It fails the target daily frequency (~0.66/day) and cannot be adopted as an independent positive strategy. REJECT this exact frozen numeric variant without parameter retuning.

## Project diagnosis and constraints
- Source inventory -> executable rule -> verified input -> costed result is the ONLY economic development measure. Past documentation-heavy loops consumed time; KAMA and Grimes were both cost2-negative, HGL1 source compiler is code-ready but market input and D claim still HOLD.
- Do not repeat a strategy already represented by project v8 / v11 records. NR7 old evaluation discovered before running.
- Paper gross or forum reported results cannot be treated as cost2 profits for six BingX futures.
- Work A retains exclusive authorized official Squeeze FULL; limited PAT API dispatch had HTTP403, no bypass attempted here. No master, A owner, active writer, B/K117, C, G5 or real order changes.
- Freeze/source hashes and script are additional source branch evidence, not a production survivor. Do not retry this exact rule on the same used source or change thresholds after viewing outcomes.

Next viable action: existing A Squeeze official FULL in authorized workflow, or independently sourced genuinely distinct mechanic with verified executable input and one predeclared cheap model screen.
