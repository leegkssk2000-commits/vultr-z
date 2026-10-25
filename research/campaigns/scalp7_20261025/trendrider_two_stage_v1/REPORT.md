# TrendRider: two stages of winner retention and loss control — 2026-10-25

Status: USED-DEV RESEARCH. Frozen before the new source-bar read, original 368 price entries/exits independently matched, no new strategy identity, Work, order, economic FULL, or production guard change.

## The two candidates are not independent

Liquid6 is original 1h TrendRider first-confirmation LONG, 6 liquid symbols, with fixed one-third total risk unit and losing-basket admission guard. Delayed Fill is original 1h TrendRider one-bar delayed LONG, 12 symbols. Original saved symbol+side+signal matching keys: **97/119** Liquid6 rows = 81.5%, 1,427 paired overlapping positions (118 same-symbol). They share a parent alpha mechanism. K117 is separate 30m Keltner/HG and was not replayed.

## Fixed stages (NO parameter sweep)

- Stage1: TIMEOUT-only winner continuation if already +1 original stop-price-R AND completed timeout close > rising EMA20. Extend up to 12 additional closed1h bars. Stop-first: lagged highwater-1.25R or entry+0.5R whichever is greater, retaining native stop as floor; gap adverse at actual open. Updates never use current candle high before current candle low/stop. Native same-symbol cooldown2h maintained. Extra holding carry = modelled 5 instrument bps per commenced8h, including Liquid6 portfolio unit scale.
- Stage2: if two previous trade cost2 losses are both known closed (exit +1h strict) inside24h and latest inside12h at next entry, reduce the original exposure 25%, preserve remaining 75%. No skip, recovery multiplier, price-signals added, or capital NAV inference.
- Cost models 1x and 2x use original native per-trade estimated fee/impact/funding field, not blanket fixed 20/40bp and not real broker funding confirmation.

## Liquid6, unchanged 119 original saved opportunities

| Stage | T | Net2 summed trade-bps | PF2 | DD2 exit-cohort trade-bps | Max loss streak |
|---|---:|---:|---:|---:|---:|
| Original | 119 | -322.66 | 0.929 | 3417.65 | 22 |
| Stage1 | 112 | +32.09 | 1.008 | 3326.60 | 22 |
| Stage2 | 119 | +61.13 | 1.015 | 2984.55 | 22 |
| Stage1+2 | 112 | +392.87 | 1.107 | 2873.75 | 22 |

Stage1 extends 20 native timeout positions, blocks 7 future saved opportunities due new holding overlap. Stage2 reduces 53 trade risk units, 47 losing and 6 winning. Combined vs original improves Net2 **+715.52bp** and DD2 **-543.89bp**, but October Net2 remains **-1850.74bp**; total net without top 2 winning trades **-572.34bp**; leave-one-DOGE-out combined Net2 **-6.35bp**. No formal H4/H5 or production credit. Candidate may only be considered for NEW forward freeze.

## Delayed LONG, four pre-existing invalid native stop geometries

The original saved 249 trade rows include **4 LONG entries with entry <= sealed initial stop**; these have no positive price-R. The saved simulator also booked a non-conservative stop-price fill although the bar opened below that stop. Adverse gap-open correction of those 4 reduces booked gross by **149.77 instrument trade-bps**. Preserve original raw 249 record and explicitly segregate a *245 valid-entry-geometry* diagnostic cohort, not a new learned parameter filter.

| Stage valid-entry cohort | T | Net2 summed trade-bps | PF2 | DD2 exit-cohort trade-bps | Max loss streak |
|---|---:|---:|---:|---:|---:|
| Valid geometry reference | 245 | +1545.16 | 1.044 | 21713.49 | 40 |
| Stage1 | 223 | +3846.40 | 1.123 | 19615.41 | 37 |
| Stage2 | 245 | +1237.68 | 1.041 | 18517.92 | 40 |

Stage1 extends 41 old TIMEOUT positions, excludes 22 later saved entries, raises net2 **+2301.25bp** vs 245 valid-entry reference, but October is still **-14550bp** and net excluding top2 winners **-1068.02bp**. Stage2 lowers realized DD but **reduces Net2 by 307.48bp** with weaker PF: REJECT that stage2, no retune.

## Reproduction and limitations

- One-time original public BingX 1h snapshot: 12 symbols x 1000 continuous hourly OHLC bars, source hashes and all 368 original stop/timeout price parity checks in RESULT. No new collector; 12 public read requests, orders0.
- Liquid6 receipt frozen at Git commit 76f7ec69e1789126114b8bfbdcd6c55d3f640c3b, original 119 trades. Delayed source is successful saved GitHub Actions run https://github.com/leegkssk2000-commits/vultr-z/actions/runs/40146310229, pinned 249 trades. Do not blend an evolving newer 248-trade master observer into this cohort.
- Actual received-at of historic bars, actual funding, account NAV, liquidation buffer and execution gaps remain unverified. Simulating new longer holding may block saved later candidates but CANNOT generate all hypothetical newly freed signals. Not full native causal owner reconciliation; no guaranteed 1-to-1 real order fill.
- Source rule, source artifact, Python algorithms, adversarial tests, all per-symbol input SHA, original and altered economics, duplicate proof, per-month losses, leave-one-symbol stress and counterexample trace preserved in this folder.
- G5 / H4 negative control / H5 concentration / PREAUTO remain blocked. Trading action HOLD. No retrospective reoptimization and no new strategy or Work.


## Cryptographic receipt pins

- FREEZE.json: SHA256 b062cd926ac2b727ecfca435a3c52b9af9362241058a4da9b4540c76b580dbf0
- MARKET_1H_SNAPSHOT.json.gz: SHA256 16198ac2a3db7849237028a5f5a0100e2033162a9d93b05ad171273215c9a592
- delayed_prospective_40146310229.zip: SHA256 4ab634d853314d8427404d0ca722b6ce52d4d1f1561a68041ced0eff0d70d2e7
- RESULT.json: SHA256 41c6386859158b5ddaf8a4785917cf4984c54f4362ae4899312e5bca4b7fb6bb
- ROBUSTNESS.json: SHA256 4156b919216b328d279ca5152179581155445bb217cf19744f3d65c140bdb6bf
- stages.py: SHA256 53e43ff24b6c72f53f8ed38c305675063f71c98f52f65cea9e4aeb0b1925cae2
- robustness.py: SHA256 cb2fd6b7ec791f9c2f00158ff74ac05e6555a694a5fd9bb0c36a50355e57e740
- test_stages.py: SHA256 a765ccf528cd989a6daf7fdd724362edb99214a90b4f8ddbbb7275dea23d869c

Underlying Liquid6 original JSON: SHA256 ec542bb59161550a2c314c6f352493f88509b0df3b739448c8b3b3a169821938
Underlying Delayed saved artifact internal JSON: SHA256 85f417400887f85e57550561a5f0c4d1f34cb366c3929e25de5224cc826eb455
