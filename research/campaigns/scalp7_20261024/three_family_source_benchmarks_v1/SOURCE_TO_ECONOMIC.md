# Exactly one sourced benchmark each: trend, momentum, countertrend

No parameter grid, repeated failed trials, new Work, heavy owner consumption or orders.
Before-result freeze SHA256 1e8e387675528e4d0ba0f63e9897e55995f231398bfdef18be928d2962b975c7. Market source manifest SHA256 bce71f9b39dee91d7ebe074da0407d672f1ead645ade5ccd788c45f96cee5bf7.
All 6 symbols have 5,115 contiguous actual 60m OHLC bars, assembled into 1,278 verified 4h bars each, no missing/gap/interpolation. Per-file source SHA in RESULT.
Fixed USED training Mar05-Jun01 88d, USED later Jun01-Aug30 90d. Roundtrip model costs 20/40bp, long-only, stop-first, next 4h open. Actual historical market receive times, funding, leverage and account NAV unknown.

## Original source vs ZEL adaptation - do not transfer claimed equity/futures returns to crypto

### Trend-following / Daryl Guppy GMMA stand-alone
Primary original: https://www.guppytraders.com/gmma-info
Grounded original: Two EMA groups (3,5,8,10,12,15)/(30,35,40,45,50,60); trader-investor agreement/expansion; original author does not specify this exact robotic next-open stop.
Frozen ZEL entry: after 240 warmup, first completed4h-bar short-min EMA>long-max EMA with previously short-min<=long-max, and long EMA60 > prior EMA60; enter next 4h open
Frozen ZEL exit/risk: after complete bar EMA15 < EMA30 exit following open; initial stop entry - 2.5*ATR14 at signal; fixed max hold 48 4h bars after entry; fixed initial stop tested intrabar adverse-first; no TP
Previous work overlap: older GMMA HolyGrail mixed donor was benchmarked and is not reissued; this is standalone two-group trend transition (same indicator family, not automatically independent alpha)

### Momentum / Moskowitz-Ooi-Pedersen TSMOM-inspired sign
Primary original: https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum
Grounded original: Moskowitz Ooi Pedersen 2012: 12-month sign of past excess futures return, ex ante volatility scaling, diversifying multiple futures; not a 4h crypto paper.
Frozen ZEL entry: first positive crossing of own 42 completed 4h-bar (7d) log return divided by lagged rolling42-bar log-return std, previous score <=0; long next 4h open; no future input
Frozen ZEL exit/risk: after completed4h bar score <0 exit next4h open, initial stop entry - 2.0*ATR14 from signal; max hold 24 completed bars, stop-first adverse; no ranking or source overlap with prior volume-weighted daily rotation implementation
Previous work overlap: broad time-series momentum already researched; this is fixed sign-cross/vol-normalized MOP-inspired candidate NOT 12-month original replication

### Countertrend / Connors-Alvarez Double7 4h
Primary original: https://alvarezquanttrading.com/blog/double-7s-strategy/
Grounded original: Cesar Alvarez and Larry Connors original daily long SPY: close>200-day SMA, close is 7-day closing low, buy close; close at 7-day high, sell close; no stop originally.
Frozen ZEL entry: on 4h crypto bars only, close>4h SMA200 and close<=last7 closing values; next actual 4h open long, no same-bar reentry
Frozen ZEL exit/risk: 7-4h-bar closing high -> next4h open exit; extra separate safety stop entry - 3.0*ATR14, max24 completed bars, original did not include stop/time cap
Previous work overlap: not Connors RSI2 and not last tested 20bar wick-reclaim; shorter time-scale and stop are ZEL modifications, no source-exact daily performance claim

## Actual costed model results

| Family | TRAIN T | TRAIN Net2 trade-bps | TRAIN PF2 | LATER T | LATER Net2 trade-bps | LATER PF2 |
|---|---:|---:|---:|---:|---:|---:|
| Trend-following / Daryl Guppy GMMA stand-alone | 38 | -4249.90 | 0.523 | 37 | +9803.03 | 2.217 |
| Momentum / Moskowitz-Ooi-Pedersen TSMOM-inspired sign | 72 | -4122.94 | 0.365 | 93 | +11766.98 | 2.743 |
| Countertrend / Connors-Alvarez Double7 4h | 69 | -2043.19 | 0.726 | 65 | -3378.78 | 0.506 |

## Honest one-shot verdict
- Trend GMMA: 38 TRAIN trades negative, 37 LATER trades positive, combined Net2 +5553.13 trade-bps. Fragile across regimes: HOLD, not production PASS.
- Momentum MOP-inspired: 72 TRAIN trades negative, 93 LATER trades positive, combined Net2 +7644.03 trade-bps. Not original 12-month signal, not academic replication: HOLD.
- Countertrend Double7: both negative, combined Net2 -5421.98 trade-bps/134 completed trades: REJECT fixed 4h ZEL version, no retune.
- No objective universal BEST exists; these are prioritized reproducible original-source hypotheses, selected before economic results.

## Joint holdings not independent sources

- TRAIN_momentum_countertrend: 201 time-overlap trade pairs, 31 same-symbol and 0 matching signal times.
- TRAIN_trend_countertrend: 248 time-overlap trade pairs, 40 same-symbol and 0 matching signal times.
- TRAIN_trend_momentum: 204 time-overlap trade pairs, 36 same-symbol and 3 matching signal times.
- LATER_momentum_countertrend: 172 time-overlap trade pairs, 31 same-symbol and 0 matching signal times.
- LATER_trend_countertrend: 194 time-overlap trade pairs, 40 same-symbol and 0 matching signal times.
- LATER_trend_momentum: 244 time-overlap trade pairs, 42 same-symbol and 3 matching signal times.

## Offline integration and gate
- benchmark.py has complete costed replay, test_benchmark.py includes adversarial tests; frozen source and exact inputs in RESULT.json.
- research_adapter.py is DEFAULT_OFF, emits only old USED-dev 4h candidate signals on explicit offline opt-in; test_research_adapter.py prohibits Live/G5.
- Current scalp7_execution_v2.TF_ALLOWED=(15,30): native Scalp7 15/30 cannot accept these 4h signal rows. We DO NOT alter core or mislabel timeframe.
- RESEARCH_ONLY_SIGNAL_EXPORT.json contains 688 modeled pretrade opportunities, NOT 688 executed trades. Actual completed model trade totals are 75 / 165 / 134 over two used partitions.
- Existing C 4h owner can accept this additive signal source only after independent native 4h and verified forward as-of, cost, volume unit, writer/owner and PREAUTO controls.
- Historical funding/account NAV and user trading MinData are missing, so these cannot be sent to Paper/Live or G5 and action remains hold.

## Preservation
- No change to existing Squeeze, K117, Supertrend, Keltner, A economic FULL, B writer or protected G5/Live.
- No new program strategy is activated. Squeeze 57T denied ledger and old KAMA/Grimes/etc were not reaccessed/replayed.
