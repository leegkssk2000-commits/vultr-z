# H02 benchmark application: incumbent loss-streak comparison

Completed UTC: 2026-10-21T17:24:36.406704+00:00
Disposition: REJECT_NO_JOINT_IMPROVEMENT
Incumbent retained unchanged: 308bd2deb7acaaacf1adb582206e78262d72c9d1 / K126 winner extension.

## What changed
One entry condition derived from the already-saved October18 Raschke benchmark: a completed rising ADX14>30 witness must precede the native EMA20 touch. Falling ADX during the pullback is allowed. The existing ZEL turn/next-open model, rejection reset, protective stops, partial, runner, conditional25/50bar extension and costs are unchanged. This is a source-motivated adaptation, not a source-exact reproduction of discretionary stop-entry trading.
Prepared rules and executable code were published before the run at393fdd21fc481b1ddb2589816b4af3fe6cc49760. Disabled adapter exactly reproduced all126 incumbent rows before the single enabled chronological comparison.

## Actual used-DEV result
All money columns are equal-notional summed trade-bps, NOT account percentage. Same245day used development corpus, six symbols, original365day context. No fresh/OOS claim.

|Metric|Incumbent|H02 candidate|
|---|---:|---:|
|Completed trades|126.00000000|115.00000000|
|Net1x trade-bps|7925.82228888|7257.80896668|
|Net2x trade-bps|6032.79913990|5529.71142325|
|WR1x percent|54.76190476|53.91304348|
|Maximum loss streak1x|8.00000000|9.00000000|
|Maximum loss streak2x|13.00000000|13.00000000|
|Worst losing-run sum1x trade-bps|-1128.22511669|-1236.00804818|
|Worst losing-run sum2x trade-bps|-1946.76645288|-2053.83872895|
|Realized DD1x trade-bps|1838.64200493|1865.60378700|
|Realized DD2x trade-bps|2059.60759415|2040.59229516|
|Maximum win streak1x|8.00000000|8.00000000|

At base costs: removed 4 losses, avoided 559.80386922; removed 8 wins, forgone 1398.17498395; one later newly admitted trade added 170.35779254; unchanged common-trade delta0. Net delta -668.01332219. Cost2x net delta -503.08771665. Attribution reconciles exactly.
Four large and four ordinary incumbent winners were excluded. Filtering losses did not shorten the losing run: removing winning interruptions and changing later opportunities worsened the maximum from8 to9. No numerical retuning or second run is authorized by this failed result.
Unresolved 0; boundary excluded 0. Accepted-gate event timestamps checked 258; missing native-touch timestamps in recorded gate events 0.

## Source-to-test accountability
The underlying source difference had already been recorded onOctober18; the failure was leaving it as a benchmark note instead of testing it. This comparison consumes that existing source, with the author rule, ZEL translation and actual result kept separate. The result rejects this precise adaptation on this used-DEV corpus, not all of the author’s trading approach.
Primary source: AIQ Opening Bell August1997, printed p2 rule box, author-hosted august1997.pdf. Related review: Better System Trader episode124 publisher text. The original source does not prove profitability of this ZEL variant; video views/full-transcript verification is not claimed.

## Current priority and boundaries
Preserve the positive K126 incumbent; do not replace it with this candidate. Do not repeat C1/C2/C3 or expand to C4/C5 before source-backed incumbent loss-control work. The already-prepared Squeeze signal-low loss-control comparison remains the next existing executable loss-control route under its separate reserved owner budget; retrieve completion evidence before starting anything. K follow-up must target a distinct already-observable failure mechanism and report saved losses plus lost recovery winners, not sweep ADX/cooldown/stop numbers.
Root code, master, workflows, existing B observation, fee assumptions, live/order authority unchanged. MarketAPI0, paidAPI0, orders0, deployment0. No account NAV, MTM DD, verified actual historical funding, independentOOS or production promotion demonstrated.
Artifacts: SUMMARY.json / ROWS.json.gz / CONTROL_PARITY.json / ARITHMETIC_AUDIT.json / STARTED.json / EXECUTION.log.
