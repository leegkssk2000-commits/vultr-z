# Exact PR1213 D: reused 2026 expansion

Exactly one new FULL: D-SEEN2026. D-DEV2025 and both KR3 periods are saved results, not rerun.
Equal-notional trade-bps, not account returns. Both periods are reused DEV; no independent OOS or G5A PASS.
Original D admission, sixth observed-bar recheck, shifted reference/exit anchors and no initial SL/fixed TP are unchanged.

|Period|Rule|Closed/open|Win %|Payoff|PF|Terminal net|All-cost2|Marked DD|
|---|---|---:|---:|---:|---:|---:|---:|---:|
|DEV2025|KR3|202/1|41.09|1.825|1.273|10265.00|5744.23|11727.79|
|DEV2025|D|108/0|45.37|2.326|1.932|16354.20|13904.99|5227.94|
|SEEN2026|KR3|75/4|33.33|2.853|1.426|4746.58|3002.13|4093.69|
|SEEN2026|D|34/2|26.47|1.854|0.667|-2333.54|-3111.36|3044.35|

Full origin-state/winner/open/concentration/same-calendar reconciliation is in ACCOUNTING.json. No costs are added twice.
Candidate hypotheses45 preserved; actual evaluations63→64. Selecting an already tested D as development parent does not rewrite the PR1213 diagnostic record.
New market requests0, unused OOS reads0, paid provider calls0, orders0. Formal G5A/G5B states unchanged.
Remote CI/merge closure is recorded separately; this measured report does not claim those are already complete.

## 결과 해석과 개발 판정

**정확한 D의 기사용 2026 확대는 경제적 우월성을 확인하지 못했다.** D는 이번 사용자 선택의 개발 기준본으로 보존하지만, 원형 KR3의 운영본이나 G5A/G5B 검증본을 교체하지 않는다. 2025의 45.37%는 해당 DEV 표본의 결과이며 다른 기간의 보장 승률이 아니다. 이번에는 D2·E 이식·파라미터 변경을 실행하지 않았다.

2026 D는 완결 34건 중 9승·25패다. 완결 순손익 -2,402.89, 미완결 2건의 가상 청산비용 포함 평가 +69.35, 합계 종료손익 -2,333.54 trade-bps다. 비용 2배 종료손익은 -3,111.36이다. 평균 승리 +535.65 / 평균 손실 -288.95 bps로, 적은 진입만으로 손실을 피하지 못했고 원래 KR3보다 승률과 손익비도 낮아졌다.

2026 D의 평가낙폭은 3,044.35로 KR3의 4,093.69보다 25.63% 작았다. 그러나 보유노출도 148.17에서 61.83 symbol-days로 줄었고 순손익은 양수에서 음수로 바뀌었다. 이를 위험조정 우월성이나 동일위험 비교의 성공이라고 부르지 않는다.

## 동일 원신호 기준 2026 손익 차이

|KR3 → D 구성|종료손익 증분 trade-bps|
|---|---:|
|공통 완결/미완결 기회 변화|-3,253.17|
|제외된 원래 기회 합계 효과|-3,561.29|
|신규 기회|0.00|
|완결/미완결 상태 전환|-265.66|
|전체|-7,080.11|

반올림 전 공통·제외·신규·상태 전환 합계는 전체 종료손익 차이와 일치한다. 제외된 미완결의 평가값은 실현 회피손실로 부르지 않고, net에 포함된 비용을 다시 더하지 않는다. 이 표는 저장 원장의 회계분해이며 진입시점·재심사·청산기준 각각의 유일한 인과효과는 아니다.

## 기존 승리 훼손과 집중도

