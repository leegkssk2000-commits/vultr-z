# TrendRider Unified v1 — Issue #1272 종료 보고

**BLOCKED_PARENT_PARITY · TREND_RIDER_UNIFIED_NOT_EARNED · REPORT_ONLY.** 저장 부모의 membership·receipt·손익 산술은 PASS지만, 승인문 Stage0가 요구한 동일 frozen data/cost clock과 실제 entry feature snapshot을 복원하지 못했다. Stage1 스크린·신규 후보·FULL·부모 control 재생은 모두 0회다. Survivor는 **NOT_EVALUATED**이며 경제적 REJECT 또는 NO_CAUSAL_UNIFIED_GENE 판정이 아니다.

## 1. 부모 identity와 역할

| 항목 | Primary | Broad |
|---|---|---|
| lane | trend_rider_primary_wr8125 | trend_rider_broad_wr7000 |
| exact frozen | 16T / 13승 / 81.25% | 30T / 21승 / 70% |
| receipt SHA256 | 98e4abf1c6d7102f930f95db85fb125f6e726765834a8774d4cc24c662446625 | b9a7cc4c930952e9fae3a4b65012ceb393f0e084ee3c9decbd2854858a4fedd9 |
| 현재 승인상 역할 | quality donor/control | coverage/economic parent |
| 보존 상태 | FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED | historical G4_ECONOMIC_SURVIVOR |
| 전략 승격 | 없음 | 없음 |

Primary의 원본 descriptor에 따라 upstream25 중 entry_ts/symbol순 첫24에서 non-US15와 원래 US anchor1을 복원했다. 이는 역사 membership 감사에만 쓰며 runtime 진입 규칙이 아니다. 16개 저장행의 값이 원본과 전부 일치했다. Primary 원본 소스 receipt `b064d6ee58c158cdb1169b79d93d1df46ea020d0dde3762703a577f9a3068103`도 검증했다.

Primary의 기존 6M224T net+87.21bps/PF1.0046, recent3M123T net−4275.95bps/PF0.6008, donor winners0의 terminal은 보존했다. Broad 기존 G5 proxy21T/production_grade_T=0은 새로 평가하지 않았고 formal production PASS/FAIL로 재해석하지 않았다.

## 2. 공통 opportunity 전수 분해

`(symbol, native signal_ts, side)`를 underlying key로 사용했다. 동시 신호의 intent/feature 해시는 lane별로 다르므로 그 해시로 서로 다른 거래라 세지 않았다.

| 저장 cohort | T | 승리 | 저장 net bps |
|---|---:|---:|---:|
| Primary/Broad 공통 | 15 | 13 | 23,516.84 |
| Primary-only | 1 | 0 | −219.07 |
| Broad-only | 15 | 8 | 11,443.74 |
| underlying 합집합 | 31 | — | 중복 합산·전략 실적 주장 없음 |

공통15행의 entry/exit/gross/net/cost/reason은 전부 동일하다. OPPORTUNITIES.json31행과 DECISION_FEATURES.json31행에는 결과열을 넣지 않았고, OUTCOME_ANSWERS.json46행에 lane별 원래 결과를 보존했다. Timestamp에서 얻은 원래 session 분류는 메타데이터이며 스크린 결과가 아니다.

## 3. Stage0 차단의 근거

