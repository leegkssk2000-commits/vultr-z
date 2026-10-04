# Review correction addendum — preserve the completed run

The actual20-trade result belongs to executed source994d6c5 and remains unchanged. The current wrapper is corrected and its command-line entrypoint is DISABLED: the original allowance has been consumed. Existing RUN/CONTRACT/PREEXEC receipts are not repinned. Future model execution requires a new versioned contract, not a repeat of this historical sample. CI checks the old execution adapter hashes from immutable994d6c5, and separately tests the corrected current wrapper; old frozen backend sources remain identical.

## P1 CSV parser — review4178030730

Accepted. Seed CSV now uses `float_precision="round_trip"`, matching the frozen runtime's `_history`. The old default parser and corrected parser were compared on the exact consumed input without generating signals or replaying trades. Differences occur only in seed volume: BTC112 cells, ETH86, LINK85, SOL75; DOGE/XRP0. All nonvolume seed columns, combined frames, regime columns and enriched causal features are bit-identical across6 symbols ×2353 bars. The pinned Keltner/context/execution code does not use volume. Thus this particular observed parser difference does not change the causal quantities for these saved20 trades; it is NOT a general assertion that the default parser is equivalent. The original result is not rerun or overwritten.

## P2 causal clock — review4178030733

Accepted. The original32-row witness covers only the traded symbol's current30m bar; its0.237/115.856/308.788-second min/median/max are component-delay statistics, not complete signal availability. The corrected helper conservatively includes every recorded30m input prefix through the decision across all6 symbols, including earlier delayed inputs. Seed/config realtime observation is still uncertified; even all-on-time prices return unknown, never an unprovenTrue.

On the already saved32 signals the six-symbol prefix bound is late for all32: minimum1.370s, median132.316s, maximum375.483s. This strengthens the existing NOT_REALTIME_FILLABLE conclusion; it does not change any trade or cost result. The original witness remains in its immutable result, and this correction is separate.

Five generated regressions cover the round-trip parser, another late symbol, an earlier delayed constituent, unknown seed clocks, and the disabled consumed entrypoint. Current connected tests19 PASS locally. A separate input-only script computes parser/frame/clock diagnostics; new economic replays0 and new signals0. Exact-head CI outputs and review status must be recorded separately.

## Scope of conclusions

Input transport/body integrity and a negative historical-model result are real completed work. Formal unusedOOS/fresh/account certification and the old running consumers remain unresolved. These corrections do not make the result positive or grant G5B/G6/LIVE. REPORT.md's table is preserved; read the timing figures there as traded-component values and this addendum for the conservative full-prefix correction. No past artifacts are deleted, no guard is weakened, and no parent strategy is retuned.
