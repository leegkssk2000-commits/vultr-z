# Issue #1278 결과 전 실행 계약

이번 권한은 PR1277 종료와 별개인 신규 권한이다. 기존 차단을 경제적 실패로 바꾸지 않는다. Issue1278과 WORK_NEXT가 요청한 source·연구·테스트·CI 범위는 AGENTS.md의 명시적 요청 예외에 해당한다. 기존 AGENTS.md와 기존 전략·경제 계약은 수정하지 않는다.

## 1. 공식 출처와 진단

공식 BingX repository의 현재 commit `5fb44d121b7e10ef3493bb4de21fedf7e5c98ac6`과 3개 문서 blob·UTF-8 SHA를 별도 receipt로 결속했다. 문서는 v3 kline 배열의 index0 open과 index6 close를 정의한다. 문서의 header는 실제 새 transport에 적용하지만, header가 응답 schema를 바꾼다고 주장하지 않는다. 공식 README의 공개 market 무인증 허용에 따라 key·signature를 요청하지 않는다. 모듈의 상충하는 인증 문구도 기록한다.

Probe A는 2026-07-18 00:00 UTC, B는 인접한 01:00 UTC로 고정한다. 각 요청은 BTC-USDT/1h/startTime=T/endTime=T+1h−1ms/limit3이며, Accept와 X-SOURCE-KEY를 동일하게 사용한다. 두 probe는 경제 target 이전이고 가격·수익·feature·gene 선택에 사용하지 않는다. 요청 간 최소 간격은 1,100ms다.

사전 봉인한 진단 소스와 protocol만 root가 실행한다. 진단 전체의 단일 attempt를 먼저 예약하고, 각 GET 직전 URL/query/명시적 outbound header를 저장한다. 원문 bytes·SHA·응답 status/header를 JSON decode 전에 저장한다. 최대 2개 GET이며, HTTP/transport/JSON 등 치명 오류에서는 추가 호출 없이 종료한다. 읽을 수 있는 응답이 객체형이라 의미를 증명하지 못한 경우에는 예정된 B를 관측하여 두 결과를 기록한다. 재시도·대체 host·header 변경·추가 요청은 없다.

## 2. 사전 고정 PASS 기준

두 응답 모두 배열형이어야 하며, 각 target [0]==T/T2가 정확히 1개여야 한다. 최대 3개 행에서 T−1h와 T+1h의 guard만 허용하며, 중복·그 밖의 시각·비정수·불완전 schema는 거부한다. 모든 배열의 explicit [6] close를 검사한다.

공식 문서가 close의 포함 규약을 정의하지 않았으므로 `close−open=3,599,999ms` 또는 `3,600,000ms`를 사전에 허용한다. 모든 행과 두 probe에서 동일한 규약이어야 한다. 실제 규약은 receipt에 기록하고 canonical open은 [0] 그대로 둔다. canonical exclusive close는 open+3,600,000ms다. 이는 native timestamp를 이동하는 보정이 아니다.

객체 `time==요청 T`, 1시간 간격, 가격 연속성 또는 값 일치만으로는 별도 cross-schema witness가 되지 않는다. 객체 원문을 공식 배열과 연결하는 독립 증거가 없으면 `BLOCKED_CANONICAL_KLINE_SCHEMA`다. 두 인접 요청만으로 확보되지 않은 witness를 만들지 않는다. 혼합 schema도 차단한다. 배열 PASS는 ARRAY_ONLY 권한이며, 이후 source의 객체 fallback은 허용하지 않는다.

## 3. 조건부 source와 경제 실행

Calibration PASS 후에만 새 V3 source 수집기를 봉인하고 단일 common source 취득을 시작한다. BTC/ETH 각 1,000개 open clock, 고정 cutoff, 최대3페이지/심볼·retry0·raw 우선 저장·guard 경제입력0·동일 timestamp vector 조건을 유지한다. 직접 array open/close와 관측한 close 규약을 검증하고 DATA_FREEZE_V3를 봉인한다.

그 뒤 동결된 B/P controls 최대4회, DEV_A G1∼G6 screen 최대6회, 최대2 생존자 원격 봉인, 변경 없는 DEV_B confirmation 최대2회 순서다. DEV_B 결과로 A 선택·규칙을 바꾸지 않는다. U1과 필요 시 독립 2축 AND U2만 허용하며 최대2후보·child FULL 최대4회다. controls를 재생하지 않는다. 최종 gate와 Pareto는 PR1275 원본 계약 그대로다.

원형 정책·진입·청산·크기·비용·분할·G1∼G6·gate는 모두 보존한다. 새 경제 owner는 root 하나이며 보조 에이전트는 실제 수집·경제 실행을 하지 않는다. 일반/상위10% winner retention 및 donor attribution도 저장 원본과 같은 key·경로로 검산한다. 유료 AI·live·order·deploy·prospective decode·Squeeze data 접근은 0이다.

## 4. 종료

Probe/source 실패는 해당 정확한 차단 상태로 종료하며 미실행 경제표를 N/A로 기록한다. 유전자 생존자0이면 NO_CAUSAL_UNIFIED_GENE_COMMON_REPLAY, 최종 경제 gate 실패면 TREND_RIDER_UNIFIED_NOT_EARNED_COMMON_REPLAY다. Unified PASS에만 미래 G5A handoff를 작성한다. common replay formal credit은 항상0이며 G5A와 이후 G5B 데이터 시간은 분리한다.

결과·실제 실행수·테스트·CI·리뷰·정상 PR 병합·정확한 병합본 검증을 원격에 보존한 후 이번 scope만 REPORT_ONLY로 종료한다. 잔여 조건부 예산을 자동 successor로 사용하지 않는다.