2026 기존 KR3의 완결 승리 25건 중 D에서 14건은 미진입, 5건은 손실, 1건은 미완결, 5건은 완결 승리로 남았다. 전체 D 승리 9건 중 나머지 4건은 KR3 손실에서 승리로 전환됐다. 원래 양수 이익까지만 인정한 승리 이익 보존율은 11.95~15.00%, 기존 큰 승리 상위 3건의 이익 보존은 0%다. 이 상·하한은 미완결을 포함한 capped 원래 이익 회계 범위이지 미래 수익의 신뢰구간이나 공식 G5 retention 기준이 아니다.

2026 KR3 대비 전체 -7,080.11 중 HYPE 기여는 -9,494.71 trade-bps였다. 저장된 양쪽 손익에서 HYPE 기여를 빼면 증분은 +2,414.59다. 이는 특정 종목 기여에 매우 민감하다는 진단일 뿐, HYPE를 뺀 전략을 새로 재생하거나 종목 제외를 채택한 결과가 아니다. 2025 D의 KR3 대비 HYPE 기여는 +4,577.58이었으므로 두 기간에서 기여 방향도 바뀌었다.

후속 개발에서 살펴볼 부분은 D의 실제 진입·대기·청산 경로가 기존 큰 승리를 잃은 이유다. HYPE 이름이나 특정 연도·결과를 실행조건으로 쓰지 않는다. 이 결과를 보고 B·E로 부모를 자동 변경하거나 2025 D와 2026 KR3/E를 사후 선택해 합성하지 않는다. 추가 수정 후보는 이번 범위에 포함하지 않는다.

## 검증 범위와 실행 기록

- 원래 D와 모든 native 매매 의존성은 PR1213 봉인 해시와 일치한다. 원래 신호 적격성, 6개 관측봉 대기, 후속 상단절반 재심사, 이동한 참조 예약·저가/보유/연장 기준을 모두 유지했다. 관측봉 6개를 무조건 달력 24시간으로 재정의하지 않는다.
- 사용 자료는 PR1215의 같은 SEEN2026 prefix 7종목×3,748행이며 준비봉 3,028행과 평가범위 720행을 구분한다. 공식 원천 ref 및 input/policy/cost hashes는 SPEC과 준비 기록에 있다. 과거 파일의 원래 partition 이름과 무관하게 전체 기사용 연구임을 유지한다.
- 실제 신규 FULL은 D-SEEN2026 한 번뿐이다. 원격 선동결 commit 92bae68c68eca8740939a5805412daa00f7aab22, SPEC 4c29ba0cdd32370bdf2315783656324d2bcdb510d3bf0b39c3c486a26ebfc4b6, run 34217548491 / economic job 102032841071 success다. 원장은 결과 commit 4bd714a3e8e46679773b2cf2ee41583286d8295f에 보존됐다.
- 신규 범위 시험 8개와 기존 인과 경계 합성시험 18개는 경제 결과 전에 로컬에서 통과했고, 원격 verify job 102032778035는 해당 신규 8개와 frozen code 검사를 통과했다. 합성시험은 경제 표본으로 세지 않는다.
- 후기 보고 문구·CI·병합 확인으로 기존 경제결과를 다시 실행하지 않는다. 후보 가설 45건은 유지하며 실제 평가만 63→64건이다. 개발 기준으로 기존 진단 D를 선택한 이력을 보존하고, 새로운 매매 가설처럼 번호를 중복 부여하지 않는다.
- 기존 비용모형은 fee/spread/impact/absolute funding/20bps floor의 연구 proxy다. 실제 거래소 체결·당시 signed funding의 증거로 격상하지 않는다. 최초 상주 보호SL·고정TP가 없는 연구 의미도 그대로다.
- G5A HOLD, 독립검증 접근권·예약·기존 관측기·다른 수집기는 그대로다. 외부 제공자 호출0, 신규 시장 수집0, 미사용 OOS 접근0, 실주문0. 배포 불필요.
- 결과 파일 생성·코드 병합 완료와 경제적 성공을 분리한다. 최종 CI·병합·병합본 verification 및 정상 종료는 별도 PR 완료 기록을 따른다.
