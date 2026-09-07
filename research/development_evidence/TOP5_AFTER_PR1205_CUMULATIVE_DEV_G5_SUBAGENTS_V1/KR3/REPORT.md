# S2 — inactive KR3 evidence binding

Stored KR3 FULL DEV2025 binding is VALID_DEV_BINDING: 1,469 checks passed. The adapter validates the pinned prior application draft, actual code files, frozen spec and result self-seals, compressed DEV artifact bytes, all 203 row seals, candidate/lane/config/code/data/cost links, closed/open cost arithmetic and receipt totals. It executes the existing `top5_sprint_metrics_v1.effects` producer on stored KR1/FULL rows and gets exact stored retention parity. No market path was replayed.

The preserved result is 202 closed / 1 open, closed net 10,341.726862925216 trade-bps, all-cost2 closed net 5,840.958577635269 trade-bps. The open mark remains hypothetical. These are reused DEV economics, without formal credit. The source guarantee is deliberately limited: artifact bytes and linked historical digest declarations are verified; raw price/cost tape, signed funding, actual quotes/fills and independent production provenance are not certified.

## Exact disposition of the prior 16 items

| Prior unresolved item | Current classification | Concrete progress / remaining requirement |
|---|---|---|
| error_tolerance | ACTUAL_RESOLVED_BINDING | Existing shared authority pinned: errors/duplicate/censored_open/unknown_exit all zero. This defines the allowed tolerance; it does not claim KR3 satisfies it. DEV open=1 remains. |
| P0_P6_bundle | CODE_PREPARED | Existing evaluate_bundle receives the exact bound candidate identity; identity passes and absent P0–P6 evidence fails. Required supports/controls/reviews are not fabricated. |
| fresh_source_receipt | NEEDS_REAL_MARKET_SOURCE | No fresh source collection or actual boundary was authorized. |
| signed_funding_and_execution_lineage | NEEDS_REAL_MARKET_SOURCE | DEV component arithmetic is linked, but real signed settlements/quotes/fill evidence is absent. |
| formal_economic_receipt | UNEVALUATED | Nine fully bound formal economic reports and formal evaluation are absent. |
| initial_risk_R_denominator | NEEDS_AUTHORITY | Explicit statistical volatility normalization formula proposed; no R values emitted. |
| protective_SL_operating_contract | NEEDS_AUTHORITY | Original initial SL remains null; statistical normalization cannot satisfy an operating order requirement. |
| retention_denominator_baseline | NEEDS_AUTHORITY | Existing KR1 retention producer reproduced; formal baseline, denominator/window convention require approval. |
| W1_W2_W3_windows | NEEDS_AUTHORITY | Concrete contiguous UTC-window formula proposed; no dates or window duration silently selected. |
| purge_embargo_runoff | NEEDS_AUTHORITY | Interval intersection purge and cap-derived 96h conservative embargo proposal, with observed-gap/runoff handling. |
| market_shock_and_regime_owner | NEEDS_AUTHORITY | Existing connected grouping algorithm mapped; reviewed causal regime/shock labels and owner remain required. |
| N_effective_terminal_threshold | NEEDS_AUTHORITY | Existing component-count definition and power formula proposed; numerical terminal threshold absent. |
| minimum_economic_effect | NEEDS_AUTHORITY | Mean cluster effect and minimum-effect lower-bound criterion proposed; no numerical effect target invented. |
| review_schedule_multiple_testing | NEEDS_AUTHORITY | Terminal W3-plus-runoff look and explicit familywise allocation proposed; alpha/beta/test family need approval. |
| source_specific_stale_authority | NEEDS_AUTHORITY | Exact per-source freshness inequality specified; source-specific time threshold missing. |
| threshold_authority | NEEDS_AUTHORITY | Existing formal threshold object pinned; missing candidate-specific conventions are not approved by a code owner. |

Totals: **1 actual binding resolved, 1 code prepared, 2 real-source requirements, 11 authority requirements, 1 formal economics unevaluated**. Every original object and status is preserved one-to-one in DRY_RUN.json. No item is claimed formally satisfied.

## Nine reports and approval bundle

DRY_RUN.json maps each report's actual available producer, schema pointer, consumer, units and applicability. Base replay/cost/cost2/symbol/monthly DEV fragments have actual owners. Purged OOS, reviewed regimes, parameter-neighbor experiments and negative controls have no KR3 result producer. The P4 checker is identified as a consumer, not a result producer. All nine reports remain complete=false and formal_eligible=false.

The same file contains one PROPOSED_NOT_APPROVED bundle with formulas, units, owners, impacts and missing decisions. Statistical R is proposed as `d_i = 10000 * ATR20(signal_close_i) / entry_open_i`, `R_i = net_bps_i / d_i`, `NetR_W = sum(R_i)`, with a completed-native-bar Wilder ATR definition and missing/nonpositive denominator rejection. It is a proposed dimensionless statistical normalization, not a protective stop or account-risk multiple; accepting it in the shared net_r field requires explicit authority. No SL or numeric R is introduced. Existing formal gates remain unchanged.

## Verification and handoff

Seven unit tests pass, covering stored evidence, altered code, resealed but economically inconsistent rows, invalid/missing inputs, candidate mismatch, false production labeling, nine-report incompleteness and exact 16-item preservation. FIXTURE_RESULTS.json records VALID_DEV_BINDING / INVALID / MISSING returns. Repository-required frontend validation passed before and after implementation. The first adversarial test exposed an uncaught RuntimeError from the existing economics producer; the adapter now returns INVALID and preserves its arithmetic failures.

Files: backend/research/rebuild/kr3_evidence_adapter_v1.py; test_kr3_evidence_adapter_v1.py; this KR3 output directory. Run `python -m unittest backend.research.rebuild.test_kr3_evidence_adapter_v1 -v` and `python -m backend.research.rebuild.kr3_evidence_adapter_v1`. Root is the sole integrator; no commit/push, shared-gate edit, boundary constructor call, new candidate, paid API or economic replay occurred. No GitHub Actions deployment is needed for these research-only files. Rollback is removal of the two new modules and this output directory; no existing evidence is changed.
