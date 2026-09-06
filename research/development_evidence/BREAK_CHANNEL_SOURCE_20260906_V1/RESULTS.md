# Break channel preparation: source and frozen ZEL adaptation

Source: Hudson & Urquhart, [Technical trading and cryptocurrencies](https://link.springer.com/article/10.1007/s10479-019-03357-1), [published PDF](https://link.springer.com/content/pdf/10.1007/s10479-019-03357-1.pdf). Appendix §5 CB1 pp217–218 (PDF26–27); daily data §2 pp195–196; prior-close position/return Eq2 §4 p197; costs §4; unused-period discussion §6.5 pp212–213. PDF SHA256 `04e9ae429b3a32cb835d29a12ce8e4b29048f54fd156adca2b5d3f3c2e405e6b`, identical to prior S1.

The previous RESEARCH.md's OOS section number §6.3 is corrected here to **§6.5**, preserving its original bytes. The paper's c menu repeats0.5; counts conflict and Table9 contains0.025 absent the printed menu. Current published HTML/PDF retain these issues. No linked correction/supplement was found. Reading's copy required Anubis and SSRN3387950 full text returned403. We do not infer missing author parameters/code or transfer paper returns to Q.

## Three-column specification

| Source-confirmed rule | Selected ZEL rule / DESIGN_PRIOR | Verification risk caused by the difference |
|---|---|---|
| CB1 previous j daily prices form a c%-narrow channel | Previous2 **daily closes**, H/L−1≤0.005; U=L×1.005, D=H×0.995 | Literal0.5%=50bps; possible undocumented author coding cannot be recovered from return tables |
| Price exceeds a channel boundary by x% for d periods | j2,d2,x0%,c0.5%; strict crossing at x0 | A single printed cell, not the best reported cell; no parameter search |
| d-period confirmation; exact threshold updating unspecified | DESIGN_PRIOR: latch bounds at first breakout; two consecutive closes; failed attempt cancels without same-day restart; nextday may rearm | Latching, cancellation and repeated-trigger semantics are ZEL assumptions |
| Channel readiness conditions the breakout | Q-minus removes **only bullish entry preparation**; same thresholds, confirmation, exits, stop and ownership. DESIGN_PRIOR: on either confirmation close, being below latched D rejects/cancels an UP attempt even without a confirmed DOWN signal; DOWN attempts may continue | Without preparation U may lie below D; this preconfirmation conflict policy is identical in both variants and is counted, not silently repaired |
| Source permits long and short; CB1 has no fixed k exit | DESIGN_PRIOR: long/cash; hold until common bearish two-close confirmation, regardless of preparation, or protective stop | Bear confirmation is a common exit assumption; no source-complete replication, short or hold6/hold12 substitution |
| Original spot-return model is based on prior close; exact exchange orders/SL unspecified | DESIGN_PRIOR: next-open market entry/exit; initial latched D protective stop; no trailing/TP; entry gap at/below D cancels | Added protection changes the system; stop trigger/fill is modeled, not exchange verified |
| Intrabar event priority unspecified | DESIGN_PRIOR: existing SL gap at open first, pending bearish exit second, entry third, intrabar SL afterward. Gap fills observed open; other SL fills D | Unknown intrabar SL time assigned4hclose upperbound; funding conservative; full-stopbar MFE/MAE may include postfill path |
| Daily source interval | UTC six complete frozen4h bars per day; partial endpoint days discarded, internal gaps fail; actual4h bars only for protection | Aggregated feed differs from paper's spot series, assets and era; no invented prices/volume |
| No matching current-parent evaluation interval | Common UTC2025-01-29 00:00 through2025-12-29 00:00; all variants start flat; P keeps native4h rule | Max(parent240×4h warmup, daily needs) determines start; existing full P remains separately recorded; initial-position effects reported |
| Source performance/cost study is independent of ZEL | Existing RESEARCH_COST_MODEL fee/spread/impact/slippage/8h funding and20bpsfloor; cost2 doubles entire cost | No signed funding or actual execution lineage; equal notional is **not equal risk**, account return or account MDD |
| No complete censoring/valuation specification | DESIGN_PRIOR: signals/entries strictly before end, held-bar close and mark may equal end; no forced exit. Open gross/funding/full-cost hypothetical net separate | Entry-side cost cannot be separated from roundtrip binding. Daily open-position marks charge full hypothetical exit cost; not realized PnL |

Parameter selection order, before any new DEV signals or outcomes: choose CB1 to study trend holding; choose smallest printed j=2 for available history; smallest printed d=2 (d=1 is not listed); x=0 to avoid another hurdle; widest explicitly printed c=0.5% for short-history applicability. No signal frequency or return was inspected for these choices. The repeated c value is not treated as another distinct cell.

Q and Q-minus begin with identical market data, calendar, parameters, exit/protection/cost code and maximum one equal-notional long per symbol. Signals blocked by ownership are recorded as opportunities with unknown counterfactual PnL; no extra isolated-trade strategy is run. Cash is a zero-turnover reference, not another strategy allocation.

## Preregistered interpretation and limits

P→Q and P→Q-minus use MECHANISM_REPLACEMENT. Exact source-time overlap and original profit preservation explain changed trades; they are not economic rejection thresholds. Q-minus→Q is the preparation ablation. Pointwise loss reduction is separated from absolute positive economics.

The existing absolute screen (minimum6 completed trades, positive net/expectancy, PF>1, payoff≥1 and positive cost2) is retained. A research-promising label additionally needs positive lower95% calendar improvement and no deterioration in inherited grouped loss-run/DD. Exposure and win-rate changes are reported as tradeoffs. Unresolved positions make the overall conclusion inconclusive. No new formal eligibility is created.

Paired daily marked-equity changes include zero days and are resampled in **fixed30-day noncircular blocks,1000 draws,seed1178**. These blocks are not proven independent; long holding or cross-symbol dependence can exceed them. Prior DEV reuse/trial selection is not corrected. Existing closed-entry-week intervals remain descriptive only. Profit concentration, monthly results, closed/marked drawdown and unrecovered periods are reported, with no best-period or best-symbol reselection.

Prior22 trial history remains immutable; Q23 and Q-minus24 consume this explicit two-slot allocation. Same-result reproduction does not consume a new strategy. No new timeframe/universe/period/parameter/risk variant or automatic retry after outcomes. The existing Top5 development CI is extended; old comparison functions/decisions are preserved.

Formal validation/OOS, seen Break validation reject, G5B collector/open intent/boundary and operating strategies are outside this experiment's authority. execution=NONE; order/live=BLOCKED. No paid external AI is invoked; Gemini video input is NOT_RUN. Research protection does not make either strategy ready for real trading.

## Measured economics

Same calendar/universe and equal-notional model; not equal risk or account returns. P native4h hold6 is unchanged; Q/Q-minus are daily ZEL adaptations with common4h protection.

| Stage | Signals | Closed/open | GrossE | NetE | PF | Win% | AvgWin | AvgLoss | Payoff | Cost2E | Net sum |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P | 282 | 155/1 | 53.9329 | 33.7449 | 1.2333 | 50.9677 | 349.9504 | -294.9424 | 1.1865 | 13.5570 | 5230.4611 |
| Q | 102 | 86/0 | 73.5522 | 47.3970 | 1.2407 | 33.7209 | 724.5046 | -297.0963 | 2.4386 | 21.2418 | 4076.1430 |
| Q_minus | 433 | 285/3 | -54.7195 | -79.4953 | 0.6994 | 24.5614 | 752.9591 | -350.5270 | 2.1481 | -104.2712 | -22656.1657 |
| CASH | 0 | 0/0 | NA | NA | NA | NA | NA | NA | NA | NA | 0.0000 |

| Stage | Fee sum | Funding sum | Total cost | Max simultaneous | Exposure days | Max loss-run | Closed DD | Marked DD | Recovery days / unrecovered |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| P | 1550.0000 | 553.1400 | 3129.1314 | 7.0000 | 155.3333 | 2735.5014 | 4102.5657 | 4289.8967 | 98/True (87 days open underwater) |
| Q | 860.0000 | 934.6400 | 2249.3472 | 6.0000 | 276.6667 | 5224.6878 | 6696.6626 | 6801.4788 | 85/True (159 days open underwater) |
| Q_minus | 2850.0000 | 2572.2600 | 7061.1129 | 7.0000 | 738.3333 | 16923.1168 | 23330.7447 | 23450.7447 | 0/True (333 days open underwater) |
| CASH | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0/False (0 days open underwater) |

## Mechanism and preparation comparisons

| Comparison | Overall / closed screen | Closed net delta | Common closed/censored | Removed/new closed/new open | Original profit retained range | Large profit range | Daily marked delta95% |
|---|---|---:|---|---|---|---|---|
| P_to_Q | DEV_INCONCLUSIVE/DEV_INCONCLUSIVE | -1154.3181 | 0/0 | 155/86/0 | [0.0, 0.0] | [0.0, 0.0] | [-72.04284927976447, 77.68717866959958] |
| P_to_Q_minus | DEV_INCONCLUSIVE/DEV_REJECT | -27886.6268 | 3/0 | 152/282/3 | [0.0, 0.0] | [0.0, 0.0] | [-158.97578979400706, 38.22969536527106] |
| Q_minus_to_Q | DEV_INCONCLUSIVE/DEV_INCONCLUSIVE | 26732.3087 | 60/0 | 225/26/0 | [0.3233974408390817, 0.3233974408390817] | [0.5516472807203124, 0.5516472807203124] | [-32.22353715927624, 147.02633075952517] |

Preparation evidence: **NOT_ESTABLISHED**. Origin overlap is explanatory,never a mechanism-quality threshold. Fixed calendar moving blocks and closed weekly intervals are descriptive reusedDEV estimates,not independent validation.

## Terminal observations and concentration

| Stage | OpenT | Gross mark | Funding accrued | Hypothetical cost | Hypothetical net | Cost2 net | Open days | Top symbol profit share | Top-decile winner share |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P | 1.0000 | -148.2913 | 1.0000 | 20.0000 | -168.2913 | -188.2913 | 0.3333 | 0.2151 | 0.3879 |
| Q | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.2972 | 0.4833 |
| Q_minus | 3.0000 | 450.9659 | 15.1200 | 61.6184 | 389.3475 | 327.7291 | 4.0000 | 0.2128 | 0.3492 |

Open marks are never forced completed trades. Entry-side cost is NOT_SEPARATELY_BOUND; full roundtrip marks are an explicit valuation convention. Intrabar stop timestamps are4h upperbounds; stopbar MFE/MAE may include postfill movement.

## Monthly closed gross / net trade-bps

| Exit month | P gross/net | Q gross/net | Q-minus gross/net |
|---|---:|---:|---:|
| 2025-01 | 0.0000/0.0000 | 0.0000/0.0000 | 0.0000/0.0000 |
| 2025-02 | -604.5579/-644.5579 | -1471.0191/-1624.8775 | -9482.5294/-10038.2700 |
| 2025-03 | -2069.4701/-2274.3254 | -2887.8912/-3035.4950 | -9396.7094/-10039.5545 |
| 2025-04 | 2600.7190/2275.8638 | 1351.8304/1176.3116 | 7242.9560/6527.9041 |
| 2025-05 | 7696.5683/7254.9499 | 917.6476/480.1973 | 3135.3496/2249.3364 |
| 2025-06 | -1972.7885/-2274.4070 | -2063.8948/-2194.5532 | -500.2917/-994.4356 |
| 2025-07 | 1998.2543/1470.1622 | 10832.4712/10400.3227 | 9217.6095/8415.9296 |
| 2025-08 | 413.9499/-7.6685 | -232.3262/-278.7862 | -3045.9186/-3748.2103 |
| 2025-09 | 2496.1440/2132.9071 | 343.3507/88.7843 | 479.6567/-90.2596 |
| 2025-10 | -1238.0157/-1619.6341 | 536.4678/373.8641 | -5861.3600/-6523.0589 |
| 2025-11 | -208.6052/-228.6052 | 5.7189/-107.7599 | -105.5605/-594.9418 |
| 2025-12 | -752.6055/-854.2239 | -1006.8652/-1201.8652 | -7278.2552/-7820.6050 |

Existing whole-calendar P remains in the original baseline receipt; common-calendar P starts flat after the frozen warmup and reports any full-parent boundary differences in receipt.json.

Prior22 preserved,exactlyQ23/Q-minus24 consumed,remaining0. New validation/OOS decoded0; Break validationREJECT and G5B collector/intents/boundary retained. executionNONE/orderBLOCKED/liveBLOCKED. No paid externalAI; Gemini actualvideoNOT_RUN. Formal validation readiness staysblocked without separate authorization,unuseddata and production cost/execution lineage.
