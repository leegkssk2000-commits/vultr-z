# TPC1 entry quality diagnostic — S1

TPC1 FULL remains the exact parent: BTC/ETH native 1h, reused DEV calendar 1734595200000–1766995200000. Existing verified totals are reused: 406 completed, 110 wins, 296 losses, 288 initial SL, six other price losses and two cost sign flips. No economic path or old candidate was replayed.

## Completed-close loss attribution

| Strictly before the SL bar | SL count |
|---|---:|
| Completed close exceeded contemporaneous modeled full roundtrip cost, then initial SL | 159 |
| Some positive completed close, never above modeled cost | 49 |
| No positive completed close | 65 |
| No completed held bar: first-bar SL, intrabar path UNKNOWN | 15 |

Cost hurdle at every observed close is max(20 bps, frozen full roundtrip fee/spread/impact plus modeled accrued absolute funding at that close). No exit-bar H/L/C or final MFE enters reconstruction. Thus 159, not stored MFE-positive 294, is the supported count of above-cost completed-close progression before SL. The 65 are close-observed adverse paths, not proof that every intrabar move was adverse. These labels attribute path behavior; they do not identify a unique causal failure mechanism or justify widening SL.

## Entry-state overlap and counterexamples

| Signal-close state | Completed | Loss | Ordinary win | Large win | Late recovery win |
|---|---:|---:|---:|---:|---:|
| Current signed candle body < 0 | 123 | 96 | 24 | 3 | 5 |
| Current signed candle body >= 0 | 283 | 200 | 75 | 8 | 28 |
| First actual attempt in current native ST direction episode | 296 | 219 | 68 | 9 | 19 |
| Same-direction attempt after previous completed SL, same episode | 83 | 55 | 26 | 2 | 13 |
| Same-direction attempt after other completed exit, same episode | 27 | 22 | 5 | 0 | 1 |

Large means the unchanged sprint diagnostic definition: top ceil(10% of positive completed winners), hence 11. Late recovery means first completed held close <= entry gross, followed by a later completed close above its contemporaneous cost hurdle; 33 winners meet this definition, including three large winners. These future path labels are never entry features. No elapsed-bar cutoff is inferred.

All 406 entries already satisfy native direction/line/EMA/slope confirmation and exact native transition freshness policy; adding the same test would be redundant. Median ST episode age is 17.5 bars for losses, 18 for ordinary wins and 13 for large wins. Median native ST distance is 2.857, 2.871 and 2.964 ATR respectively. These descriptive locations overlap; they supply no natural new cutoff. Prior SL does not separate losses: its 28/83 wins include two large wins, contradicting blanket repeated-attempt suppression.

The 1,555 raw signals contain 743 adverse-body signals, while the 406 owned entries contain only 123. The other 1,149 signals retain outcome UNKNOWN. Raw-signal and admitted-entry proportions show selection by position ownership/cooldown and must not be converted to raw-signal win rates. Exact regenerated native intent parity passes for BTC 762 and ETH 793.

## One bounded hypothesis for root review

At the original signal close, reject an otherwise eligible TPC1 Primary entry iff sign * (signal close - signal open) < 0; allow flat or aligned bodies. Entry eligibility is the sole changed axis. The original next-open execution, SL, TP, cost, protection, extension and cooldown remain unchanged. This natural zero-state hypothesis was written in DIAGNOSTIC_FREEZE.json before the feature pass. No parameter sweep or new-PnL comparison selected it.

The mechanism is current-bar rejection after the parent only checked the previous candle's direction. Its stored conditional group contains 83/283 wins (29.3286%) versus parent's 110/406 (27.0936%); this is an observational diagnostic, not a candidate FULL result. A veto would omit 96 stored losses and 27 stored winners, including 3/11 large winners and five late recoveries. Winner capture is 83/110 = 75.4545%. These are material counterexamples; the hypothesis is not an adoption recommendation and its incremental economics are unmeasured.

Prior-known evidence is explicitly inherited: backend/research/rebuild/top5_development_repair_v1.py already diagnoses directional_body_positive. The rejected Primary precision_prior_extreme_v1 in TOP5_DEV_REPAIR_20260905_V1/research_registry.json demands close at/beyond the previous high/low. Both address local continuation. Current-body sign is logically distinct (an aligned candle may remain inside the prior range), but it is related, previously diagnosed evidence, not a novel independent discovery. S4 independently confirms causal availability and semantic distinction, with the same missed-winner counterexamples; root owns candidate selection.

P/TPR1/TPP1 economic values are copied from the existing stored artifact in SUMMARY.json. Broad remains a separate lane using the common native SL-path interpretation only; no duplicate Broad path was computed. KR3/Break/Q0 and all other Work were untouched. 2026 native1h remains NOT_RUN for the known unavailable period.

## Verification and stop

Three narrow synthetic tests pass: arbitrary future append leaves past entry state unchanged; an unreadable exit-bar sentinel is never accessed during completed-close attribution; a first-bar SL remains UNKNOWN. Future previous-outcome input is rejected. Native BTC/ETH and manifest SHA values match the user's V5 attachment once; exact original policy raw-tape parity passes. This role used two feature-only symbol passes, zero economic replays, zero candidate executions, zero paid API calls and zero parameter sweeps. S1 stops after this handoff. SUMMARY.json and DIAGNOSTIC_FREEZE.json are stable for the S3 source allowlist.
