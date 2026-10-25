# ZEL — Three published Freqtrade bots directly copied and screened against BingX

2026-10-25 one-shot, read-only, NO new Work, no global FULL, exchange collector or real orders. The exact GPL-3 originals were version-pinned and saved, not guessed.

## Exact original source and fixed rules

- Official repo: https://github.com/freqtrade/freqtrade-strategies ; commit SHA f3340ce11f5bdf62f598522e64d1f5638eaa13f5, original license GPL-3.0 and author attribution preserved in immutable source archive.
- BbandRsi 1h: RSI14<30 and close below lower BB(20,2) of typical price, exit RSI14>70, ROI10%, stop -25%.
- ClucMay72018 5m: close<EMA50 and close<0.985 lower BB(20,2) of typical price and volume<20x previous30 average volume, exit close>BBmiddle, ROI1%, stop -5%. Unknown absolute volume unit cancels for a stable within-symbol ratio, but historic unit stability is not independently certified.
- MACDStrategy_crossed 5m: MACD(12,26,9) crosses ABOVE signal and CCI14<=-50, exit below crossover and CCI>=100, ROI 5/4/3/1% at 0/20/30/60 minutes, stop -30%.

Original source hashes and exact links:
- BbandRsi.py: SHA256 65718e8d0c14094b67be82b66238ea60a4af4bbf6fd9a6e1879dad5c48125547 ; https://raw.githubusercontent.com/freqtrade/freqtrade-strategies/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/berlinguyinca/BbandRsi.py
- ClucMay72018.py: SHA256 d146f7bc8285b5f1e48514d5d6acc53b37b0ca00299780210e3bdf84564978aa ; https://raw.githubusercontent.com/freqtrade/freqtrade-strategies/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/berlinguyinca/ClucMay72018.py
- MACDStrategy_crossed.py: SHA256 af5aed1cbb9a9d3ed519ea8649363a2cfaa95cbffe443f073d9f96b2aa91b0f6 ; https://raw.githubusercontent.com/freqtrade/freqtrade-strategies/f3340ce11f5bdf62f598522e64d1f5638eaa13f5/user_data/strategies/berlinguyinca/MACDStrategy_crossed.py

## Original data and execution assumptions

- Fixed source original BingX 1m archived trade market 2025-12-15 to 2026-02-13 UTC, 60 days x six native symbols. 360 complete daily gzip files, 518400 continuous minute rows in this subperiod (1440 per UTC day), 0 missing/forward-filled; SHA for every raw file in SOURCE_CENSUS.json.
- Full canonical_12m archive has global HOLD_SOURCE_INTEGRITY; only this exact locally checked subperiod passed OHLC/time continuity. Historical actual HTTP received-at, native exchange fills and actual signed funding are UNKNOWN. This is used history, not OOS.
- Entry on actual next complete TF bar open after signal close; conservative stop FIRST if both TP/SL intrabar, gap filled at worse observed open; original ROI schedule and native stop magnitude; exit signals next TF bar open. No leverage/NAV conversion. Original native Freqtrade engine was NOT installed or backtested, so it is source-reproduced signals with explicit manual execution assumptions, not strict engine parity.
- Fixed cost scenarios 20/40 instrument bps of roundtrip fee+impact, without invented actual funding. No source API call for price rows and no trading API.

## Cost-after screening outcomes

| Original bot | timeframe | Completed T | Net20 summed trade-bps | Net40 summed trade-bps | PF40 | WR40 | DD40 trade-bps | MaxLossStreak |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BbandRsi | 1h | 23 | -22,212.48 | -22,672.48 | 0.138 | 47.8% | 25169.18 | 6 |
| ClucMay72018 | 5m | 27 | +941.15 | +401.15 | 1.410 | 85.2% | 540.00 | 2 |
| MACDStrategy_crossed | 5m | 85 | -15,996.06 | -17,696.06 | 0.220 | 88.2% | 21096.66 | 3 |

## Cluc May 7 2018 — weak economic positive but still HOLD

- Cluc cost40 T 27, Net +401.15, PF 1.410, WR 85.2%, realized cohort DD 540.00, max losing streak 2.
- First30d Net -368.43 on 3 trades; last30d +769.58 on 24 trades.
- Net without top two wins +281.15; remove DOGE and leave rest static cost40 -18.85 (NEGATIVE).
- Cost60 Net -138.85, cost80 Net -678.85. Edge weak against realistic added funding and slippage.

## Final fate and protection

- BbandRsi = FAIL_NEGATIVE_COSTED_SCREEN. MACDStrategy_crossed = FAIL_NEGATIVE_COSTED_SCREEN. Preserve original/code and costly losing tails, no retune, no expensive replay.
- ClucMay72018 = SCREEN_DEV_POSITIVE_WEAK_HOLD. Native copied mean reversion distinct from TrendRider and K117. One unburned new prospectively pinned forward comparison may be warranted only after actual source/fee funding and signed orderless as-of verification, no Paper/Live.
- All three from official freqtrade-strategies GPL-3 repo; archived exact originals with license, clean-room signal implementation. User can inspect hashes and prevent source/license drift.
- Current K117 price-only Shadow signal observation remains a separate no-order workflow, no modified K117 policy, no G4/G5 promotion implied.

## SHA256 receipts
- FREEZE.json SHA256 e60118cafbcfd1237ed6302488cb4588f6c5fa07385846b8d7b90e8a7058bd84
- SOURCE_CENSUS.json SHA256 9c0323d93b32f0f9c35a46baa8d9bb94d20f4aa757d5732fcf1c8cefc3cf6196
- RESULT.json SHA256 a6d817ba55cd187c645bfaca76a42b58af798c4e128d7108ea211b80e4ae17c0
- TRADES.json.gz SHA256 d0612d3a312b4b6ea85f81a053e79354cbc83aa4f1d9f3243e864dfc4dfc8d4f
- AUDIT.json SHA256 24b9c686da13f30f3132127abf0e0d9600366cf1ece65923cb61d7e0ce27dea7
- screen.py SHA256 24e471a85ee2263e89abdabff0a62ebc8d19bda6d63d8fe5bfdc6855807948a6
- audit.py SHA256 9c9d0b86481ddd72e390437eae608ee6060f05656131758d20b5be371205306c
- test_screen.py SHA256 d887c050c90f5fc26348f5f1b7dae54a3db7bc0b143cd9164c69ac3c78cb2962
- source/LICENSE SHA256 8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903

GPL source archive original SHA256 38d09a4d8618fd7d9147b295ebca9cbd2f0494078377d1450f1e75713c8ededa
Executable reproduction from repo on the same authorized VPS: python -B screen.py && python -B audit.py. Inputs are source-pinned 2025-12-15 through 2026-02-13 UTC, never market downloads.
