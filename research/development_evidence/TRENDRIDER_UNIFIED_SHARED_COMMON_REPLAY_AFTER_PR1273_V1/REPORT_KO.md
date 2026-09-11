# TrendRider shared common replay — Issue #1274

**최종 source 판정: `BLOCKED_COMMON_SOURCE_DATA`. 전략의 경제적 실패 판정이 아니다.**

승인된 단일 수집 응답이 고정 시간 경계를 위반했다. 사전 계약대로 부모 대조·유전자 screen·후보 FULL을 모두 실행하지 않았다. Unified 전략 봉인과 prospective G5A handoff는 없다. 이 scope는 REPORT_ONLY이며 조건부 후속 예산은 무효화했다. 자동 재수집·미세튜닝 successor를 만들지 않는다.

## 원문으로 확인한 차단 원인

| 항목 | 계약/요청 | 실제 응답 |
|---|---|---|
| 시장 | BingX USDT-M, BTC/ETH, 1h | BTC 첫 요청까지만 수행 |
| endTime | `1788047999999` = cutoff−1ms | 요청 메타데이터 일치 |
| HTTP / API | 정상 응답 필요 | 200 / code 0 |
| BTC 봉 수 | 정확히 1,000 | 1,000 |
| 첫 native open | 2026-07-19 08:00 UTC | **2026-07-19 09:00 UTC** |
| 마지막 native open | 2026-08-29 23:00 UTC | **2026-08-30 00:00 UTC** |
| 누락 | 0 | 첫 봉 1개 |
| cutoff 이상 봉 | 0 | cutoff 봉 1개 |
| 중복 / 인접 시계 간격 결함 | 0 / 0 | 0 / 0 |
| ETH 요청 | BTC 검증 통과 후 | 미실행 |
| 정규화 데이터 / 공통 data SHA | 검증 통과 후 봉인 | **없음** |

실패 코드 `SOURCE_TIMESTAMP_GRID_OR_WINDOW`. endpoint가 이 응답을 반환한 내부 원인은 추정하지 않았다. 원문 111,096 bytes와 요청·응답 시각, HTTP 상태, SHA를 JSON 검증 전에 저장했다. 이후 진단은 timestamp만 대조했으며 지표·의도·손익을 계산하지 않았다. 거부된 원문은 격리 증거이며 replay 입력이 아니다.

원문 SHA256: `098fa627689d58fe765b79242f01eba144e978eead6e0b6debea9154a7ed2fb9`.

고정 계약은 범위 밖 봉을 거부하며 재수집을 금지한다. cutoff 봉을 버리고 다른 페이지를 추가하거나 요청 시각을 바꾸는 수선은 하지 않았다. 이 실패를 `NO_CAUSAL_UNIFIED_GENE_COMMON_REPLAY` 또는 경제적 후보 REJECT로 바꾸지 않는다.

## 경제 결과 전 봉인

원격 커밋: `b8afbb355921970092a25fcf11304d13b5fea497`.

| 봉인 | SHA256 |
|---|---|
| COMMON_REPLAY_CONTRACT.json | `b8e37cd4ebd58425c9e13917d77230994f5dec1b48dc57543bd2d0d4a409e813` |
| PREEXEC_FREEZE.json | `73b90a8093eabb08db68829c6b82a42f459009d4054ce6a97f3961fe4c68ffd4` |
| 공통 비용 객체 | `db626f99bb9e5619e59e29041c02f6ad97582e788fb3715c831f3e99718023eb` |
| B_COMMON 원본 정책 | `f58792c31d9b358894c6626ea8aa273aef3ba086366d023913003eeb8e576b1e` |
| P_COMMON 원본 정책 | `ff9f4d75922504d83cc42f20cbbeaa118c3592f73d550511d8a8b5711b0c5335` |

12개 계약·구현·테스트·출처 파일을 사전 봉인했다. 원격 manifest를 다시 읽어 일치를 확인하고, 단일 수집 직전 12개 파일 및 기존 TrendRider 출처·PR1273 증거 32개 파일의 SHA를 검증했다. Python 3.12의 원형 정책 계산을 고정했다.

비용은 정적 DEV 왕복 **fee10 + spread floor1 + impact floor2 + funding proxy1 = 14bps**, 정확한 2배는 28bps다. 비용 authority는 funding 상수를 제공하지 않는다. funding proxy1은 두 기존 upstream receipt의 reserve metadata에서 가져온 연구 가정이다. 현재 depth를 과거 거래에 붙이지 않았으며 실제 signed funding, settlement calendar, production-grade 비용을 주장하지 않는다.

64개 봉을 계산용 warmup으로만 배정했다. DEV_A는 index `[64,532)`, 2026-07-22 00:00∼2026-08-10 12:00 UTC이고 DEV_B는 `[532,1000)`, 2026-08-10 12:00∼2026-08-30 00:00 UTC다. 각각 468개 signal timestamp이며 구간별 경제 상태는 flat으로 시작한다. 마지막 봉의 다음 open이 구간 밖이면 unfilled로 남기는 계약이었다.

## 역사 기록과 새 공통 평가의 구분

