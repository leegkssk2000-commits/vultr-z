# K126 native pullback structure failure — one pre-result follow-up

## Prior result actually consumed
The prior signal-bar close rule completed at 2026-10-21T21:10:46Z; result f7a697de16bec7ae64f36a0d5974f1cb28a201db. It reduced loss-run magnitude but damaged recovery winners and full Net. Its ALL126 changed losers saved1096.26274535 trade-bps; changed winners lost3219.85708574. This is NOT a reason to select those losses or blacklist those winners.

## Code observation
The frozen native _hg_event maintains pull_low/pull_high from EMA20 touch through the turn and emits this reference as signal.invalidation_price. The initial protective stop is that reference minus side*0.10*ATR. The single turning bar low/high need not equal the whole pullback extreme. The previous rule used only that bar. Existing prices, state machine, initial protective stop, entry, partial, feeBE,5bar scratch and25/50 extension remain unchanged.

## Source facts and limits
Al Brooks, Ask Al: Breakouts, when to exit or hold?, https://www.brookstradingcourse.com/ask-al/breakouts/ : author search-index excerpt read, direct page fetch failed in this turn. The excerpt ties trend premise to the latest breakout leg low rather than each small pullback. SEARCH_EXCERPT_ONLY, not full article read.
Al Brooks, Scale Into reversals,2014, https://www.brookstradingcourse.com/futures-market/scale-into-reversals/ : full public text sections Scale play/Turning tides read; distinguishes a protective risk stop from premise failure and gives counterexamples where a first weak adverse push recovers. This is discretionary E-mini reversal/scaling material, not a fully mechanical30m crypto recipe. No scaling, risk expansion, tick distances, stated probabilities or timing constants are imported. Already-known text is used, not counted as a novel discovery.
Adam H Grimes, The Failure Test,2014, https://www.adamhgrimes.com/failure-test-2/ : full public text read. Crossing a pivot can fail and reverse; examples can lose and gaps can exceed stop assumptions. It is countertrend material and is used as counterevidence, not a claim that this exit is profitable. Images were not separately analyzed.

## Internal hypothesis — exactly one different structural reference
On an entered long, first completed close strictly below its already frozen full-pullback invalidation_price schedules a market exit at the next actual open; short is mirrored. Mere signal-bar crossings, equality, or wicks do not qualify. Stop/gap/due exits retain priority. No new observation window, numerical cutoff, side/symbol filter, finalMFE/PnL feature, or parameter sweep. This is NOT a verbatim author rule. It changes the source of the invalidation level, not a fitted multiplier. Because original protective stops are near this structural level, there may be zero earlier exits; zero incremental opportunity is an acceptable measured outcome.

## Compare and authority
Explicit user continuation: '개선 들어가 그럼' and '이어서 해 뭐해'. One bounded exit-only candidate against retained K126, not adoption. Reproduce all126 exactly, compare ALL126 paired then native full chronological occupancy; include all recovery winners, extra/missed entries, reference cost1x/2x plus inherited carry scenario. Same usedDEV, no fresh/OOS claim, accountNAV/MTM and historicalfunding unverified. Retain K126 unless actual tradeoffs justify a separate explicitly labeled development candidate. S/C reserved comparisons untouched; orders, currentShadow and root strategy remain unchanged.
