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
