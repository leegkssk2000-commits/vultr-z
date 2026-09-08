# PR1220 calendar/cache correction — two exact 2026 comparisons

Both are already-used DEV, equal-entry-notional trade-bps, not account returns or live futures proof.
Original 2025 results, failed attempts, rules, costs and native controls were not rerun or overwritten.

|2026 execution|Closed/open|Win %|Payoff|PF|Net including open mark|Cost2|4h marked DD|
|---|---:|---:|---:|---:|---:|---:|---:|
|D2 / FT2026.7|34/2|26.47|1.912|0.688|-2115.38|-2884.00|2982.91|
|HLHB / FT2026.7|25/1|60.00|0.136|0.204|-6867.00|-7634.13|8624.17|

## D2 independent engine differences
{
  "signal_differences": 0,
  "entry_differences": 0,
  "reference_differences": 0,
  "exit_differences": 4,
  "cost_differences": 0,
  "callback_errors": 0
}

Full first-difference details are in results/D2/RESULT.json.gz parity. Native timeout close versus FT next open remains explicit; no price overwrites.
Calendar repair is an integration repair, not new alpha. High win rate is not profitability. Existing G5A HOLD and all operational authorities stay unchanged.
Original signed funding, intrabar price order, live fills, margin and liquidation remain outside this offline research comparison.
Candidate count49 remains; exactly two new begun evaluations77/78. Old attempts73–76 remain intact, including failures74/76.
This report records economic work; final review/CI/merge closure is recorded separately.
