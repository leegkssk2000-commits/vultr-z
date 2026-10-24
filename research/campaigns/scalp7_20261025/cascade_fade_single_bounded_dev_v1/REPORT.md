# Curupira cascade-fade external source — actual bounded BingX 1m economic screen

**Scope: SOURCE-REFERENCED ZEL *translation*, not original author code. Terminal decision: REJECT_ECONOMIC_EARLY; never retune these same historical used periods to manufacture a positive result.**

## Source and distinction
- Primary article: https://curupira.dev/blog/cascade-fade-scalper-fading-liquidation-overshoots/
- Related original author build video (embedded official public link; video itself not independently transcribed): https://www.youtube.com/embed/gWCOoviLEc0
- Author's reported mechanism: 5 completed one-minute price-velocity bars AND volume spike >3x previous baseline, fade downward cascade, close after 1–3min. Source does **not** disclose exact numeric velocity cutoff, real fill data, or all execution details needed for verbatim replication. Claimed SOL/ETH positive walkforward and small live fills are AUTHOR-reported, not exchange audited.
- Internal ZEL hypothesis frozen *before results*: log return of 5 closed 1m bars <= -1.00%, current volume >=3x previous 60 complete1m average, LONG SOL/ETH only, entry next1m OPEN, EXIT 3m later OPEN, single position/symbol. Original's STOP/TP timing, true maker/limit queue, liquidation detection, funding and live slippage are NOT represented; do not transfer source claims.

## Source verification
- Six-symbol source inventory is already cached; this child read ONLY SOL and ETH from existing canonical_postgap archive, 214 gzip day-files each, 306924 timestamp-contiguous valid one-minute OHLCV rows/coin. No new downloads of market candles and no original source mutation.
- Raw gzip SHA per file in RESULT.json; source parent MANIFEST SHA `bce71f9b39dee91d7ebe074da0407d672f1ead645ade5ccd788c45f96cee5bf7`; pre-result contract SHA `148d08ea90a8965810764fc0d6453bbb9f5de87780121ab06de9db336a5dbfa4`; result SHA `47499c8f7b78c4e184ce08720b6e19c45131abde6d78a9d2c39e4f532d255a13`.
- Historical TRAIN and LATER have **both been used by older development**. Not untouched holdout or genuine 2026-10 new forward data. Fixed 20bp and 40bp all-in modeled roundtrip costs, without actual funding/received_at; units trade-bps, not NAV%.

## Real cheap screen after 40bp modeled roundtrip
|metric|TRAIN 88d|LATER 90d|
|---|---:|---:|
|T|82|93|
|signals per day (completed trades)|0.932|1.033|
|Gross/T|+2.620bp|+13.178bp|
|Cost1 Net SUM|-1425.160bp|-634.479bp|
|Cost2 Net SUM|-3065.160bp|-2494.479bp|
|Cost2 PF|0.104|0.222|
|Cost2 WR|15.85%|29.03%|
|Max losing streak|18|26|
|Realized DD2 trade-bps|3072.30|2609.92|

Raw Gross/T <20bp in BOTH fixed partitions; heavy FULL would be waste. This *specific* rule cost-killed; author reports on Hyperliquid are not comparable (different data/venue, thresholds and fill). No STOP/funding account-NAV evidence; no order, Paper or LIVE, no formal G4/G5 credit.

## Other independent sources actually checked, do not clone claims
1. **CacheCarti Crypto-Strategies**: https://github.com/CacheCarti/Crypto-Strategies ; public commit `f8e32599c192b823dbe7aea77a2b9341c6114527`. Read all ten published `passed/` report cards as original JSON, preserved per-file raw hashes. The ten cards display negative OOS returns, even while README calls them '7-stage survivors'; each card reports `stages_passed=2`. These do NOT provide a confirmed positive economic transfer. Details in PUBLIC_CARDS_RECHECK.json.
2. **Freqtrade BbandRsi 1h**: https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/berlinguyinca/BbandRsi.py . Source-exact condition RSI14<30 and close<BB20 lower, exit RSI>70 was already tested in Issue #1388 donor intake: 87T Gross/T -254.60bps. **Do not rerun this failed family**.
3. **BingX Futures Grid / Bybit Martingale**: https://bingx.com/en/bot-trading ; marketplace delivery is not alpha evidence. Previously frozen K117-based grid proxy original 88d 1024T Net2 -44,820bp and later 90d 1001T Net2 -44,096bp. Trading-frequency alone cannot fix negative expectancy; different venue market-making fill and proper queue data needed.
4. **Keel external futures strategy cases**: https://usekeel.io/strategies ; some same-vendor backtests report positive, but they use Hyperliquid, 10 symbols, both long/short and different fees/funding. MACD/Trend and Supertrend cases overlap current in-repo 4h/G5 analysis, while Funding+Momentum lacks contemporaneous BingX funding/price side inputs for exact costed port. No naive copy.
5. **User-linked cost-aware research**: https://github.com/PeterLP123/systematic-crypto-research ; 263 post-selection days Trend strategy +9.54% (author reported), BTC-dominance MR -6.96%; timeframe daily/covariance and exchange incompatible with today's low-latency orderless source; note but do not call an eligible 30m ZEL survivor.

## K117 safety and next handoff
K117 117 saved closed historical model rows Cost2 Net+8399.99trade-bps, PF2 2.162; max11 loss streak and 23 original price-R losers below -1R due cost/gap. **This is NOT Shadow PASS.** VPS `/home/z/z/runtime/k117_development_20261023T184907Z/STATUS.json` last seen Oct24 20:49 Berlin: `STOPPED`, `B_SOURCE_WRITER_NOT_LIVE`, 270 development decisions, 0 live virtual fills, 0 order calls; upstream B4 writer epoch stopped and formal admission PREAUTO/G4/G5 unverified. Leave real order blocked. Resume only through existing B owner with a single verified fresh source epoch / non-duplicate writer, no backfills and measured received_at/cost risk.

**A/C next:** stop reusing already-rejected BB RSI, Donchian / MACD / grid / MR aliases. Novel OHLCV-only directional strategy must cross cheap cost gate on pinned source BEFORE full. Continue source-led intake within already-approved Issue1388, not new Work. No paid external API.

## Executed code byte pin and reproducibility
- Source code used in the executed cheap screen is preserved byte-for-byte in `RUN_EXECUTED_SOURCE.py.txt`, SHA256 `8fe64531d1ed24dd91a12eb05c2159f231971c839f58be3286b5a551722f8a36`; `run.py` may be formatting-linted after execution but economic receipt is unchanged.
- The source original archive is immutable and must be run with the same FREEZE/source directories to reproduce, not executed in the production environment. The test fixture passed 5 locally.