- 원본1000봉 수집 종료시각: Primary1787486400000, Broad1787313600000. 차이는48시간이며 Primary-only ETH long signal1787400000000은 Broad 범위 밖이다. 이 차이 자체로 공통 봉 가격이 다르거나 lookahead가 있었다고 단정하지 않는다.
- config SHA와 경제 비용 component 값은 같지만 원본 cost snapshot ID가 다르다. 전체 signed funding settlement rows는 원래 receipt에서 제거됐다.
- 원본 OHLCV·warmup·입력 content hash·전체 적격/탈락 signal tape와 실제 decision feature payload가 저장 receipt에 없다. 모든31 opportunity의 snapshot 및 실제 decision_ts는 null이다. native signal_ts를 실제 close/decision시각으로 바꾸지 않았다.
- historical evaluator는 독립 intent 경로를 계산했다. 저장행의 최대 동일종목 중첩은 Primary8/Broad12이며, 현재 chronological occupancy owner와의 동일 입력 증명이 아니다. 완료 거래만 재필터링해도 원래 제외·점유·미완결 신호가 복원되지는 않는다.
- 원본 Actions artifact9446790894/9493430326은 metadata상 존재·미만료이나 다운로드 참조의 로컬 전송이 HTTP403으로 실패했다. 바이트 해독0. 당시 workflow와 evaluator 원문은 역사 commit에서 회수했다. Primary artifact는 attribution summary 하나만 업로드하며 evaluator는 raw bars와 funding_rows를 receipt에 저장하지 않는다. Broad archive의 실제 내용은 확보하지 못했으므로 보았다고 주장하지 않는다.

따라서 **saved membership parity PASS / common input parity NOT_ESTABLISHED**다. 승인문 §4의 조건에 따라 경제실행을 차단했다. 현재 rolling봉·다른 DEV자료·fresh자료로 빈칸을 대체하지 않았다. 허용된 parent control2회도 원래 입력 부재를 해결하지 못하므로 사용하지 않았다.

## 4. 과거 시도와 Stage1

| 과거 축 | 확인된 상태 | 이번 처리 |
|---|---|---|
| PR1044: 3-bar persistence ADD_ONLY | 원본 Primary payload 부재 HOLD, PR미병합 | CI성공을 경제PASS로 해석하지 않음 |
| PR1052 V4: 방향에 맞는 연속3개 close delta | 양 lane preregisterable false, REJECT_3BAR_GATE_AND_ROTATE_TO_HTF_ALIGNMENT | 동일 predicate·기간 숫자변경 재시험 금지 |
| PR1052 V3: session/STgap/chase/ATR/geometry 단일 및 깊이≤2 조합 | 실행 이력 있음, 경제 terminal 미확인 | 신규 축으로 세지 않고 이력 보존 |
| Primary Keltner/Supertrend-BTC include/veto4cell | DROP_CELL_KEEP_PARENT_FALSIFIED | 같은 donor cell 재시험 금지 |

세부 predicate·원문 SHA·run/job 및 추가 exact-form 금지는 AXIS_HISTORY_AUDIT.json/md에 있다. lane 이력 파일이 비어 있어도 이전 시도가 없었다고 간주하지 않았다.

| entry feature family | Stage1 | admitted/rejected·경제지표 | survivor |
|---|---|---|---|
| session_state | NOT_RUN_PARENT_PARITY | 미평가 | null |
| st_gap_state | NOT_RUN_PARENT_PARITY | 미평가 | null |
| chase_state | NOT_RUN_PARENT_PARITY | 미평가 | null |
| atr_state | NOT_RUN_PARENT_PARITY | 미평가 | null |
| geometry_balance | NOT_RUN_PARENT_PARITY | 미평가 | null |
| directional/persistence | NOT_RUN_PARENT_PARITY | 미평가 | null |

6개는 feature inventory이며 소비한 스크린은0개다. ordinary/top10 winner retention, loss removal/clipped winners, DD contribution, regime concentration, prefix 판정도 gene별 미평가다. gate를 완화해 session 하나만 부분 실행하거나 과거 승리를 복사한 합성을 하지 않았다.

## 5. 역사 control 경제표 — 새로운 공통 partition FULL 아님

