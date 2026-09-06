# Supertrend A/B: measured ZEL DEV adaptations

A replaces the impulse trigger by official down-to-up flips and retains hold12. B uses the same flips and exits at the next open after the first opposite flip, long/flat only. Source-complete replication is not claimed.

Prior20 applications preserved;A ordinal21 and B ordinal22 consume exactly2. Reproduction is not another hypothesis. All values are equal-notional modeled trade-bps,not account returns.

| Stage | Closed / open T | Gross E | Net E | PF | Payoff | Cost2 E | Closed net sum | Closed loss-run | Total exposure days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P | 243 / 0 | -1.5120 | -22.8509 | 0.9064 | 1.1714 | -44.1899 | -5552.7777 | 4456.3242 | 486.0000 |
| A | 164 / 0 | -60.9121 | -82.4802 | 0.7205 | 0.9920 | -104.0483 | -13526.7473 | 8535.2629 | 328.0000 |
| B | 161 / 3 | -0.3619 | -38.5553 | 0.9111 | 2.0226 | -76.7487 | -6207.4030 | 18816.7405 | 1095.0000 |
| B_FIXED_A | 161 / 3 | -0.3619 | -38.5553 | 0.9111 | 2.0226 | -76.7487 | -6207.4030 | 18816.7405 | 1095.0000 |

Closed E/PF/payoff and loss-run exclude open marks. Exposure includes censored holding. B_FIXED_A is an independent-position diagnostic,not a deployable portfolio.

| Comparison | Overall / closed screen | Closed delta | Common closed / censored | Unfilled / new closed / new open | Winner amount bounds | Large winner bounds | Delta E95% |
|---|---|---:|---|---|---|---|---|
| P_to_A | DEV_REJECT / DEV_REJECT | -7973.9697 | 11 / 0 | 232 / 153 / 0 | [0.08479319613051797, 0.08479319613051797] | [0.08013587801296976, 0.08013587801296976] | [-194.20528082984762, 86.62227397533377] |
| A_to_B | DEV_INCONCLUSIVE / DEV_REJECT | 7319.3443 | 161 / 3 | 0 / 0 / 0 | [0.47986044591503474, 0.4826316855438822] | [0.6224314732766132, 0.6224314732766132] | [-245.0703508051613, 436.75615416586544] |
| P_to_B | DEV_INCONCLUSIVE / DEV_REJECT | -654.6253 | 11 / 0 | 232 / 150 / 3 | [0.05503282107452482, 0.05503282107452482] | [0.06499586785085247, 0.06499586785085247] | [-345.5004209726966, 435.1678163704292] |
| A_to_B_FIXED | DEV_INCONCLUSIVE / DEV_REJECT | 7319.3443 | 161 / 3 | 0 / 0 / 0 | [0.47986044591503474, 0.4826316855438822] | [0.6224314732766132, 0.6224314732766132] | [-245.0703508051613, 436.75615416586544] |

## Unclosed observations: no fabricated liquidation

| Stage | Open T | Gross mark | Modeled funding accrued | Hypothetical roundtrip liquidation cost | Hypothetical net mark | Cost2 hypothetical net mark | Open exposure days |
|---|---:|---:|---:|---:|---:|---:|---:|
| B | 3 | 506.8025 | 74.5800 | 116.6822 | 390.1203 | 273.4381 | 14.3333 |
| B_FIXED_A | 3 | 506.8025 | 74.5800 | 116.6822 | 390.1203 | 273.4381 | 14.3333 |

Entry-side fee/spread/impact is NOT_SEPARATELY_BOUND by the roundtrip model. Hypothetical liquidation cost includes the full frozen cost/floor; it is not accrued cost or a realized exit. Winner retention bounds concern capped original profit,not total future PnL.

Source-trigger overlap is exact signal-time coincidence only. P→A and P→B are full mechanism comparisons. A→B isolates holding/exit on fixed A origins plus a separate full ownership replay. Paired-completer metrics are in receipt.json; unresolved A origins remain visible.

Weekly bootstrap is closed-only and entry-week clustered;it does not adjust for censoring or long holding dependence. ExistingDEV reuse and prior20 trials remain recorded. No independent significance, operating adoption, validation/OOS, G5B change or live authority is created.

See receipt.json for source admission,events,all three decompositions,fees/funding,risk diagnostics,per-symbol metrics and immutable hashes. New paid externalAI0;actual Gemini video NOT_RUN.
