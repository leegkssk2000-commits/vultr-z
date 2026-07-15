# Team/Advisor TB-1 runtime verdict — 2026-07-15

## Runtime result

- state: `HOLD`
- verdict: `TB1_AUTHORITY_SURFACES_REQUIRE_MANUAL_CONTRACT_AUDIT`
- matched files: `1200` (hard cap reached)
- active components: none resolved
- ambiguous core components: LBot, MBot, OBot, SBot, ZBot, ZICO, LiCo, Zlice
- authority candidates: `33`
- Producer PID preserved: `1779948`
- Writer PID preserved: `1780181`

## Audit defects discovered

The TB-1 result is not suitable for owner selection because the audit itself is contaminated:

1. Path exclusion used exact directory-part equality, so directories such as `.backup_restore_*`, `_LIVE_BACKUP_*`, `_LOCKED_BASELINE_*`, `_restore_*` and `_rollback_*` were scanned.
2. Frontend bundled assets were scored as canonical owners even though they are display/build artifacts.
3. Authority detection treated policy fields such as `paper_enabled`, generic `ledger` mentions, verifier scripts and `write_text` as direct execution authority.
4. Command output was globally truncated to 500 characters before systemd field parsing, causing active-unit false negatives, including ZICO/Team-lane surfaces observed in earlier audits.
5. The 1200-file cap was exhausted by contaminated frontend/backup material before the canonical backend search completed.

## Decision

Do not use the 33 authority candidates or the component rankings for mutation, removal, activation, or binding.

Next stage: TB-1.1 contamination-clean owner narrowing and semantic authority trace. It must exclude backup/build/display artifacts, parse systemd without global truncation, distinguish direct order authority from file-output/policy references, and emit only bounded owner candidates.
