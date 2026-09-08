# PR1220 calendar/cache correction — two exact 2026 comparisons

Both are already-used DEV, equal-entry-notional trade-bps, not account returns or live futures proof.
Original 2025 results, failed attempts, rules, costs and native controls were not rerun or overwritten.

|2026 execution|Closed/open|Win %|Payoff|PF|Net including open mark|Cost2|4h marked DD|
|---|---:|---:|---:|---:|---:|---:|---:|
|D2 / FT2026.7|34/2|26.47|1.912|0.688|-2115.38|-2884.00|2982.91|
|HLHB / FT2026.7|25/1|60.00|0.136|0.204|-6867.00|-7634.13|8624.17|

## D2 independent engine differences
{
  "signal_differences": 0,
  "entry_differences": 0,
  "reference_differences": 0,
  "exit_differences": 4,
  "cost_differences": 0,
  "callback_errors": 0
}

Full first-difference details are in results/D2/RESULT.json.gz parity. Native timeout close versus FT next open remains explicit; no price overwrites.
Calendar repair is an integration repair, not new alpha. High win rate is not profitability. Existing G5A HOLD and all operational authorities stay unchanged.
Original signed funding, intrabar price order, live fills, margin and liquidation remain outside this offline research comparison.
Candidate count49 remains; exactly two new begun evaluations77/78. Old attempts73–76 remain intact, including failures74/76.
This report records economic work; final review/CI/merge closure is recorded separately.

## 해석과 완료 범위

2026의 비교 구현 오류는 이번 두 실제 실행에서 해소됐다. D2는 원시 신호126개, 공통 진입36개(완결34+미완결2), 참조예약과 공통 비용에서 원형과 일치한다. 진입은 모두 평가구간 안이고 콜백 오류0이다. 시간청산4건의 원형 종가/FT 다음 시가 차이만 남아 총손익이 -0.231390379577 trade-bps 다르다. 두 기간의 시간청산 가격 차이를 남긴 채 결과를 보고하며 완전한 체결 동일성은 주장하지 않는다.

이 차이로 기존 D2의2026 손실을 설명할 수 없다. 원형 -2,115.145562803371, 외부엔진 -2,115.376953182948 trade-bps로 같은 손실 구조가 확인됐다. 데이터 경계 오류 수선과 수익전략 개선은 다른 성과다. D2의2025 결과는 재실행하지 않았으며 기존 원문/원장 그대로다.

hlhb는2026 완결25건 중15승10패, 평균이익112.7772/평균손실829.4593bps다. 완결손익 -6,602.9345, 미완결1건 평가 -264.0624, 전체 -6,866.9969 trade-bps다. 비용 전 총손익부터 -6,099.8627bps로 음수이며 고승률 때문에 채택할 수 없다. 2025의73.08%/비용 후 -1,832.85 결과도 보존한다. 이번 고정 외부 원형은 두 기사용 기간 모두 연구비용 후 적자다. 이 결과를 모든 외부 봇의 성능으로 일반화하지 않는다.

18건의 hlhb 청산은 봉내 시각이 미관측이다. 상·하한 펀딩시각 가정만 바꾼 순손익 범위는 -6,866.9969~-6,863.9969bps다. 이는 실제 봉내 가격순서나 체결을 확인한 범위가 아니다. 수익률은 동일명목 거래-bps 합계, 위험은4h종가 평가합계이며 계좌수익률/계좌MDD/동일위험 비교로 부르지 않는다. 원래 signed funding·실체결·슬리피지·선물증거금·청산가 결손은 그대로다.

## 실제 수선과 재현

전체3,748봉으로 지표·원신호 좌표를 만든 뒤, 엔진에 넘기는 데이터만 잘라 D2는721행(원좌표3027부터), hlhb는751행(startup30 포함)으로 맞췄다. 지표를 짧은 구간에서 다시 계산하지 않았고 D2/hlhb의 진입·청산·SL·ROI·trailing 값은 변경하지 않았다. 콜백 무결성 위반은 한 번 발생하면 실행 전체를 즉시 중단한다. 정상 거래를 걸러 수익을 만드는 필터가 아니다.

사전 실제 FT 합성시험14개: 시작0/120/3028, 준비3028+평가720, 원좌표·지표 보존, 경계 밖 진입 거절, 첫 콜백 오류 중단, 다른 체크아웃 경로 및 원형 파라미터 보존. QA run34263219129/job102186081681 성공 후 실제 평가를 실행했다. old analysis의 임시 절대경로 스크립트는 봉인 기록으로 보존하고 이번 상대경로 모듈로 대체한다. 새 NOTICE가 오래된 미실행 문구와 없는 pin 파일 참조를 명시적으로 정정한다. 원래 봉인파일은 수정하지 않았다.

실제 실행 run34263686448/job102187635822. 규칙·코드 SPEC을 먼저 원격저장하고, D2는 e4f15834c01a52055461dc078e9b02c799795654, hlhb는 efb990cf23cccd9be55a87ae69ebd39d886a4d40에 각각 실행소유자·예산예약을 원격저장/읽기확인한 뒤 최초 한 번씩 실행했다. SPEC SHA256 f05b2765880b8b63adbf2837d0d105f6dca60d4eaf0bbc4d510380fd375a2254. 실행/미확정실패 기록을 지우거나 무료 재시도로 처리하지 않았다.

후보49 유지, 실제 평가76→78. 과거73~76(유효2/실패2)와 모든 이전 예산·판정은 보존된다. 이번 허용2/2 완료, 새 가설0, 신규 시세0, 미사용OOS0, 외부유료AI0, 실주문0. 엔진 설치와 CI의 플랫폼 비용이0이라고 주장하지 않는다. 최종 CI/리뷰/병합/고정병합본 검증은 별도 PR 완료 기록을 따른다. 완료 workflow는 저장결과 검증 전용이며 시장평가 재실행경로를 제거한다.

## 다음 경제적 판단

D2·KR3·Break·Q0와 이전 분기는 변경하지 않는다. 이번은 측정 결손을 마감한 것이지 새 수익개선/Survivor/G5A PASS가 아니다. D2에서 KR3 대비2026 훼손을 설명한 기존 원장은 재사용하며 또 같은 분해를 새 경제평가로 세지 않는다. 검증 주력 선정과 독립 경계·실전 운영 연결은 후속 범위이며 이번에 미사용자료 또는 주문 권한을 열지 않았다.
