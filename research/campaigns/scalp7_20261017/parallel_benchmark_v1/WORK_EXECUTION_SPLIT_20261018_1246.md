# 기존 두 개선안 실행 + 무주문 Shadow 작업 분리 — 2026-10-18 12:46 Europe/Berlin

사용자 최신 요청: 정보수집만 하지 말고 실제 개발에 사용하라. 현재 Chat에서 실행할 수 없는 일은 Work에서 처리하도록 필요한 작업을 나누라. 이 문서는 기존 최소제품 지시 Issue1334 comment6236661922의 실행 인계다. 새 경제후보·FULL 예산·실주문·유료API 승인이 아니다.

## 현재 확인한 사실과 완료 재작업 금지
- 경제 owner=CLOUD_WORK_COORDINATOR_ISSUE1358_V1. 기존 단일 담당과 global-heavy<=1 유지.
- owner ref=research-coordinator-claims/issue1358-cloud-work-v1.
- 읽은 current_resume: research/campaigns/scalp7_20261005/coordinator_work_v1/EVIDENCE_INDEX.json, Git blob404d76d4e2c9c218fdf7df4408ea87c4b230fbf9. PREPARATION_MERGED_ECONOMIC_EXECUTION_BLOCKED, remaining2, Shadow NOT_STARTED. 실행 직전 이후 변경·소비는 다시 확인한다.
- PR1449 merged=true, merge7e229bd37c7df7ba8b99a424cb67d84e0074e4e2를 직접 재확인했다. 옛 READY_HANDOFF의 미병합 문장을 현재 상태로 쓰지 않는다.
- K 비교기 ops/scalp7_keltner_fresh_touch_successor_v1.py 현재 blob6df588e51afda0557f65cd4e47e67c2849da5f09.
- S 비교기 ops/scalp7_squeeze_signal_low_comparison_v1.py 현재 blob75dd7f8ef88a6568c3328bf1a956660572739dbd. 기본 scan, FULL은 실제 claim과 앞선 K 결과 필요, 결과 덮기 금지.
- 기존 5개 연구복구·04e242e9 인계·83b3174d 코드·PR1445/1447/1448/1449 완료 부분은 재작성하지 않는다.

## A — 기존 경제개발 Work: 실행 연결과 실제 손익표
1. 최신 master/AGENTS, owner current_resume, Issue1334 comment6144885708와6236661922 및 이후 변경을 읽는다. 동일 후보의 active claim/run/결과가 있으면 회수하며 경제담당자를 새로 만들지 않는다. 수동 Work가 담당 중이면 예약은 같은 claim에 중복 실행을 만들지 않는다.
2. 첫 행동은 이 Work 자체의 기존 인증 터미널/Actions 실행가능 여부 점검이다. Chat의 도구부재를 Work에도 그대로 가정하지 않는다. CLI가 있으면 gh auth status와 저장소·대상 workflow 읽기를 확인한다. 계정 admin이나 조회 성공은 실제 dispatch 성공과 다르다. 새 secret/권한/결제/우회 경로는 만들지 않는다. 실행수단이 없으면 첫 접근점검 직후 정확한 실패명령/오류·필요한 사용자조치 한 가지를 보고하고 같은 조사루프를 반복하지 않는다.
3. 소비원장과 전체 shared-heavy active/pending을 확인하고 기존 kp-github-access-diagnosis-20261004.yml workflow_dispatch로 미소비 K 비교를 한 번 수행한다. 기존 대기를 밀어내거나 정상작업을 취소하지 않는다. 실제 대기열 결함은 기존 승인 안의 최소수선·검증만 한다. 새 스케줄러/전체워크플로 정리는 하지 않는다. 실 run ID와 경제 step 시작을 확인한다.
4. 기존 인증245일·6종목·30m 원천, 원형109T parity, 저장된 기각본146T, fresh-touch successor를 결속한다. 기각본은 재실행하지 않는다. KELTNER_FRESH_TOUCH_SUCCESSOR_RESULT.json·거래/미결·해시와 첫 비용1x/2x 경제표를 저장하고 먼저 보고한다. S 또는 추가연구를 기다리지 않는다.
5. 같은 Work에서 S의 저장57T source trigger scan으로 이어간다. 완전한 가격경로에서 earlier_invalidation_count=0이면 FULL 없이 종료; 입력부재는 UNKNOWN. 발동하면 앞선 K 결과·기존 실제 claim을 결속해 잔여 허용1회만 FULL. scan과 FULL은 각각 새 출력경로를 사용한다. S의 기존 실행기 연결이 미완성이면 필요한 최소배선만 검증·통합하고 엔진을 새로 쓰지 않는다.
6. 첫 표는 원형/기각본/후속본 T·진입/일·Net1x2x·PF·DD종류·연패누적손실·보존/훼손승리·run/result다. 원형·기각·미완결·후속점유를 보존한다. 과거 trade-bps를 계좌NAV나 fresh로 바꾸지 않는다. 기존 gate로 기각/개발보존/독립검증대기 판정. 현재 승인 범위는 매 단계 재질문 없이 수행하지만 추가 후보/FULL/실주문은 개방하지 않는다.