| 지표 | Historical Primary archive | Historical Broad archive | P_COMMON | B_COMMON | U1 | U2 |
|---|---:|---:|---|---|---|---|
| 완결 T | 16 | 30 | 미실행 | 미실행 | 미생성 | 미생성 |
| 승리 T / WR | 13 / 81.25% | 21 / 70.00% | N/A | N/A | N/A | N/A |
| 역할 | 불변 역사 benchmark | 불변 역사 reference | 재실행 가능한 Primary 계보 proxy | 원형 Broad 정책 | 조건부 Unified | 조건부 2축 AND |

P_COMMON은 historical Primary16과 동일하지 않다. 과거 두 lane의 window·입력·평가 맥락을 이번 공통 baseline으로 취급하지 않았고, 옛 성적의 수치 재현을 요구하지 않았다. 기존 prospective boundary와 이력은 수정하지 않았다. 신규 공개 과거 데이터 승인과 기존 prospective ledger의 사용 권한을 혼동하지 않았으며 기존 prospective ledger decode는 0이다.

다음 지표는 **DEV_A와 DEV_B 모두 동일하게 N/A**다. 미실행을 손익 0 또는 거래 0건의 실측 결과로 표시하지 않는다.

| 공통 평가 지표 | P_COMMON | B_COMMON | U1 | U2 |
|---|---|---|---|---|
| eligible / completed / open-censored / unfilled | N/A | N/A | N/A | N/A |
| WR / net / expectancy / PF / payoff / cost2 | N/A | N/A | N/A | N/A |
| avg win / avg loss / worst / loss-tail / loss streak | N/A | N/A | N/A | N/A |
| closed DD / marked DD / exposure / conflict / top1 | N/A | N/A | N/A | N/A |
| feature / intent SHA lineage | N/A | N/A | N/A | N/A |
| overlap / P-only / B-only / displaced | N/A | N/A | N/A | N/A |

## 유전자 및 조건부 Unified 절차

| 사전 고정 gene | 조건 | screen / confirmation |
|---|---|---|
| G1 TRANSITION_FRESHNESS | P_COMMON actionable | 미실행; strict raw B_ONLY에서는 구조적으로 공집합 |
| G2 HISTORICAL_PRIMARY_QUALITY | source-open session!=US 또는 chase_now<=chase_prior | 미실행; 원본 classifier 출처 복원 |
| G3 ST_GAP_EXPANDING | st_gap_now>st_gap_prior | 미실행 |
| G4 CHASE_COOLING | chase_now<=chase_prior | 미실행 |
| G5 ATR_EXPANDING | ATR/close_now>ATR/close_prior | 미실행 |
| G6 GEOMETRY_ST_GAP_GE_CHASE | st_gap_now>=chase_now | 미실행 |

G3–G6는 결과 전 고정한 기전 가설이다. 과거 승리에서 선택한 것으로 주장하지 않는다. PR1052의 terminal reject인 3봉 방향 지속 predicate는 제외했다. G6는 gap/chase 2축으로 처리한다. DEV_A 하드게이트→최대2 생존자 동결→수정 없는 DEV_B 확인→U1 및 독립 2축 AND인 U2라는 절차는 구현했으나 source gate 실패로 실행하지 않았다.

따라서 admitted/rejected B_ONLY, removed losers/clipped winners, ordinary/top10 보존률, P core 유지와 실제 점유 탈락, 추가 비용·DD·집중도 attribution도 N/A다. 불합격 유전자나 후보가 관측됐다는 뜻이 아니다.

## 예산·검증·변경 범위

| 항목 | 승인 상한 | 실제 |
|---|---:|---:|
| 공통 dataset 수집 시도 | 1 | **1** |
| HTTP 응답 | 결정적 pagination 범위 | **1**, BTC만 |
| 부모 경제 실행 | 4 | **0** |
| DEV_A screen | 6 | **0** |
| DEV_B confirmation | 2 | **0** |
| canonical 후보 / child FULL | 2 / 4 | **0 / 0** |
| retry / sweep / FIXED / arbitrary OOS | 0 | **0** |
| prospective ledger decode / Squeeze v1·v2 데이터 접근 | 0 | **0** |
| paid AI / 주문 / live / 배포 | 0 | **0** |
| prospective G5A handoff / formal credit | 성공 후 조건부 / 0 | **0 / 0** |

사전 합성 테스트 **55개 PASS**: 원형 B/P feature·intent 일치, 미래봉 변조, SHA 결속, SL→TP→timeout, gap 낙관 체결 집계, 구간 경계, 미완결·중복 비용·점유·노출, source malformed/3xx/non200/재호출 차단, gene 인과성·선택 gate를 포함한다. canonical frontend validate도 PASS다. 저장 검증은 봉인된 bytes와 차단 의미만 검사하고 데이터 취득·경제 재생을 하지 않는다.

신규 연구 엔진·source 수집기·gene 모듈, 합성 테스트, 읽기 전용 saved verifier/CI와 이 scope 증거만 추가했다. 기존 부모와 PR1273 증거를 보존했다. CI·리뷰·정상 PR 병합·정확한 merge SHA 검증의 확정 결과는 별도 `EXACT_MERGE_VERIFICATION.json`에 결속한다.

배포는 필요 없다. 신규 연구 코드와 검증 workflow를 정상 revert하면 기능 추가를 되돌릴 수 있으며 기존 부모는 그대로다. 원형 evaluator의 gap-through-SL 낙관 체결과 미구현 trailing/runner 의미는 구현에 명시했다. 이번에는 실자료 경제 실행이 없으므로 그 호환성이나 Unified 수익성을 검증했다고 주장하지 않는다.
