# Requested non-frontend research scope — PR1349

AGENTS.md says to avoid unrelated backend/engine/tests/root/workflow changes **unless explicitly requested**. The active request is not a frontend task. This document records the current user instruction and its necessary implementation scope; it does not change AGENTS.md or grant new economic/live authority.

The user's specific request in this conversation was: "양수 Keltner 부모의 증거를 완결하고, 적용할 G4→G5 판정 들어가". After the assistant described preservation of the parent, partial-cashflow reconciliation, cost-sensitive exit analysis, and separation from later improvements, the user explicitly continued: "그렇게 다음 들어가".

The assistant's start notice for this work was: "Keltner 부모는 동결한 채 부분청산 기록과 G4→G5 적용 근거를 확인한다. 비용 2배에서 승리에서 손실로 바뀐 거래도 분해해, 지금 필요한 일이 증거 수선인지 별도 개선인지 구분하겠다. 기존 SR 실행과 예산은 건드리지 않는다."

Implementation scope directly supporting that request:
- Add one saved-file arithmetic script under scripts/ and its synthetic tests under tests/.
- Store research findings and this scope record under research/campaigns/scalp7_20261003/kp_saved_evidence_v1/.
- Add one narrowly branch/path-triggered contents:read workflow for those saved inputs/tests. No scheduled or economic execution, secrets, SSH, VPS, service, deployment or network data collection.
- Preserve all existing backend/strategy sources, publication guards, allowlists, seals, budgets and historical results. Original files are only read and hash-checked.

Required frontend canonical validation ran before initial changes and again in the dedicated CI before/after the saved audit. This does not convert the task into a frontend change. Moving the research code into the frontend would obscure rather than satisfy its intended boundary.

This request authorizes neither a new FULL budget nor G4 PASS/G5 admission by declaration. The exact candidate's transition contract remains unbound; this document must never serve as that contract. SR1347 and HG1997-1348 remain separate.

The automated P1 scope comment is preserved for review. This file supplies missing user-task context and identifies the existing AGENTS exception; it is not an attempt to suppress or weaken a checker or silently mark the review resolved.
