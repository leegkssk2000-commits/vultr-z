# Squeeze selected hypothesis: source-first cases

Written before new implementation tests or economic execution. Owner: Work.
Scope: G4_SCALP7_MATERIAL20_ECONOMIC_DEVELOPMENT_AFTER_PR1340_V1.
No economic probe, historical signal scan, reservation or run was performed by this author.

## Reused primary evidence

The source receipts and paragraph locations are preserved in
research/campaigns/scalp7_20260917/source_fidelity_v1/audits/POSITIVE_OTHER_SOURCES.json.
No second full audit of the 27 targets is undertaken.

- Simpler Trading, Squeeze tutorial, sections “How does the TTM Squeeze indicator work?”, “How to Read the Squeeze Indicator”, “Using the Squeeze on different time frames”: BB/KC compression release, momentum direction and timeframe interpretation. https://www.simplertrading.com/trading-education/tutorials/squeeze-indicator
- thinkorswim TTM Squeeze, “Description”: bullish momentum exit after two weakening positive histogram bars. https://toslc.thinkorswim.com/center/reference/Tech-Indicators/studies-library/T-U/TTM-Squeeze
- Al Brooks glossary, “bar pullback”, “high 1, 2, 3, or 4”: second break above a previous high after an intervening lower high. https://www.brookstradingcourse.com/price-action-trading-terms-glossary/

These primary concepts support the proposed event anatomy, not an exact platform replica.
Public prose does not establish numerical parity of the inherited histogram.
PANIC-only long context, EMA stack, cost ratio, 15m completed-bar confirmation,
fire-low invalidation, one attempt, deadlines and structural stop are disclosed
own adaptations. Combining those with High2 is a replacement architecture, not
an isolated test of timeframe and not a promise of higher profit.

## Frozen clarification before implementation

Root confirmed: retain original fire ATR20 and genuine reference cost; apply
ATR20 / actual next-open entry * 10000 / cost >= 4 at admission.
Do not add a fire-close-price eligibility threshold: the actual frozen parent
does not have that threshold in its potential-signal generator.

SQ0 inherits exact parent potential fires and original stop/fallback; execution
moves to 15m while the complete 30m momentum observations remain distinct.
SQ2 replaces immediate parent entry with four ordered later completed 15m stages:
pullback low below prior low; High1 high above prior high; later lower high;
High2 high above prior high. No bullish-close or strong-close requirement.
Every transition needs a different bar; a bar cannot cascade through stages.

SQ2 pre-entry cancellation: any completed 15m low below original fire low,
gap, new visible parent fire, completed 30m momentum <= 0, the inherited
two-positive-weakening momentum pattern, or elapsed setup time > 300 minutes.
At exactly 300 minutes a valid High2 remains eligible; at 315 it does not.
Invalidation is evaluated before a trigger on the same completed bar.
SQ2 structural stop is the lowest observed low from pullback through High2;
a next-open fill at or below it rejects, with no fallback or retry.

Position exits remain the inherited two-positive-weakening 30m momentum pattern;
the child does not add a nonpositive-momentum position exit.
Both variants expire at original fire close + 330 minutes; no child reset.
Original parent next-open entry at fire close t with 11 held 30m bars exits on
the next actual open at t + 330m. SQ0 therefore uses 22 held 15m bars.
SQ2 uses (deadline - its decision close) / 15m held bars.

## Expected cases specified before code

| Case | Hand-stated expected outcome |
|---|---|
| SOURCE_FIRST_RELEASE | Reuse parent.generate_signals, not a rewritten compression predicate; unchanged PANIC/long/MA/momentum parent eligibility. |
| HIGH2_WICK_NOT_CLOSE | Pullback, High1, lower high, then high above previous high qualifies even when final close is below prior high and below its own open. |
| HIGH2_FOUR_BARS | An outside first pullback bar cannot also be High1; no same-bar stage cascade. |
| HIGH2_INSIDEBAR_NOT_PULLBACK | Equal/higher low with inside bar alone does not start the low-below-prior-low pullback stage. |
| HIGH2_INVALIDATION_FIRST | A High2 bar that also trades below original fire low cancels without a signal. |
| HIGH2_EQUAL_FIRE_LOW | Equality with original fire low does not breach the strictly lower-low rule. |
| HIGH2_STOP | Structural stop includes all lows from initial pullback through the trigger bar; entry <= stop rejects without fallback. |
| ORIGINAL_COST | Fire ATR is carried unchanged; actual entry price drives the same ratio4 test; no extra fire-close gate. |
| NEW_FIRE | A new causal parent fire replaces an unfinished old setup; one emission at most per fire. |
| CONTEXT_AVAILABLE | No 30m context or fire is visible before its actual availability; 15m bars started before visibility cannot count retrospectively as setup. |
| GAP_RESET | Missing 15m or a segment change cancels the pending setup; no gap fill. |
| DEADLINE | Setup High2 at +300m can emit; +315m cannot. Immediate control hold22 and later High2 hold remaining bars both terminate at fire +330m. |
| MOMENTUM_DISTINCT | Repeated joined 30m endpoint on the next half bar cannot count as a new momentum observation. |
| MOMENTUM_TWO_INTERVALS | A single decrease is insufficient; endpoints 3,2,1 qualify only with last two positive and second-latest 30m open >= actual entry. |
| MOMENTUM_STRADDLE | If entry is at minute15 inside a 30m candle, that candle is not a fully post-entry weakening observation. |
| FUTURE_PREFIX | Altering later candles/context must not alter earlier generated signals or callback instructions. |
| STOP_FIRST | On a completed execution bar with both adverse stop and momentum exit, common engine executes the stop first. |
| ORIGIN_PAIRING | Both variants retain identical origin_fire_ts_ms for a shared opportunity despite different signal timestamps. |

Fixtures establish source-rule and adapter semantics only; they are not market
performance, official numeric goldens or a reason to promote a strategy.
