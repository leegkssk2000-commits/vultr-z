# C3 source and adaptation map

Primary document: Nial Fuller, *Inside Bar Forex Trading Strategy*, 2013-11-14, https://www.learntotradethemarket.com/forex-trading-strategies/inside-bar-forex-strateg . Read on 2026-10-21; one new primary document consumed. Checked the pattern, entry, stop, continuation and timeframe sections. No external implementation or performance ledger was used. Public success language is not ZEL evidence.

The source's adverse timeframe evidence is retained in SPEC: the author discourages intraday compression. C3 is therefore an explicit, falsifiable ZEL transfer hypothesis, not source-exact replication. The exact3-hour structure classifier,15m confirmation,16bar time cap,2R target, zero tick padding and long-only direction are internal design assumptions fixed before implementation. None changes risk/promotion SSOT. No return or daily opportunity claim follows from this implementation.

Prior identity comparison, all read at `3f4a798f15fbb3a21f3f6063db1b063b95d182e0`:

| Prior identity | Evidence | Concrete difference |
|---|---|---|
| `scalp7_rider_15m_impulse_pullback_reclaim_v2` | `backend/research/rebuild/scalp7_rider_architecture_v2.py`, SHA256 `9cdd3b802559b7aadcc3e2844a4275d39fd8517d4c763b85d23d0975e4a9f79a`; `broad_rebuild_v2/SCALP7_BROAD_REBUILD_V2_FINAL_REPORT.md` R.C | Old same-TF4bar impulse/lower-low+lower-close/reclaim and swing trailing; C3 pre-mother complete-hour structure, strict inside mother, one expansion, fixed mother stop/2R/time. |
| `scalp7_break_15m_anchored_retest_reclaim_v2` | same final report B.C and `scalp7_break_architecture_v2.py` | C3 has no anchored breakout-retest episode or EMA reclaim; inside contraction itself defines frozen mother levels. |
| `scalp7_supertrend_native_impulse_pullback_30m_v2` | same final report ST.C and `scalp7_supertrend_architecture_v2.py` | C3 has no Supertrend line, direction flip or30m pullback. |
| `scalp7_squeeze_brooks_second_signal_30m_v1`, `scalp7_squeeze_brooks_carter_components_30m_v1` | `backend/research/rebuild/scalp7_source_components_v1.py`, SHA256 `68221969d913cc91d242bc5127f6a06f890d25c091fe21aec8879521982cf457` | Old inside bar is optional pause in second reclaim within a Squeeze fire with PANIC/momentum/cost guard; C3 has independent1h context and first15m mother expansion, no Squeeze origin or repeated-attempt sequence. |

The three broad rebuild failures remain failures; no old run is repeated. Keltner/HG and Squeeze controls are preserved and not relabelled as long-only. Candidate contribution on dates outside K/S remains unmeasured.

Execution uses the unchanged `backend/research/rebuild/scalp7_execution_v2.py`, SHA256 `d1461371124c2fbb3e4e9acb0afb7457fcec0b9740b908c2d98a6401bcae6cb1`. Historical availability is the existing completed-bar model, not measured network latency. Existing six-symbol price/timestamp/segment data suffice; no volume/OI/L2/tick metadata is invented. Gaps/late observations reset setup/context; entered gaps remain unresolved under common execution semantics.
