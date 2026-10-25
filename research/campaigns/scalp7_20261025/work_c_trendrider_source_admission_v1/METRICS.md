# Saved evidence accounting — not new economic validation

All bps are sums of saved trade bps with the original 1/3 notional weight already applied. They are not account NAV returns. Gross/Cost/Net1/Net2 and group sums were reconciled from sealed legs. PF2, WR2, DD, streak and original-long-risk R are copied from the historical result. Clock/fill defects remain unresolved.

T counts accepted opportunities; legs include reversal shorts. DD is saved realized exit-leg DD, not marked account equity DD. T/day is NULL: no admissible fixed calendar window/last-bar closure is established. No window is inferred from trade outcomes.

| Row | T / legs | T/day | Gross | Cost1 | Net1 | Net2 | PF2 | WR2% | DD2 | Max loss streak | Worst R | Max R | Net2 ex top2 | Added vs S0 | Excluded vs S0 | Missed original winners |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| S0 | 153/153 | NULL | 780.902839 | 893.086592 | -112.183753 | -1005.270344 | 0.861783 | 22.222222 | 4575.807608 | 32 | -17.410986 | 9.416637 | -2460.328394 | 0 | 0 | 0 |
| S1 | 144/144 | NULL | 1691.935150 | 919.527076 | 772.408074 | -147.119002 | 0.978113 | 24.305556 | 3901.503174 | 30 | -17.410986 | 23.814218 | -1530.351646 | 7 | 16 | 2 |
| S2 | 157/157 | NULL | 296.364259 | 984.101734 | -687.737475 | -1671.839209 | 0.765754 | 19.745223 | 4884.415497 | 31 | -17.410986 | 23.814218 | -2589.428874 | 21 | 17 | 2 |
| S3 | 138/218 | NULL | 2641.979323 | 1623.795738 | 1018.183585 | -605.612152 | 0.925350 | 30.434783 | 4285.937366 | 20 | -107.272668 | 23.814218 | -2199.534439 | 32 | 47 | 8 |
| S4 | 121/192 | NULL | 4622.262895 | 1434.891293 | 3187.371602 | 1752.480309 | 1.294173 | 37.190083 | 2225.861306 | 14 | -107.272668 | 23.814218 | 369.247664 | 28 | 60 | 10 |
| S4_PR1471_FAILED_FILTER_SAVED | 118/182 | NULL | NULL | NULL | NULL | 1107.459111 | 1.183319 | 37.288136 | 2623.503543 | 14 | -4.945890 | 9.887428 | -275.773533 | NULL | NULL | NULL |
| S4_REALISTIC_NEW_SOURCE | NULL/NULL | NULL | NULL | NULL | NULL | NULL | NULL | NULL | NULL | NULL | NULL | NULL | NULL | NULL | NULL | NULL |

The failed PR1471 filter has no sealed leg artifact in these inputs, so Gross/Cost1/Net1 and symbol contributions stay NULL. Its rejection is preserved. New realistic-source S4 metrics are all NOT_RUN/NULL. R uses the old long-stop denominator and is not executable capital-at-risk; S4 worst −107.27R is retained as a counterexample.

S4 vs S0: 93 common admissions lose 270.273019 bps in aggregate; 28 entries are added and 60 excluded. Ten excluded original winners total 953.054805 bps. These are retrospective descriptions, never execution filters.

## Signal-month Net2 (UTC)

| Month | S0 | S1 | S2 | S3 | S4 | Failed PR1471 | New realistic S4 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-09 | 2077.625594 | 2164.455361 | 943.189383 | 711.803842 | 1652.561768 | 1652.561768 | NULL |
| 2026-10 | -3082.895938 | -2311.574363 | -2615.028592 | -1317.415994 | 99.918541 | -545.102656 | NULL |

These are signal-cohort months, not cash realization months.

## Symbol Net2 (saved admitted contributions)

| Symbol | S0 | S1 | S2 | S3 | S4 |
|---|---:|---:|---:|---:|---:|
| 1000PEPE-USDT | 918.046615 | 645.370994 | 582.646662 | 1130.963306 | 989.153380 |
| 1INCH-USDT | -149.845954 | -46.382146 | 22.590278 | -769.428853 | -621.414362 |
| APE-USDT | -72.624401 | 221.632918 | 322.437798 | 836.917658 | 906.684797 |
| BCH-USDT | 1037.377747 | 1034.792002 | -430.883677 | 509.559216 | 922.140195 |
| BTC-USDT | 18.736856 | 55.029932 | 49.342254 | 59.461121 | 93.017657 |
| DOGE-USDT | -368.014539 | -406.486625 | -408.935655 | -457.841784 | -420.125317 |
| ETH-USDT | -346.302004 | -263.650951 | -224.832836 | -267.035260 | -233.881236 |
| ETHFI-USDT | -1360.452015 | -1192.379721 | -1133.133455 | -597.363390 | 361.694670 |
| HYPE-USDT | -178.668768 | -185.856020 | -188.697247 | -790.235411 | -598.073415 |
| LINK-USDT | -269.940338 | -389.555474 | -421.761538 | -226.519335 | 34.755032 |
| SOL-USDT | 196.465765 | 314.043206 | 208.323400 | 614.221411 | 752.142142 |
| XRP-USDT | -430.049307 | 66.322882 | -48.935193 | -648.310832 | -433.613235 |

Symbol contributions are not leave-one-symbol-out replay results; removing a symbol changes occupancy and admissions. All 12 symbols, including BCH and 1000PEPE, are retained.

## Preserved mandatory stress counterexamples

| Saved scenario | T | Net2 | PF2 | DD2 | Loss streak | Top2-excluded Net2 | Disposition |
|---|---:|---:|---:|---:|---:|---:|---|
| S4 +40 instrument bp all legs | 121 | -807.519691 | 0.895491 | 3692.661351 | 14 | -2164.085669 | FAIL |
| S4 short +1h | 118 | 236.835957 | 1.036712 | 3606.670449 | 9 | -1163.907064 | HOLD: October and ex-top2 negative |
| Saved ablation: no short | 127 | -176.834412 | 0.968814 | 3671.921745 | 28 | -1560.067057 | old negative control only |
| Saved ablation: no early bailout | 121 | -695.927424 | 0.893734 | 3597.148541 | 23 | -2073.420032 | old negative control only |
| Exclude 1000PEPE | 115 | -752.270814 | 0.884118 | 3634.407567 | 15 | NULL | FAIL |
| H4 preregistered placebo | NULL | NULL | NULL | NULL | NULL | NULL | BLOCKED: no fresh eligible witness |
| Unused OOS | NULL | NULL | NULL | NULL | NULL | NULL | BLOCKED: no input |

+40bp is the original frozen stress: an additional 40 instrument bps once per long/short leg, then the saved 1/3 weight (192 × 40/3 = 2560 bps total deduction). It is not a claim that actual exchange round-trip cost is 40bp, and it is not doubled a second time. The +1h row has October −1168.504213 bps and top2-excluded −1163.907064 bps despite positive total Net2. These saved tests were not rerun.
