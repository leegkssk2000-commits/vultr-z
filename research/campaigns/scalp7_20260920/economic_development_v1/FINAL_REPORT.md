# 선정 2가설·4 FULL 경제실행 최종 결과

범위: `G4_SCALP7_MATERIAL20_ECONOMIC_DEVELOPMENT_AFTER_PR1340_V1`. 승인한 경제실행은 **4/4 완료, 추가 실행 여유 0**이다. 살아난 후보·채택 후보는 0개이며, T·WR·Net 증가와 DD 감소를 동시에 달성한 child도 0개다. 이번 배치의 경제비교 완료와 G4 전체 완료는 다르다. PR #1340과 기존 판정은 보존한다.

아래는 **rolling 245일** 결과다. PnL·DD는 동일 원금 기준 거래 bps의 합이며 계좌 수익률 또는 평가손익 DD가 아니다. validation·rolling·fresh를 합치지 않았다.

| Identity | 실행 / 청산 | T | T/day | WR | Gross | Net 1x | Net/T | PF | DD | MaxLS | Net 2x |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SQ0 대조군 | 30m 문맥 → 15m 최초 진입 / 기존 30m lifecycle | 25 | 0.1020 | 48.00% | 1892.29 | 1520.49 | 60.82 | 1.912 | 576.67 | 3 | 1148.69 |
| SQ2 child | 같은 문맥 → 15m 두 번째 상승 시도 | 13 | 0.0531 | 46.15% | 423.31 | 230.43 | 17.73 | 1.465 | 171.06 | 3 | 37.56 |
| R15 새 대조군 | 30m GMMA·눌림 → 15m 진입 / 15m 구조 청산 | 2147 | 8.7633 | 21.66% | -1062.46 | -33115.78 | -15.42 | 0.675 | 37403.11 | 39 | -65169.10 |
| R30 child | R15와 같은 진입 / 30m 구조 청산 | 1970 | 8.0408 | 20.76% | -6256.79 | -35652.53 | -18.10 | 0.652 | 40086.92 | 41 | -65048.26 |

**Squeeze는 DD·손실 tail 개선에도 수익을 크게 훼손했다.** Net 변화 -1290.06, 동일 원인(origin)의 부모 승리이익 보존율 21.06%다. 부모 승리 그룹 기여 변화 -2713.39가 부모 손실 절감 +1423.33보다 크다. child 최대 승리 1건을 빼면 자체 Net은 -42.64다. 작은 표본(13건), validation 0건, session 이익 집중 84.25%를 포함하여 기존 parent 대체를 기각한다.

**Rider 30m 청산은 15m 청산보다 악화됐다.** Net 변화 -2536.74, DD +2683.81, 연패 39→41, 부모 승리이익 보존율 69.69%다. 부모 승리 그룹 변화 -15265.43과 손실 절감 +13892.28을 따로 보존했다. 비용 2x의 총 Net만 +120.84 덜 음수인 것은 거래 감소에 따른 비용 절감이며, 양쪽 모두 큰 손실이다. 두 새 Rider 모두 독립 수익 후보로 채택하지 않는다.

| 별도 validation 30일 | T | WR | Net 1x | Net/T | PF | DD | MaxLS | Net 2x |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SQ0 | 1 | 0.00% | -12.62 | -12.62 | 0.000 | 12.62 | 1 | -27.87 |
| SQ2 | 0 | N/A | 0.00 | N/A | N/A | 0.00 | 0 | 0.00 |
| R15 | 296 | 22.30% | -5608.46 | -18.95 | 0.512 | 5912.53 | 24 | -10029.07 |
| R30 | 267 | 19.48% | -5575.81 | -20.88 | 0.537 | 5986.31 | 38 | -9565.72 |

validation도 이미 관찰한 개발 이력이며 새로운 OOS/fresh 증거가 아니다. SQ2의 무거래를 검증 성공으로 취급하지 않는다. Rider validation 총 Net +32.65의 작은 차이에도 WR·Net/T·DD·연패는 악화됐다.

