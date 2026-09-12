# Squeeze/KR3 Unified execution repair — pre-outcome freeze

Issue #1292 preserves Issue #1291 candidate85/evaluation153 as `FAILED_CONSUMED` with no RAW/RESULT and no observed child economic outcome.

Only implementation repair: each symbol replay receives the exact native per-symbol cost binding `packet['costs'][symbol]`. The previous owner incorrectly supplied the whole costs map.

Scientific rules are byte-identical to the already frozen `squeeze_kr3_unified_v1.py`:
- U1 = CAPREUSE82 + C54 B lagged-ATR entry-quality component.
- U2 = CAPREUSE82 + C51 profit-zone protection on post-partial residual only.
- U3 = U1 + U2.

New actual ordinals: candidate86/evals154-155; candidate87/evals156-157; candidate88/evals158-159. Each evaluation is first-attempt/no-retry. Parent replay=0.

Selection contract is unchanged from #1291: each period requires net>0, cost2>0, PF>=1. Rank eligible children by combined two-period terminal net, then combined cost2, lower worst-period marked DD, then weighted WR. WR alone is not a hard reject. If no child beats CAPREUSE combined net, retain CAPREUSE.

Both periods are USED_DEV and formal_credit=0. Q-track/fresh/G5A/G5B, new market/OOS, paid AI, live/order/deploy are forbidden.
