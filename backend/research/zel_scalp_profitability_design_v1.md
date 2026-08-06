# ZEL Scalp Profitability Design V1

Status: `STARTED_2026-08-06T00:44Z`
Tracking: issue #587
Authority: research-only; `execution_authority=NONE`; `order_authority=BLOCKED`; `action=hold`

## 1. Objective

Build one new Scalp/intraday candidate family from zero whose economic mechanism has a credible path to positive Net R after real BingX maker/taker fees, spread, slippage, funding, latency, partial fills and rejects. The inherited `scalp_snap` architecture is frozen as a failure benchmark; no further parameter, filter or exit refinement is allowed until this design stage is terminal.

No source, paper, video, public script or bot may claim profitability for ZEL. External material is hypothesis and architecture evidence only. Deterministic replay and sealed OOS economics remain authoritative.

## 2. Immediate work packages

### WP-A — inherited architecture autopsy
- resolve the exact active/canonical source owner and source SHA;
- enumerate entry, exit, sizing, order and risk rules;
- classify each rule as evidence-backed, empirically supported, unsupported/post-hoc or structurally harmful;
- attribute failure to gross-edge absence, turnover/cost burden, holding-horizon mismatch, adverse selection, entry weakness, exit truncation, market-order dependence, regime/symbol concentration or data-resolution mismatch;
- bind PR #576 terminal Gen3 artifact as failure evidence only.

### WP-B — external architecture benchmark
For every source record: source type, URL/identifier, access date, claimed edge, market/timeframe, entry, exit, regime filter, order type, execution assumptions, risk controls, reported performance, reproducibility, failure modes and transferable design elements.

Initial source sweep started:

| source | class | immediately transferable architecture evidence | trust disposition |
|---|---|---|---|
| https://www.freqtrade.io/en/stable/hyperopt/ | official framework | bounded parameter spaces, guard/trigger distinction, multi-objective loss, trade-count penalties | architecture evidence; not profitability evidence |
| https://www.freqtrade.io/en/latest/backtesting/ | official framework | explicit round-trip fee injection and trade export | execution-validation evidence |
| https://hummingbot.org/strategies/v2-strategies/controllers/ | official framework | MarketDataProvider using OrderBook/Trades/Candles; Controllers + Executors separation; directional/MM/arbitrage families | production architecture evidence |
| https://hummingbot.org/strategies/ | official framework | per-tick data collection, processing and order execution; multi-controller routing | production architecture evidence |
| https://nautilustrader.io/docs/nightly/concepts/backtesting/ | official framework | backtest/live shared engines, execution algorithms and event-driven data stream | high-value parity evidence |
| https://www.quantconnect.com/docs/v1/algorithm-reference/trading-and-orders | official framework | pluggable fill, fee, slippage and margin models; high-resolution data requirement | execution-model evidence |
| https://docs.jesse.trade/docs/research/optimize | official framework | train/test split plus Monte Carlo follow-up | robustness evidence |
| https://github.com/enarjord/passivbot/wiki/Overview | official project | perpetual grid/martingale architecture | tail-risk counterexample; core edge rejected |
| https://www.tradingview.com/script/gp332Dao-Scalping-Support-Resistance-Strategy/ | open community script | simple breakout + explicit TP/SL; high public engagement | hypothesis only; metrics untrusted |
| https://www.tradingview.com/script/YgRqvCGx-Swing-Scalper-HULL-T3-avg-Crypto-Strategy/ | open community script | trend direction + reversal/TP/SL exit | hypothesis only; metrics untrusted |
| https://www.reddit.com/r/algotrading/comments/1e40bak/to_people_currently_running_a_live_strategy_whats/ | practitioner discussion | monitor live-vs-theoretical return distribution, liquidity and slippage degradation | anecdotal operational evidence |

Pending mandatory sweep: YouTube technical implementations with view snapshots; r/algotrading/r/algotradingcrypto failure reports; TradingView open-source scripts; QuantConnect strategy library; Freqtrade strategy repos; Hummingbot controllers; NautilusTrader examples; Jesse strategies; OctoBot; open GitHub bot implementations.

### WP-C — architecture comparison matrix
Score each archetype on causal edge clarity, BingX feasibility, data availability, cost margin, holding horizon, execution risk, sample capacity, overfit risk, tail risk and expected Net R/day.

Required archetypes:
1. momentum breakout/continuation;
2. pullback/reclaim;
3. mean reversion/liquidity sweep;
4. order-flow imbalance/microprice;
5. maker spread capture/market making;
6. cross-venue or spot-perp basis/arbitrage;
7. volatility expansion;
8. session/event-driven scalp;
9. hybrid regime router.

Hard exclusions:
- martingale/DCA as core edge;
- strategies whose gross expected move does not materially exceed all-in cost;
- unmodelled market-order dependence;
- public-script parameter copying;
- same-data design and validation;
- trade-starvation disguised as improvement.

### WP-D — BingX feasibility gate
Determine whether ZEL can obtain and preserve sufficient historical and forward evidence for:
- trades/aggressor flow;
- L1/L2 book snapshots and depth;
- spread, microprice and imbalance;
- maker/taker classification;
- queue/fill probability and partial fills;
- account-specific latency, rejects and realized slippage.

Routing rule:
- sufficient event-time book/trade/latency data -> permit `scalp_microstructure_v1`;
- insufficient data -> route to a 3m/5m/15m intraday design whose expected move exceeds all-in cost; do not tune candle-only 1m pseudo-HFT.

### WP-E — sealed design selection
No strategy code before a machine-verifiable design receipt contains:
- selected archetype and rejected alternatives;
- causal/economic edge hypothesis;
- market, symbols, timeframe and expected holding horizon;
- decision-time feature set;
- explicit maker/taker and order lifecycle;
- realistic fee/spread/slippage/funding/latency assumptions;
- stop, target, timeout and sizing contract;
- bounded coarse-search variables;
- falsification criteria;
- research/W1/W2/W3/final-holdout SHA boundaries;
- trial budget and multiple-testing accounting.

### WP-F — implementation and economics
Implement one clean candidate family from zero. Required order:
1. static contracts and deterministic fixtures;
2. research-data coarse test;
3. W1 selection once;
4. freeze configuration;
5. W2/W3 unchanged;
6. adjacent-parameter stability;
7. 2x cost, P95 funding, plus-one-bar latency, gap/stale and concentration stress;
8. independent metric recomputation and A/B parity.

## 3. Acceptance gates

A research survivor requires every frozen W1/W2/W3:
- `Net_R > 0`;
- `profit_factor >= 1`;
- `expectancy_R > 0`;
- `payoff >= 1`;
- sufficient sample and retention under SSOT;
- errors, duplicates, censored opens and unknown exits = 0;
- complete per-trade source/config/data/window/cost lineage;
- no future information and no protected mutation.

A relative loss reduction remains `ECONOMIC_FAIL`.

## 4. Current next action

1. Resolve inherited `scalp_snap` source owner from branch/history/VPS receipts.
2. Complete external benchmark ledger and YouTube/community sweep.
3. Produce scored architecture matrix.
4. Run BingX data-feasibility gate.
5. Publish sealed design-selection receipt before any new replay.
