# Q0 loss-run diagnosis: source-to-rule boundary

This note supports one bounded Q2 decision. It does not allocate another hypothesis, report new strategy economics, or change Q0/Q1 decisions. Q0 remains the PR #1190 research reference; Q1 remains PR #1191 DEV_REJECT.

## Primary source actually read

[Hudson & Urquhart, Technical trading and cryptocurrencies](https://link.springer.com/article/10.1007/s10479-019-03357-1), Annals of Operations Research 297, 191–220; [published PDF](https://link.springer.com/content/pdf/10.1007/s10479-019-03357-1.pdf). The existing full PDF was re-read and its SHA256 is `04e9ae429b3a32cb835d29a12ce8e4b29048f54fd156adca2b5d3f3c2e405e6b`. The publisher HTML was also opened during this task. No author contact, paid model call, or video request was made.

| Source fact, paraphrased | Exact printed / PDF location |
|---|---|
| Daily Bitcoin (CoinDesk/Bitstamp), Litecoin, Ripple and Ethereum; initial samples end December 2017. | §2 pp.195–196 / PDF 5–6 |
| Prior-close information determines subsequent-period long, short or cash returns. | §4, Eq.2 p.197 / PDF 7 |
| Channel readiness requires earlier prices to lie within a percentage range. Bounds derive from previous low/high; a breach must persist for `d` periods. | Appendix §5 pp.217–218 / PDF 27–28 |
| CB1 gives opposite directional entries; CB2 adds a fixed holding period. Executable stop/cancellation/reentry details are incomplete. | Appendix §5 p.218 / PDF 28 |
| Support/resistance uses previous closing-price extrema as barriers. | Appendix §3 pp.216–217 / PDF 26–27 |
| Family profitability and breakeven costs do not isolate a particular whipsaw remedy. Selected Bitcoin rules subsequently lost out of sample. | §6.1–6.2, Table6 p.210; §6.5, Table9 pp.212–213 |
| Printed parameter/count conflicts remain. | Appendix pp.216–218; Table9 p.213 |

The source does not prove a profitable Q2 filter, causal losing-run mechanism, or current ZEL economics. Q0's performance is its own ledger evidence. The original paper's selected best parameters are not copied. The previous source note's abbreviated cost locator is clarified: §6.2 starts p.205 and continues on pp.210–211; pp.208–209 contain Table5. Its earlier OOS locator correction to §6.5 remains valid. Old files are preserved byte for byte.

## Existing ZEL choices, not author rules

`BREAK_CHANNEL_SOURCE_20260906_V1/SPEC.json` and `SOURCE_AND_SPEC.md` already fix Q0's daily two-close channel, latched bounds, two-close confirmation, cancellation, next-open long/cash execution, initial protective lower stop, cost/funding authority, and terminal treatment. `break_channel_structure_v1.channel()` and `generate_signals()` implement those choices. In particular, DOWN exit confirmation has no preparation requirement; this is a ZEL exit assumption.

The source's barrier interpretation can motivate observing whether a new prepared breakout has made structural progress. It does not prescribe any of the following diagnostic definitions: reclaiming the latest DOWN upper bound; advancing above the previous prepared-UP upper bound; or requiring a stopped position's old upper bound to be surpassed. These are distinct ZEL causal questions. A useful empirical split must be identified from pre-loss observables before choosing one rule; source terminology alone cannot justify implementation.

The current diagnostic uses only original bands and completed confirmations. A last-DOWN barrier must have existed before the new UP decision. A prior-UP barrier must exclude the current UP event. A prior stopped-position condition must use an already completed stop, never a later stop or a final run label. End-of-run dates, realized future profit, eventual maxima/minima and hindsight market labels may annotate analysis only.

## Current-data evidence and bounded conclusion

The independently produced occurrence analysis covers all 102 original eligible UP signals, including 86 completed Q0 trades and 16 ownership exclusions. These are observations of the unchanged Q0 ledger; no vetoed-trade PnL, candidate equity curve or Q2 replay was calculated by this source task. Outcome groups annotate the diagnostic and cannot become execution features.

| Pre-loss observable | Q0 losses: true / all | Q0 wins: true / all | Top three Q0 winners: true / all | Consequence for the proposed source-to-rule link |
|---|---:|---:|---:|---|
| Last confirmed DOWN upper still unreclaimed at the current UP confirmation | 9/57 | 6/29 | 3/3 | It occurs more often among wins and marks every largest winner; the barrier story does not distinguish the targeted losses. |
| New prepared-UP upper is no higher than the previous prepared-UP upper | 27/57 | 13/29 | 1/3 | Worst-run concentration does not persist in other periods; no general loss-state separation. Two loss observations have no previous comparable UP. |
| Previous position stopped, with current upper no higher than its original upper | 12/57 | 7/29 | 1/3 | It occurs more often among wins; reentry failure is not established by this condition. Six losses and one win have no comparable completed prior position. |

Denominators retain unknown observations instead of quietly treating them as known false. For the successive-UP condition, loss/win occurrences are 7/21 versus 4/11 in 2025Q2, 3/10 versus 5/14 in 2025Q3, and 9/12 versus 4/4 in 2025Q4. 2025Q1 has 14 losses and no wins, so it cannot establish within-period separation. For unreclaimed DOWN upper, 2025Q2's 3/21 losses versus 0/11 wins reverses to 3/10 versus 5/14 in 2025Q3 and 1/12 versus 1/4 in 2025Q4. The stopped-position condition is also more common among wins in all three quarters with wins. Calendar slices are assigned by original signal time, cover reused DEV, and are not independent OOS.

Thus these three source-native observations do **not** justify a Q2 rule. No source can turn their failed discrimination into current empirical evidence. This conclusion is limited to these stated interventions; it is not a claim that Q0 or all channel improvements are impossible. No threshold, lookback, waiting period, extra indicator, or replacement candidate is inferred after seeing these observations.

Reproducible repository evidence is recorded in this directory: `OBSERVABILITY.json.gz`, `LOSS_RUNS.json.gz`, and `analysis.json`. The latter records source-note, code, parent and artifact hashes. Mutable scratch snapshots are not authoritative outputs.

No broad source catalogue or indicator sweep is needed for these source-native structural questions. An additional primary source would be warranted only if the diagnosed intervention cannot be stated honestly as an explicit ZEL prior using the existing source and data. Publication titles, indicator formulae and paper-level success do not fill missing current-data discrimination.

Gemini actual video execution: **NOT_RUN**. There is no new run ID or timestamped extraction evidence. New paid external AI calls: **0**. Existing Top5/G5B and execution/order/live boundaries remain outside this note's scope.
