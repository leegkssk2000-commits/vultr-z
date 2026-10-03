# K.P validation preparation authorization after PR1350

Scope: `KP30_VALIDATION_PREP_AND_IMPROVEMENT_SEPARATION_AFTER_PR1350_V1`.

The actual user message at 2026-10-03T16:54:16+02:00 explicitly requests Keltner-only preparation implementation, synthetic integration/regression tests, read-only access/source recovery, one reviewable validation protocol and the normal research review/CI/PR lifecycle. AGENTS.md's existing exception permits explicitly requested work outside the frontend. Required canonical frontend prechecks passed before editing.

The attached handoff is preserved as `WORK_NEXT.txt`; it is a scope specification together with the actual user instruction, not an economic execution approval. PR1350's admission receipt and frozen parent remain unmodified. PR1349's completed 119-row amount audit, existing FULL and completed admission review are inherited and are not repeated.

Implementation stays in a transparent research-local preparation module and new synthetic tests. It reuses existing read-only parent/ObservedPaper interfaces without installing a backend entry point or activating a collector. Existing guards, seals, allowlists, workflows, backend modules, shared 21-identity configuration, MICRO, SR/HG1997 ledgers and other lane budgets remain unchanged. Existing ordinary saved/synthetic CI discovers the added `test_scalp7_*.py` tests; no new execution workflow is added.

Authorized now: read-only normal access checks, candidate-only supplied-input preparation code, synthetic tests, nonexecuting protocol/design proposals, existing-seen observation/hypothesis preparation and normal repository storage/review/CI/PR work.

Not authorized now: new FULL, genuine-price strategy probe/replay, G5B activation, starting market-data collection, paid spend, service changes, real orders, strategy tuning, G6 execution or promotion. Proposed future protocol choices and exact planned execution labels do not register identities, allocate credit or grant execution permission.

Actual user instruction:

```text
[PR #1350 이후 — Keltner 검증 실행준비 착수]

repo=leegkssk2000-commits/vultr-z

첨부 WORK_KP_AFTER_PR1350_NEXT_20261003.txt 전체를 읽고
명시된 후속 준비범위를 실제 수행하라.

PR #1350의 입장판정과 Keltner 부모 규칙을 보존한다.
119건 검산·기존 FULL·완료된 입장심사는 반복하지 마라.

현재 허용된 접근 경로와 미사용 자료의 상태를 확인하고,
Keltner 전용 입력·시각·부분청산·R·비용·펀딩·
중복 방지·체크포인트 연결을 최소 구현·통합시험하라.

G5A 미사용 OOS와 G5B 검증의 순서를 구분하고,
프로토콜·실행 전 점검·정확한 실행 ID·필요 횟수·
종료 조건을 한 묶음으로 제시하라.
확인 가능한 항목을 ‘미정’으로 남긴 요구사항 보고만 반복하지 마라.

추가개선은 기존 개발 증거의 가설과 관측 항목 준비로 분리한다.
부모 규칙을 바꾸거나 미사용 검증자료로 튜닝하지 마라.

이번 지시는 준비 구현·시험 범위다.
신규 FULL·G5B 활성화·새 시세수집 기동·유료 지출·
서비스 변경·실주문·G6 실행은 승인하지 않는다.

실제 구현 결과, 실행준비 완료 여부, 정확한 외부 차단,
필요한 다음 승인을 보고하고 마감하라.
```
