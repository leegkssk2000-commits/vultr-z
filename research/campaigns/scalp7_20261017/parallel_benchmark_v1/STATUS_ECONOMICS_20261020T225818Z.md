# Actual A/B status audit — 2026-10-20T22:58:18Z

Observed on vultr at 2026-10-21 00:58:18 Europe/Berlin. This is a status audit, not an economic comparison, strategy change, deployment or profitability PASS.

## B: actual running observer

- Device: vultr, 18e0412c-ac50-4e46-99ed-5c78a36cbd94. Remote shell succeeded. Agent active/running, NRestarts=0.
- Same observer PID 548354 is alive, with exact command/cwd checked. Process started 2026-10-20T20:06:14Z; runtime about 10,323 seconds (2h52m).
- Exact code: 6f7a42171dab54ff1be544304f44ee06fdd8f056.
- Active out: /home/z/z/runtime/work_b_orderless_20261020_reconnected/runtime_forward_20261020T200614Z.
- Existing CLI bound: 86400 seconds. This does not establish 24-hour completion or a permanent service.
- Last successful observation: 2026-10-20T22:57:53.996Z; snapshot age 24.23 seconds. Latest per-symbol source receipts reach 22:57–22:58Z and all six latest receipt hashes verify.
- Actual completed 30m closes: 20:30, 21:00, 21:30, 22:00, 22:30 UTC, each for six symbols. Thus 30 source records and 120 version/symbol decisions in THIS new forward segment.
- Decisions: 115 NO_SIGNAL/FROZEN_NATIVE_CONDITIONS_NOT_MET; 5 UNKNOWN/HISTORICAL_HG_ADMISSION_UNKNOWN_WAIT_NATIVE_RESET.
- All five UNKNOWN decisions belong to Keltner fresh-touch / ETH-USDT. The other versions/symbols continue to be evaluated. These UNKNOWNs are not market losses or confirmed absence of setups.
- Each of four versions has 30 decisions. Keltner parent: 30 NO_SIGNAL; fresh-touch: 25 NO_SIGNAL + 5 UNKNOWN; Squeeze parent: 30 NO_SIGNAL; signal-low successor: 30 NO_SIGNAL.
- Actual generated trade signals=0; virtual entries=0; all four accounts pending/open/closed trades=0/0/0. The 24 entries in the JSON signals mapping are native state slots, NOT 24 trading signals.
- Retry events=13: attempt 1 count=12, attempt 2 count=1; WAIT_SOURCE_RETRY=13, HOLD_RETRY_BUDGET=0. Latest retry timestamp=22:45:24.911Z; the successful observation is newer than every retry. The same process remains alive.
- PR1450 comment6301984232 independently records the actual 21:00Z case: error at21:00:04Z, retry10s, second error21:00:16Z, retry30s, then processing of the21:00 completed bars at21:00:50Z. This is actual recovery, not only a synthetic test result.
- Process audit at the state snapshot: public GET1045, order calls0, credential-file reads0, blocked calls0. No exchange trading client imported.
- STATE internal SHA256: 64510fd77034e37ab4147aa3a545365b994b4fff9edd5febb5742b398daf52c8; recomputation agrees. STATUS points to the same hash and says DEVELOPMENT_OBSERVATION. All pinned code files match.
- STATE file SHA256: cc476fed2436704833eb3816953e3d5e93596a924bcdd56c5d71a2447fc7e041.
- Historical last_error remains preserved. It is not interpreted as current process failure because newer successful observations and the live PID were checked.
- Full server audit: active out/STATUS_AUDIT_20261020T225818Z.json.

## A: economic comparison still not completed

- Owner branch EVIDENCE_INDEX.json fetched at this audit still records BLOCKED_EXECUTION, no successor economic run and two comparisons requiring consumption reconciliation. This index contains obsolete B NOT_STARTED navigation; actual B evidence above supersedes that field only, not economic authority.
- Repository workflow_dispatch runs queried since 2026-10-20T20:00:00Z: 8 returned, no kp-github-access-diagnosis-20261004.yml match. Issue1334 and PR1449 comments since that timestamp were empty. No new A run/result was found in these checked surfaces; no repository-wide nonexistence claim is made.
- Current master workflow blob448f73c0e11ed8c9c8eb4dbee86be69e9ea55848 still downloads kp-access-diagnosis-38310659348-1 from run38310659348 before the successor comparison.
- Fresh artifact API check for run38310659348 returned an empty artifacts list. The saved-input repair has not been applied to that workflow. This is separate from the now-working VPS remote connection.
- Confirmed completed comparisons of the two approved successors remain0/2 in the checked authoritative record; no new economic result or improvement is claimed.

## Outcome boundary

Operational progress: the repaired observer continues on new actual market input and survives the previously fatal100410 responses without a restart in this segment. Economic progress: UNMEASURED. No new closed trades, cost-after-profit, win rate, PF, drawdown improvement or capital-based NAV is established. Historical development returns are not relabelled as this run's returns.

Audit actions: read live process/state/source and GitHub records; save this evidence only. No observer restart, state reset, strategy modification, new candidate, new economic FULL, order, owner/checkpoint/consumption mutation or automation change.
