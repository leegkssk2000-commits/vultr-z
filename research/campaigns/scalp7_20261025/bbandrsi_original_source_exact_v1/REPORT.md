# Independent published BbandRsi 1h: source-pinned realistic spot screen

NO_ORDER, NO_NEW_FULL, USED_DEV_ONLY, FUTURES_EXECUTION_BLOCKED.

Original Freqtrade bot: https://github.com/freqtrade/freqtrade-strategies/blob/main/user_data/strategies/berlinguyinca/BbandRsi.py
Pinned original Git blob: addc87268affc2f3b1b00549f1ca8b119e41e655; source credited to Gert Wohlgemuth, converted from sthewissen/Mynt.
Native source rules: 1h TA-Lib RSI14(close) < 30 AND close below 20-hour 2-standard-deviation Bollinger lower of typical price; exit RSI14 >70. Original ROI10%, stoploss -25%.
Upstream QTPyLib Bollinger uses rolling std sample ddof=1 and min_periods=1. Replaces previous quick screen ddof=0 and unseeded EWM RSI with Wilder initial fourteen SMA gain/loss seeding.
Source signal formulas are anchored to original code. Actual TA-Lib / Freqtrade binary execution and precise ROI/stop exchange fill parity NOT installed or proven.

One existing public BingX 12x1000 1h price snapshot SHA256 16198ac2a3db7849237028a5f5a0100e2033162a9d93b05ad171273215c9a592. Last 08:00-09:00 UTC forming candle at 08:01:20 batch fetch excluded. Historical individual real received_at remains UNKNOWN.
One SPOT EQUIVALENT long sleeve/symbol: fixed notional equal weights, no leverage, no martingale or doubling, bearish stop-first including adverse gap-open, 10% ROI conservative target, RSI>70 exit at NEXT theoretical hourly open. Roundtrip model 20/40 instrument bp, actual signed funding and precise order book fill UNKNOWN.

| fee40 model | 4 core BTC/ETH/SOL/XRP | 6 target BTC/ETH/SOL/XRP/DOGE/LINK | 12 snapshot assets |
|---|---:|---:|---:|
| Completed trades | 18 | 28 | 51 |
| Still-open positions | 4 | 6 | 9 |
| Closed trade bps sum | +1627.40 | +3392.25 | +9529.68 |
| Closed PF | 1.883 | 2.078 | 2.587 |
| Final MTM including open, equal-sleeve % | +3.431 | +3.607 | +4.836 |
| MTM peak-to-trough DD % | 8.577 | 10.085 | 9.320 |

12-source original matching candle signals 296, entered 60, closed 51, still OPEN 9. Of the nine open, seven carry negative unrealized gains; sum still-open gross -3546.61bp. The earlier 52 closed model-trade result silently omitted these positions and is superseded.
For six target symbols, an additional fixed one-hour entry delay yields MTM net +4.805%, DD 9.328%; source actual historical received-at is unknown, so not execution validation.

DECISION: HISTORICAL_SPOT_SIGNAL_SCREEN_INTERESTING; FUTURES_VIRTUAL_EXECUTION_HOLD. Original price stop -25% at 10x/15x/20x implies -250%/-375%/-500% of initial risk margin before liquidation, clearly unsuitable for BingX user futures. Do NOT turn on real or paper orders. No risk threshold retuning on used Sep/Oct market.
Permissible next: one 1h SIGNAL-ONLY no-order forward observer from the already verified public 1m feed (no extra market API). Signals may be logged only at actual received-at; a late received candle cannot justify a past exact-next-open fill. Unused future source and separate risk/cost/funding economic gates needed for any executable trading.

All repo additions are self-contained within existing C research folder; no new Work or workflow. No full economic action. Source snapshot only as input, original file unchanged.

## Exact SHA256 file pins
FREEZE.json SHA256 99b17c9139e5fe4cee3412ee256ecb113ee3db880ce8d80826cbe78c2511ad8d
evaluate.py SHA256 dc222273a98f47adf758b480d5c455afbd7d4aea26c06f76b49fbb068d283891
test_evaluate.py SHA256 a0f1d7e8743f87c3363c2196f1f164df516b77b7b65535a722a2a4d1d874456b
RESULT.json SHA256 6ef13e794fd9411cc5c4b4ed0053a13ab4729d557ce659d8e81d2feeadfb7d97
coverage.py SHA256 ed935cc479acdf5da8f8303c7981acf5131722c92c1d64cf14e47e868034afb0
COVERAGE.json SHA256 9a83bbe297794e01e518a7ed935619a90081c74361b0eb3d66aa5cc046c88a95
Reproduce: python -B evaluate.py --output /tmp/bbandrsi-new-result.json ; python -B coverage.py --out /tmp/bbandrsi-new-coverage.json ; python -B -m unittest discover -s . -p test_*.py