| 지표 | Primary 역사 control | Broad 역사 control | U1 / U2 |
|---|---:|---:|---|
| 완결 / 승리 | 16 / 13 | 30 / 21 | 미생성 |
| WR | 81.25% | 70.00% | 미생성 |
| 저장 완결 net | 23,297.77 | 34,960.58 | 미생성 |
| expectancy / T | 1,456.11 | 1,165.35 | 미생성 |
| PF | 64.50 | 60.81 | 미생성 |
| payoff | 14.88 | 26.06 | 미생성 |
| 원래 저장순서 closed DD | 219.07 | 413.79 | 미생성 |
| 저장 비용 2배 net¹ | 23,051.21 | 34,509.89 | 미생성 |
| 평균 승리 | 1,820.36 | 1,692.62 | 미생성 |
| 평균 손실 | -122.30 | -64.94 | 미생성 |
| 최악 거래 | -219.07 | -83.04 | 미생성 |
| 손실 하위10% 평균² | -219.07 | -83.04 | 미생성 |
| 독립 저장행 symbol-days³ | 27.42 | 44.21 | 미생성 |
| 최대 동시 독립 저장행³ | 11 | 17 | 미생성 |
| top1 양의기여 비중 | 11.62% | 7.74% | 미생성 |

손익 단위는 독립 거래 bps이며 계좌수익률이 아니다. 각 부모의 서로 다른 원래 capture 기간·표본·평가 의미를 유지했다. ¹ `sum(net)−sum(realized_cost)`인 저장비용 단순2배 산술이며 원본 signed funding 재현이 아니다. ² 손실집합 하위ceil(10%)로 양쪽1건. ³ 독립 full-unit 저장행의 보유기간 합/중첩으로 실제 포트폴리오 점유·노출 성능을 주장하지 않는다. DD는 원래 receipt 행순서의 완결손익만 사용하며 marked DD가 아니다.

U1/U2를 만들지 않았으므로 Primary winner retention, Broad-only accepted/rejected contribution, removed loser/clipped winner, new/displaced와 최종 Pareto 비교는 **해당 없음**이다. 위 Broad-only15건은 합집합 귀속이며 ADD_ONLY gate에 채택된 거래가 아니다.

## 6. 코드·검증·실행 회계

추가 코드: 순수 저장 원장 감사, 고정된 scope 검증기, 변조·중복·결과열·시각·0예산·handoff 검사, 모든 PR/master push에서 실행하는 읽기 전용 CI. 기존 정책·exit/risk/size·이전 이력은 수정하지 않았다.

| 항목 | 승인 상한 | 실제 소비 |
|---|---:|---:|
| Stage1 screen | 6 | 0 |
| canonical candidate | 2 | 0 |
| child FULL | 4 | 0 |
| 필수 parent control | 2 | 0 |
| retry/sweep/새 prospective decode/유료AI/주문/배포 | 0 | 0 |

검증 명령: `python -B -m unittest backend.research.rebuild.test_trendrider_unified_parent_audit_v1 backend.research.rebuild.test_trendrider_unified_saved_verify_v1 -v` 및 `python -B -m backend.research.rebuild.trendrider_unified_saved_verify_v1`; canonical frontend validate도 실행한다. 코드 검증은 saved arithmetic이며 경제실행 예산을 소비하지 않는다.

PR·리뷰·정상 병합·정확한 merge SHA 검증의 실제 결과는 후속 EXACT_MERGE_VERIFICATION.json에 결속한다. 이 보고서 생성 시점에는 아직 원격 완료를 주장하지 않는다. 이전 Squeeze84후보/152평가 및 완료결과는 그대로다.

## 7. 종료·handoff

**TrendRider Unified v1은 생성되지 않았다.** strategy digest=null, G5A handoff=NOT_CREATED, qualification/G5B boundary=null, formal credit0, G6권한 없음. Primary를 incumbent로 복귀시키거나 Broad를 최종 Unified로 재명명하지 않았다.

이 scope는 REPORT_ONLY로 닫으며 잔여 실행권한0이다. 조건부 미사용 예산은 소진한 것이 아니라 Stage0 hard stop으로 종료된 것이고 다음 작업으로 이월하지 않는다. 자동 tuning·추가 실험 없음. 배포 불필요. 되돌릴 범위는 이번 신규 감사코드·읽기전용 workflow·증거이며 기존 부모/운영본은 보존한다.
