# Work B — isolated orderless development observations

Scope: Issue #1334 comment 6236661922 and the uploaded Work B instruction.
PR #1449 was merged at `7e229bd37c7df7ba8b99a424cb67d84e0074e4e2`.
Implementation: PR #1450, branch `research/work-b-orderless-shadow-20261018`.
Work B is not the economic coordinator. A keeps economic comparison and integration ownership.

The two existing families retain four separate version ledgers:

| Family | Existing version |
| --- | --- |
| Keltner/HG | `scalp7_keltner_hg_parent_utc30m_v2` |
| Keltner/HG | `scalp7_keltner_hg_fresh_touch_after_reject_utc30m_v1` |
| Squeeze | `scalp7_squeeze_panic_cost4_parent_utc30m_v2` |
| Squeeze | `scalp7_squeeze_trend_signal_low_invalidation_utc30m_v1` |

## Actual result — 2026-10-18

All four existing versions observed the first complete 11:00–11:30 UTC candle for each of the six symbols. Source/model close was **11:30:00 UTC (13:30 Berlin)**; actual constituent receipt availability ranged from **11:30:05.756 to 11:31:44.033 UTC**. The first decision batch was processed at **11:31:44.037 UTC**. There were **24 NO_SIGNAL decisions, 0 signals, 0 virtual entries, closed_T=0 and 0 order calls**. NAV and PnL remain unmeasured.

The first process held on an actual XRP public-feed response at 11:30:22.633 UTC (HTTP 200, exchange code 100410). Its immutable body and cursor were retained. A new bounded process resumed the same state and source, collected the missing observations, and exited normally with code 0. The historical error remains in the state for audit; it is not an unresolved current failure.

A further **new process restart with exactly the same observed input** reproduced the entire state hash `f0d7163f86c28ed5059045be74be4744979dd11a1b841d9a76e3087f70887b1d`, with 0 new market rows, 0 new decisions, 0 additional HG calls, 0 network requests and 0 order calls. Actual open/pending positions were empty; preservation and explicit stop with nonempty positions were separate fixture checks.

Order isolation is supported by the CLI environment boundary, absence of a trading client, GET-only public endpoint allowlist, denied credential-file access, and **58 runtime HTTP receipts, all public GET without authentication**. Process audits recorded 0 credential-file reads and 0 order calls. This evidence covers this observation process; it is not an audit of an external exchange account or every process on the host.

The implementation code commit `c8ebe076239ae173bf6e3f8e9a398c51738105a6` passed 29 targeted local tests and all 18 existing PR workflow runs. The canonical suite recorded 2,246 passed, 2 skipped and 21 passed subtests. A later evidence-only commit adds these receipts without changing that tested implementation.

## Reused components

- `scalp7_fresh_source_v2`: immutable public 1m bodies, HTTP receipts, cursor and verification.
- `scalp7_source_data_v2.aggregate_minutes`: complete UTC 30m bars and actual constituent receipt availability. No gap synthesis.
- `scalp7_fresh_forward_v2.bind_frozen_context`, `scalp7_rolling_context_v2`: existing past-only fit and context rules; no new fit.
- `scalp7_positive_lanes_v2`: native HG state transition, entry, stop and lifecycle callbacks.
- Existing `_keltner_parent_signal`, `_source_condition`, `_squeeze_parent_signal`, `RejectedHGEventReset`, `bind_signal_low`, `native_exit_update` helpers.
- `scalp7_observed_paper_v3.ObservedPaper`: actual post-decision quote timing, virtual entry/exit/partials and cost-reserve accounting. Its formal service/config loader is not started.
- `economic7_canonical_history_v1.atomic_json`: authoritative state commit; four account dictionaries remain separate.

The new modules are `ops/scalp7_orderless_signals_v1.py` and `ops/scalp7_orderless_shadow_v1.py`; three targeted unittest files validate the connections. No existing source, comparator, workflow, owner, checkpoint, consumption ledger, authority or service was changed.

## Evidence boundaries

`RUN_RECEIPT.json` records the actual run; `RESTART_RECEIPT.json` records restart/deduplication and stop verification. The separate downloadable evidence archive contains exact observed raw bodies, HTTP receipts, normalized rows, immutable identities, cursors and state.

The fixed warmup interval is 2026-10-15 22:00Z through 2026-10-18 11:00Z: 122 complete 30m bars per symbol, built from 3,660 actual 1m rows. Last receipt was 2026-10-18 11:22:46.396Z. These are indicator context, with no historical trade, economic run or fresh credit. Actual receipt times remain intact when context is joined.

The stored regime fit comes from `broad_rebuild_v2/FRESH_FORWARD_CONFIG_V2.json`, ending 2026-09-15 00:00Z with 2,160 rows. Its body hash and past availability are checked. The cost reserve and quote clock limits are reused from the existing frozen snapshots, not represented as current exchange fees.

Real observed quotes differ from research next-open fills. Virtual fills require a later public bid/ask request and preserve source, requested, received and actual-clock availability evidence. Sparse observations do not establish complete exchange tick paths, capacity or execution quality.

No verified capital, leverage or exchange quantity is available: quantity and NAV remain null. Any virtual PnL is research-notional bps with the stated reserve, never account return. All evidence is labelled development-only, with formal fresh credit and promotion authority false.

## Restart and stop

From the exact implementation checkout, reuse the same output/source paths:

```bash
python -m ops.scalp7_orderless_shadow_v1 \
  --out /workspace/scratch/a27b7f31a86c/orderless-observation/runtime \
  --source /workspace/scratch/a27b7f31a86c/orderless-observation/source \
  --warmup-source /workspace/scratch/a27b7f31a86c/orderless-observation/warmup-source \
  --collect --max-seconds 600
```

The CLI re-executes with an environment allowlist, no trading credentials, GET-only public quote endpoints, blocked redirects and credential-file access. Exclusive locks reject a second writer. State, code, settings and source hashes must match. Restart never initializes an existing state anew. A fresh-touch historical admission ambiguity remains UNKNOWN until a genuinely observed native reset.

Omit `--collect` to read the saved source without network collection; the output state can still advance. Exact same-input restart verification uses the recorded observation timestamp in `RESTART_RECEIPT.json`. To stop after the current writer has exited, run the same command with `--stop` instead of `--collect --max-seconds 600`. Stop preserves open/pending virtual records and does not synthesize a close. A stopped state intentionally refuses further advancement.

This Work used a bounded session process. No persistent VPS service, schedule, formal Paper/Live activation, remote installation or deployment is claimed. Existing Desktop Commander access to `vultr` was Offline; AGENTS.md forbids manual SSH/deployment. A durable existing execution route still needs to be connected before continuous unattended observation can be claimed.

## Verification

29 targeted unittest cases passed before the actual observation run. They cover environment/public-GET isolation, duplicate input, one HG call per bar, immutable prefix, atomic write failure, state restart, missing/latest/future candles, separate accounts, pending supersession, shared virtual stop/cost execution, open-position preservation, warmup causality and stop. Fixture trades are labelled FIXTURE and give no real/fresh/economic credit. Canonical frontend source validation passed. No Actions deploy is required.

Rollback is stopping this isolated process and retaining its evidence. No production or economic component needs rollback.
