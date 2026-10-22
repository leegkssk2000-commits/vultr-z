# K117 C/D 적용: 설치·연결·저장원장 검산 완료, 실제 시세 계측 미실행

분류: PARTIAL_APPLICATION_NOT_NATIVE_TRACE_OR_ECONOMIC_IMPROVEMENT.

## 실제 수행
- Work C exact commit `48570b3e55b23cc40c69fd9d6e89fd3614dc476c`를 `/home/z/worktrees/zel-work-c-k117-exit-observer-v1`에 별도 detached sparse checkout으로 설치했다. 원본 dirty 작업트리는 변경하지 않았다.
- Work D exact commit `af9451b4ad7efc2111bf88a1901df2d9a8a71a49`를 `/home/z/worktrees/zel-work-d-k117-be-observer-v1`에 동일 방식으로 설치했다. 두 delivery의 tracked diff는 없다.
- C의 `--bind-only`를 실제 실행해 `PINNED_K117_BUILD_ONLY_PASS`를 받았다. D도 정확한 모든 dependency pin과 K117 callable/AST 관측함수를 빌드했다. 이 두 검사는 시세재생0이다.
- D의 `saved_ledger_audit.py`를 VPS의 실제 저장117 원장에 적용해 결과파일을 생성했다. 결과 SHA256 `408efa7ff90061d3dd9c25bba9087597a6906ed51a3d6eec69f38e778d217c74`. 117건 전체, 기본71승46패, 비용2배43승74패가 검산 입력이다. 새 전략성과가 아니다.

## 실제 실행 연결과 실패
기존 owner를 `k117_cd_passive_apply_20261022` 한 건으로 WAITING 결속했다(commit `00e19dd4d33bedb9021975ff39281f5c75e77b10`). 기존 공통 경제배정이 점유 중이면 즉시 종료하는 공식 관측 호출 래퍼를 준비했고, 관측기나 전략 원문은 바꾸지 않았다.
기존 연구브랜치 one-shot workflow를 재사용한 commit `ac8eecd31cd41faee263e246e7f998538d425d27`에서 실제 요청 run `39762857755` (#455)이 생성됐다. 2026-10-22T10:24:26Z 생성 후10:24:28Z CANCELLED, jobs0. 호출 전 취소로 원격 native C/D는 시작되지 않았다. 취소 actor/직접 원인은 미확인이다. 같은 요청 재등록이나 다른 작업 취소는 하지 않았다.
10:30:27Z 실제 공유배정은 Supertrend run39761464232 in_progress, A3 run39762858877 pending이었다. 로컬 경제실행0, C/D 지정 결과폴더도 없었다. 해당 ID를 영구차단으로 사용하지 말고 다음에는 현재 상태를 다시 확인한다.

## 바뀌지 않은 경제판정
K117 기준선117T, Net1x+10159.281145923826 / Net2x+8399.99437120003 trade-bps, 최대연패5/11. 기존 개발성과이며 계좌수익률/OOS/실측펀딩 성과가 아니다. 신규 정책0, 신규 경제비교0, native observer0, 주문0, Shadow변경0. 이번 코드 설치와 원장 검산을 추가수익이나 동적청산경로 확보라고 보고하지 않는다.

## 다음 하나의 실제 소비 경로
새 Work/C/D 재작성 불필요. 기존 owner와 current capacity/프로세스/시작영수증을 확인한 뒤 `apply_existing_once.py C`로 정확한 C 관측기1회, C완료·현재슬롯 확인 후 `apply_existing_once.py D`로 D1회다. 각 호출은 가격정책 변경이 아니라 원형117 재현·passive계측이다. 출력폴더가 있으면 먼저 PARTIAL/RECEIPT를 확인하고 blind재실행하지 않는다. 두 실제 receipt가 생기면 `report_traces.py`로 실제 event와 Gross-Cost=Net을 검산한다. 저장 원장·동결코드·기존 의사결정 순서를 바꾸지 않는다.
`queue_apply_existing.py`는 정확히 배정된 자기 GitHub run에서만 가능하다. 취소된39762857755 ID로 실행할 수 없다. 현재 직접 호출을 실제 슬롯 없이 강제로 실행하지 않는다. 대기 daemon·새 예약·서비스·권한 확대를 추가하지 않았다.