기존 Rider와의 비교는 별도 참고다. 아래 기존 수치는 저장된 원장만 읽었으며 FULL을 반복하지 않았다.

| Rolling 참고 | T | WR | Net | Net/T | PF | DD |
|---|---:|---:|---:|---:|---:|---:|
| 기존 Rider 15m impulse/pullback/reclaim V2 | 4358 | 22.28% | -57549.68 | -13.21 | 0.682 | 58693.85 |
| 새 R15 | 2147 | 21.66% | -33115.78 | -15.42 | 0.675 | 37403.11 |
| 새 R30 | 1970 | 20.76% | -35652.53 | -18.10 | 0.652 | 40086.92 |

새 구조의 총 손실·DD 감소는 거래 수의 큰 감소와 함께 나타났고, WR·Net/T·PF는 개선되지 않았다. 여러 entry 구조가 동시에 바뀐 기존→새 비교로 GMMA 단독 효과를 주장하지 않는다. 기존 Squeeze 30m 저장 결과와 SQ0의 이번 실제 실행 결과는 이 이력에서 일치했다. 상세 출처·해시는 [SAVED_BASELINES.json](SAVED_BASELINES.json)에 있다.

원문 규칙과 연구용 선택을 구분했다. [Guppy GMMA 설명](https://www.guppytraders.com/gmma-info)의 단기·장기 집단과 압축/추세 문맥, [Brooks 용어집](https://www.brookstradingcourse.com/price-action-trading-terms-glossary/)의 두 번째 시도 개념을 검토했다. 이를 사용하는 구체적인 EMA 초기화, candle 사건 순서, TTL, pivot 확인 및 실행 지연은 동결한 **연구용 architecture**이며 저자의 수익 시스템을 그대로 재현했다고 주장하지 않는다. 원문 예상 사례→구현 결속→독립 검수는 [audits](audits)에 있다.

네 규칙은 경제결과를 보기 전 **2026-09-20 08:54:21.689821 UTC**, commit `c81437af1c29dbea1f7b6c0ea7d462d57c2b45fb`에 함께 동결했다. [BATCH_SELECTION.json](BATCH_SELECTION.json), [freezes](freezes), [EXECUTION_RECEIPT.json](EXECUTION_RECEIPT.json), [EXPORT_REGISTRY.json](EXPORT_REGISTRY.json)이 2가설·4 identity·4회 한도와 완료를 연결한다. 과거 실패 실험·27개 감사는 반복하지 않았다.

검증 자료는 실제 6개 symbol의 2025-09-15~2026-09-15 원자료다. 최초 90일 문맥, validation 30일, rolling 245일/9창을 분리했다. 2026-02-13 20:32~20:35의 4개 missing minute를 gap으로 보존했고 synthetic fill·L2를 만들지 않았다. 새 24개월 자료, 새 fresh 경계 및 서비스 변경은 없다. cost 2x는 동일 저장 체결의 비용 산술 비교로 추가 FULL에 해당하지 않는다.

Squeeze의 13개 매칭은 **같은 원인에서 진입 시각이 달라진 거래**다. exact-time 비교의 0 common/25 missed/13 added를 13개의 독립 신규 기회로 오해하면 안 된다. Rider의 전체 4378개 발생 신호는 identity·청산 timeframe 외에 동일하다. rolling 완료 거래 차이는 보유·점유 경로에서 발생했다: 완료 position 점유 차단 710→832, 미완결 점유 차단 56→110. 각 Rider의 window 종료 경계 완료 거래 1건은 엄격한 구간에서 제외했다. rolling 미완결 10/11건과 validation 4/4건에는 실현 손익을 부여하지 않았다.

[ECONOMIC_REPORT.md](ECONOMIC_REPORT.md)와 [ECONOMIC_COMPARISON.json](ECONOMIC_COMPARISON.json)은 tail·보유시간·월/심볼/session 집중도·최대 승리 의존도·창별 양수 비율·cost 1x/2x 전체 지표와 귀속을 담는다. 독립 검산은 실제 체결가격의 gross, 비용, 구간 경계, 점유, 동일 원인 매칭을 별도 표준 라이브러리 계산으로 확인했다. 네 identity의 gross 재계산 오차는 0 bps다. [독립 검산 기록](audits/SAVED_ARITHMETIC_INDEPENDENT_REVIEW.json)의 PASS는 계산 일치이며 전략 승격이 아니다.

현재 Top7·재료20의 공식 판단은 [PR #1340 고정본의 두 상태표](https://github.com/leegkssk2000-commits/vultr-z/blob/41535742994ee7d442375cc0d1b34325213f5736/research/campaigns/scalp7_20260917/source_fidelity_v1/CURRENT_TOP7_AND_MATERIAL20_STATUS.md)를 유지한다. 옛 Active5 1h·TrendRider Broad·구 G4/G5 성과를 이번 Scalp7에 합치지 않는다.

| 이번 배치의 판정 | 결과 |
|---|---|
| 새 후보 채택 / 실패에서 살아난 후보 | 0 / 0 |
| T↑·WR↑·Net↑·DD↓ 동시 달성 child | 0 |
| 재료20 신규 경제실행 / C→B / B→A | 0 / 0 / 0 |
| B×B fusion | 시작 불가; 독립 B 최소 2개 요건 미충족 |
| 새 7개 포트폴리오 경제실행 | 없음; 기존 parent·정책 유지 |
| 기존 equal-seven 저장 참고 | T/day 16.3388, Net 1x -4325.71, Net 2x -9464.81, PF 0.7352, DD 4669.53 |
| 기존 adaptive 저장 참고 | T/day 2.4571, Net 1x -5016.15, PF 0.729, DD 5620.18 |
| 이번 네 identity의 fresh T | 0 |
| 주문 / LIVE / 공식 승격 | BLOCKED / BLOCKED / 금지 |
| G4 전체 완료 | 아니오 |

기존 portfolio 수치는 이전 저장 결과의 참고이며 새 네 identity를 합산해 만든 포트폴리오가 아니다. 다른 lane으로의 강제 대체 주문도 없다.

남은 미확인은 독립 fresh 성과, 작은 Squeeze 표본의 일반화, 실제 microstructure 자료 및 기존 source clock 정상화다. 이번 후보의 과거 전체 실행을 막는 자료 장애는 없었다. 다만 [최종 서비스 관찰](recovery/FINAL_SERVICE_WITNESS.json)은 fresh snapshot 변경 재시도와 fresh 종료 0건, micro raw unit failed/PID 0, micro clock WAIT_SOURCE_CLOCK_ADMISSION, paper snapshot 재시도 상태를 기록한다. unit이 active라는 이유로 정상 fresh라고 주장하지 않았다. 이번 승인 밖의 서비스 복구·재시작은 실행하지 않았다.

변경 범위는 신규 연구용 Squeeze/Rider 규칙, 한도·동결 검증 runner, 저장 결과 reporter, 독립 사례·회귀 테스트, 저장 결과 CI와 이번 campaign 증거다. 기존 parent·주문 경로는 수정하지 않았다. 검증은 Scalp7 **943 tests PASS**, normal pre-commit hooks PASS, frontend validate PASS이며, 병합·CI·병합 고정본 검증 영수증은 해당 PR 및 Issue #1334에 연결한다. 경제결과의 한계는 이미 관찰한 개발 자료, 실현 bps 기반 DD, gap 및 미완결이다. 배포는 불필요하다. 통합 문제 시 이번 연구 변경 PR만 revert하고 원본 결과·동결 증거는 보존한다.
