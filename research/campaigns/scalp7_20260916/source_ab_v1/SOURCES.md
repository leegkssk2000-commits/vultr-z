# Source -> mechanism -> code binding (read before economics)

## CARTER_THRUST / official Simpler Trading educational publication
https://www.simplertrading.com/news/ttm-squeeze-explained
Section: initial thrust, article paragraphs describing four bars and exiting an unprofitable initial move (web text lines150-151).
Source-supported: the article discusses an initial move of roughly four bars, holding developing momentum, and exiting an unprofitable failed initial move. These are qualitative trading guidelines, not a verified crypto performance estimate.
Translation B: test once at the close of held30m bar4. If gross mark-to-close bps minus the same frozen round-trip reference cost is nonpositive, schedule exit at the next open. Preserve earlier stop/momentum exits and the original max hold. Do not retune bar count after results.
Code: `scalp7_source_components_v1.exit_update`; engine stop-first and next-open policies remain unchanged.

## BROOKS_SECOND_SIGNAL / author's public glossary
https://www.brookstradingcourse.com/price-action-trading-terms-glossary/
Entries: bar pullback, breakout, second entry, second signal.
Source-supported: pullback uses adverse bar movement; a second entry/signal is another attempt based on the same setup after the first attempt and subsequent pullback. The source does not prescribe this exact Squeeze combination.
Translation A: within an existing30m first-fire episode, observe pause1 -> completed close reclaim1 -> a later pause2 -> completed close reclaim2. One supplementary setup per fire. Define a pause by lower low or an inside bar; reclaim by close above prior high and own open. Require current PANIC context and positive momentum. Retain all original parent events and the original ATR/cost4 admission floor.
Stop uses the lowest observed pullback low. Gap invalidation rejects entry rather than widening this stop. A close below the fire low, a data gap, a changed segment or a new fire invalidates the episode. These exact choices are our disclosed causal operationalization, not verbatim Brooks rules.
Code: `SecondSignal.observe`, `generate_signals`, `entry_update`.

## CARTER_LIFETIME / official Simpler Trading tutorial
https://www.simplertrading.com/trading-education/tutorials/squeeze-indicator
Source-supported: first release after compression and a commonly discussed8-10bar momentum period.
Translation: supplementary sequence expires10 completed30m bars after the original fire; its holding cap uses only the remaining original11-bar implementation lifetime, not a new full lifetime. Actual new signal times remain30m; no unimplemented15m performance is claimed.

Sources describe mechanisms. Their promotional statements, testimonials and individual profits are not evidence of expected returns here. This experiment claims no independently audited success rate for any named trader. Existing cached parent costs/source contracts and all historical limitations remain in force.

Novelty review: prior Chat filters/EMA-loss exits/common-hour owner/BE1R and PR1338 three rebuilds/material round1 stay untouched. This is a source-component diagnostic with three new identities, not reopening failed material fusion or refitting an old holdout.