## B — 무주문 Shadow Work: 경제실행과 충돌 없는 준비·새 관측
1. 별도 개발브랜치에서 기존 source/신호/가상체결/원장 모듈을 재사용한다. 같은 작업이 이미 있으면 이어받고 복제하지 않는다. B는 경제 OWNER/CHECKPOINT/소비원장/원형/경제비교기/workflow를 수정하지 않으며 새 FULL이나 후보선정을 하지 않는다. 공통 파일 변경은 A가 통합한다.
2. 대상은 Keltner 원형/fresh-touch, Squeeze PANIC 원형/signal-low의4버전. 두계열이지4독립전략이 아니다. 준비된 원형부터 관측하고 5번째 후보나 A의 경제합격을 기다리지 않는다.
3. 주문 제출 경로·매매키 접근이 없는 격리를 먼저 검증한다. 기존 승인된 무료 feed와 무주문 지속경로만 사용한다. 새 서버/결제/권한/운영배포/formal Paper/Live는 하지 않는다. 실제 경로가 없으면 코드준비와 기동차단을 분리한다.
4. 새 확정30m 수신→동결신호→가상체결→기존 손절/청산→원장/상태복구를 최소연결한다. 실제 수신시각과 BAR_CLOSE_MODEL을 구분하고 지연 후 지나간 next-open에 체결됐다고 쓰지 않는다. 미완료/결측/분절/중복은 해당 lane fail-closed. HG 중복호출, 미래 context-fit, 재시작 후 과거신호 재진입을 방지한다.
5. 기존 가상자본/노출 설정이 확인되면 재사용한다. 미확인 자본/레버리지를 새로 정하지 않으며 NAV미측정으로 둔다. 원형/수정본은 대조원장으로 분리해 중복수익을 합산하지 않는다. 첫 산출물은 실제 사용경로·최소시험·기동버전·새 봉의 source/received 시각·원장·재시작/중지·주문호출0 증거다. 모의시험/실제 관측/가상거래/경제합격을 구분한다.

## 모은 정보의 사용 위치 — 추가 수집이나 새 게이트가 아님
- Keltner: 기존 fresh-touch의 거절→새접촉→반전→진입 causal_trace와 실제 비용후 결과를 사용한다. H02 거절 이전 weak-state 유지와 분리하며 ADX 변경/reset규칙을 몰래 추가하지 않는다.
- Squeeze: 첫 양수 감소 / 두 연속 양수 감소 / 최초 음수전환 / signal-low / 기존 stop·max-hold를 구분해 피한 손실과 회복승리 훼손을 비교한다. 이미 붙은 optional H01/H02 관측만 활용하며 추가필드 구현을 경제실행 선행조건으로 하지 않는다.
- 최근 세 연구는 LazyBear 수정 Pine, Carter에게 귀속된 두감속 조건, 번역 인터뷰의 첫감속후 회복사례다. 세 신규전략이나 경제성과가 아니다. 원문사실·2차귀속·저자자기보고·내부가설을 구분한다. 첫감속 즉시청산을 새 기본규칙으로 넣지 않는다.
- 정보수집 보조는 새 결과가 생겼을 때 저장 원장의 비용/기회/회복승리를 검산하는 데 우선 사용한다. 같은 H01/H02를 반복 요약하지 않는다. 실제 반증 질문이 없으면 추가검색하지 않는다.

## 사용자에게 전달한 실행 패키지
파일명 ZEL_WORK_EXECUTE_20261018.zip. SHA256=5bb0fdd21d30de8bd02646d11c111c8dbea0995f9e613c7ca4f9f41d5a94bcea. GitHub에 ZIP을 업로드했다는 뜻이 아니며 Work에는 사용자가 첨부해야 한다.
- WORK_A_ECONOMIC_EXECUTE.txt / WORK_B_ORDERLESS_SHADOW.txt / START_HERE.txt / EVIDENCE_USE_MAP.md / PACKAGE_RECEIPT.json.
- 기존 K 결과 NATIVE_DAILY_FUNNEL.json: 146T, receipt a17e2d42d89875e5c215824c68c324aaf95d867e217a08c981fdcb0e76289137.
- 기존 S 결과 SQUEEZE_REGIME_OVERLAY_RESULT.json: 57T, receipt8389495e62fb1da211c7b360de621ed782322280552d627dea58909eee6025e8.
두 결과의 내부 receipt 해시를 재계산하고 원본바이트 그대로 첨부했다. 이는 재백테스트가 아니며 실제245일 OHLC를 포함하지 않는다. 기존 아티팩트 만료/대화파일 분산 때문에 실패 실험을 재실행할 필요를 줄이기 위한 입력 묶음이다.
- 최근 연구원본3건(20261018 0822/1022/1121)을 바이트 그대로 첨부했다. 이전 도구안전차단을 우회해 원격 복구했다고 주장하지 않는다.

현재 이 인계 작성에서 새 경제실행0, 새 Shadow기동0, Work세션 시작0이다. 인계 저장은 개발 소비나 실행 성공이 아니다. 기존 마감 10/18 18:30·10/20 18:30·10/24 18:30 Berlin은 미달 시 자동연장하지 않는다.
