# Work D 완료 — 저장 원장 공백·충돌·추가기여 집계

scope_key: `ZEL_WORK_D_PORTFOLIO_OPPORTUNITY_CONTRIBUTION_20261021_V1`
경제 owner: `CLOUD_WORK_COORDINATOR_ISSUE1358_V1` 보존.
저장 branch: `work/zel-portfolio-coverage-20261021`; 기반 ref: `3f4a798f15fbb3a21f3f6063db1b063b95d182e0`.
이 파일이 포함된 정확한 제출 commit은 해당 브랜치의 단일 `[skip ci]` 제출 commit이다. 소비 owner는 실제 사용한 commit을 자기 소비원장에 기록한다. D는 소비원장을 수정하지 않았다.

## 실제 결과

공통 사용 DEV: `[2026-01-13T00:00Z, 2026-09-15T00:00Z)`. K126은 보유연장 identity, S25는 부모 identity의 rolling만 사용했다. S validation 1건은 제외했다. 입력 gzip SHA 2개, 비용 원본 SHA 및 추가 reserve 근거 SHA가 일치했다.

| 저장된 진입시각 집계 | UTC | Europe/Berlin |
|---|---:|---:|
| 분모: 교차하는 모든 날짜 | 245일 | 246일 |
| 진입 / 완료 | 151 / 151건 | 151 / 151건 |
| 진입 있는 날 / 없는 날 | 54 / 191일 | 53 / 193일 |
| 평균 / 중앙값 | 0.616327 / 0건 | 0.613821 / 0건 |
| 3회 이상 / 4회 이상 | 18 / 10일 | 20 / 14일 |
| 3회 미만 | 227일 | 226일 |
| 최장 무진입 | 30일 | 30일 |

최장 공백은 양쪽 달력 모두 **2026-07-16~2026-08-14**. Berlin 관측범위는 1월13일 01:00~9월15일 02:00이며 첫 날짜 23시간·마지막 날짜 2시간을 포함한다. 3월29일은 DST로 23시간이다. 실제 경과시간은 두 집계 모두 245×24시간이며 Berlin 경과24시간당 평균은 0.616327건이다. 부분 날짜나 무거래일을 분모에서 제거하지 않았다.

K 방향은 long47 / short79건, S는 long25 / short0건이다. 이 과거 방향을 유지했으며 현재 매매 권한을 확대하지 않았다. 독립 신호 전체 원장/공통 opportunity ID가 없어 **독립 기회 수는 UNKNOWN**이다. 이름을 무시한 symbol·side·signal-time proxy는151개이며 독립 기회 인증이 아니다.

## S가 K에 더한 날짜와 충돌

UTC/Berlin 모두 추가 날짜는 **7일**: 03-04, 03-24, 06-15, 07-03, 08-27, 09-03, 09-11 (2026년). 같은 진입일은8일이다.

| 종목 | K 진입 UTC | S 진입 UTC | 동일방향 보유 중첩 |
|---|---|---|---:|
| SOL | 08-20 15:30 | 08-21 02:00 | 90분 |
| ETH | 08-20 15:30 | 08-21 02:00 | 120분 |
| ETH | 08-21 13:00 | 08-21 20:00 | 180분 |
| LINK | 08-21 13:00 | 08-21 19:30 | 210분 |
| DOGE | 08-21 00:30 | 08-21 21:00 | 180분 |
| SOL | 08-21 14:00 | 08-21 22:00 | 330분 |
| LINK | 09-04 02:00 | 09-04 09:00 | 240분 |

교차전략 보유 충돌7쌍, 반대방향0쌍, 교차전략 동일 신호시각0그룹. 전체 묶음의 동시 신호시각은19그룹이다. 비용1x 최종손실 거래끼리 보유가 겹친 경우는17쌍, 같은 outcome 가용시각에 손실이 알려진 경우는7묶음이며 모두 전략 내부다. 이 사후 손실 표시는 보유 중 MTM 손실이나 과거 진입 feature가 아니다. 모든 행의 정확한 identity·signal/entry/exit/outcome 시각은 CONTRIBUTION.json에 있다.

## 손익 기여의 범위

모든 수치는 **동일 명목 거래 합산 trade-bps**, 계좌 %가 아니다. 2x는 동일 저장 거래의 비용만2배다.

