# Top5 Pre-G5 tooling #1316

## Authority
- start master: `c15bf49d283d606982b053eb2d99efcf205f3975`
- official collection scope remains Issue #1314.
- this scope does not mutate any official G5A boundary, strategy rule, cost model, formal credit, or collector state.

## Official lanes / event-rate bottleneck

| lane | official universe | cadence | bottleneck / acceleration disposition |
|---|---|---:|---|
| TrendRider Unified | BTC-USDT, ETH-USDT | 1h | only 2 symbols; only lane where a separately preregistered liquid-universe accelerator can materially expand opportunity count. Official cohort must stay untouched. |
| Keltner Reclaim | 1000PEPE/BCH/BTC/ETH/HYPE/LINK/SOL | 4h | already 7-symbol V2 universe; keep official cohort. No in-place expansion. |
| Supertrend Momentum | same frozen 7-symbol V2 universe | 4h | same. No in-place expansion. |
| Squeeze-KR3 Unified | 1000PEPE/BCH/BTC/ETH/HYPE/LINK/SOL | 4h | already 7-symbol frozen universe and per-symbol cost snapshots; keep official cohort. |
| Q0 Convex Channel Breakout | 1000PEPE/BCH/BTC/ETH/HYPE/LINK/SOL | 4h + observed 1m stop witness | event rate is not the only bottleneck; stop-witness integrity is mandatory. Keep official cohort. |

## Existing vs actual executable gaps

Already present before this successor:
- frozen Phase-1 lane boundaries and exact Top5 identities;
- individual future-only collectors/states;
- PR #1315 read-only Phase-1 status monitor;
- existing 7-symbol replacement/Squeeze/Q0 universes;
- hourly durable status persistence.

Actual executable gaps found and filled here:
1. no common finalized-CLOSED-T economic accounting owner with `net/cost2/expectancy/PF/payoff/DD/loss-tail/exposure/concentration` output and explicit WAIT_AUTHORITY behavior;
2. no generic fail-closed G5B successor template enforcing explicit same-lane G5A terminal PASS, a strictly later boundary, and zero G5A credit reuse;
3. no generic diagnostic-only G5A FAIL attribution owner using the approved categories while forbidding fresh-row candidate selection;
4. no common collector-integrity readback for stale cursor, duplicate IDs, digest drift, unknown exit, censored/open rows and source-bar gaps;
5. no reusable outcome-blind accelerator preregistration guard that guarantees a later isolated cohort and refuses PnL-directed symbol selection.

## Added tooling
- `backend/research/rebuild/top5_pre_g5_tooling_v1.py`
- `backend/tests/test_top5_pre_g5_tooling_v1.py`
- `.github/workflows/top5-pre-g5-tooling-1316.yml`

The accelerator function is a preregistration guard, not an activation. It requires a pre-boundary liquidity snapshot containing only symbol/quote-volume selection data. No outcome-aware universe was recovered from the current master, therefore no new accelerator boundary or formal cohort is opened by this PR.

## Safety / authority
- economic executions: 0
- new CLOSED T: 0
- formal G5A credit changes: 0
- G5B boundary opened: 0
- strategy/rule/source/cost mutation: 0
- paid AI: 0
- order/live/deploy: 0
- historical backfill/synthetic repair: 0

Issue #1314 scheduled collection continues independently. This successor becomes REPORT_ONLY only after focused CI, review, merge and exact-master readback.