| 구분 | 거래 수 | Net1x | Net2x |
|---|---:|---:|---:|
| K 단독 기존 DEV | 126 | 7925.822289 | 6032.799140 |
| S 단독 기존 DEV | 25 | 1520.491493 | 1148.688767 |
| 제한 없는 별도원장 합계 | 151 | 9446.313782 | 7181.487907 |
| K와 같은종목 보유 중첩이 없는 S 부분집합 | 18 | 8.646149 | -258.975910 |
| 실제 공동계좌 추가Net / NAV / MTM DD | 미측정 | UNKNOWN | UNKNOWN |

마지막 S18행은 충돌 분해용 기술통계이며 선택된 포트폴리오나 greedy 백테스트가 아니다. 기존 K 보유연장 수익이 D 작업으로 새로 발생한 것도 아니다. K의5.4 trade-bps 추가 funding reserve는 원장 cost에 이미 포함되어 중복 차감하지 않았다. 실제 역사 funding·개별 부분청산 cashflow를 새로 재구축하지 않았다.

## 실행·후보 소비 계약

저장소 root에서 다음 명령을 실행한다. 표준 Python 3.10+와 시스템 IANA timezone 자료만 사용하며 설치·시장자료·API가 필요 없다.

```bash
python research/campaigns/scalp7_20261021/portfolio_coverage_v1/work_d/contribution_report.py --manifest research/campaigns/scalp7_20261021/portfolio_coverage_v1/work_d/INPUT_MANIFEST.json --repo-root . --out-dir /tmp/zel-work-d-readback
python -m unittest discover -s research/campaigns/scalp7_20261021/portfolio_coverage_v1/work_d -p 'test_*.py' -v
```

24개 인공 시험 PASS. 동일 신호/반대방향/이름변경/부분체결·청산/DCA/handoff/대기·미청산/빈 날짜/경계/DST/지연 outcome/미래손익 불변성/후보 기여/입력 SHA·identity·partition·비용 오류를 검증했다. exact code·test·manifest SHA는 VALIDATION_RECEIPT.json에 있다.

새 후보는 기존 owner가 생성한 **완료 lifecycle 원장 + 미결·대기 행**을 INPUT_CONTRACT.md 형식으로 새 manifest에 추가한다. baseline_labels=[K,S]를 유지하면 candidate_contribution에 기존 묶음 대비 추가 날짜·중첩·단순 Net·비중첩 부분집합 Net이 출력된다. 신규후보 입력/경제실행은 이번 D에서0건이며 예상 숫자를 채우지 않았다.

DAILY_COVERAGE.csv는 매 날짜의 진입·완료·outcome 가용시각별 손익, STRATEGY_DAY_SYMBOL.csv는 전략×날짜×종목이다. 일반 입력에서 일별 known Net은 carry-in의 종료손익도 포함하지만 총 economics는 기간 내 진입 cohort 기준이다. 이번 K/S에는 carry-in이 없다.

## C / 경제 owner에게 넘길 기술통계

평균3~4회 목표 총수735~980건 대비 현재151건이므로 **584~829건 부족**하다. 매일3회 충족과 평균3회를 혼동하지 않는다. 4월30일 중29일, 5월31일 중28일, 7월31일 중27일에 저장 진입이 없다. 시간대별 분포와 모든 월·빈 날짜는 출력에 보존했다. 거래 없는 날의 시장 국면 타임라인은 없으므로 특정 국면 실패를 추정하지 않는다. 이 날짜를 골라 학습하거나 승리 월 whitelist로 쓰지 않는다.

SELECTION_TABLE.csv에 기존 K/S와 서로의 추가 기여를 연결했다. 신규 최종 순위에는 단독 비용후 경제성·독립검증, 공동 추가Net, 추가 유효진입·날짜범위, 동시손실·DD가 함께 필요하다. 임의 가중점수·상관 cutoff는 없다.

기존 scalp7_portfolio_v2.route는 고정7개 연구 sleeve 전용이며 K/S 공동계좌 엔진이 아니다. 정확한 함수 입력과 미결속 risk SSOT는 EXISTING_ENGINE_BINDING.md 참조. 전체 가격경로·공동 자본/점유·상태 변경으로 생기는 반사실적 진입/청산은 기존 owner의 다음 공동 비교 범위다.

새 FULL/시세 실험/워크플로 dispatch/주문/배포 **0건**. A/B·C·원형·경제 원장·OWNER/CHECKPOINT·master·다른 branch 변경0건. 롤백이 필요하면 이 D 제출물을 소비하지 않으면 되며 기존 결과 삭제·재실행은 필요 없다. GitHub Actions 배포는 실행하지 않는다.
