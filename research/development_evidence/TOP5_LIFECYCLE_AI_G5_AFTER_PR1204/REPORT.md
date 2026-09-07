# TOP5_LIFECYCLE_AI_G5_AFTER_PR1204 — 실제 결과

Task task-f99748b09e83e58d. PR1204와 별도 승인 범위. 신규 후보42 TPP1 한 개, 기존41 보존. Gemini/OpenAI 실제호출0. G5 formal credit0. 코드/결과 보존이며 공식 전략 채택이 아니다.

## 경제표

고정명목 trade-bps, 계좌수익률 아님. DEV2025=2024-12-19 08:00Z–2025-12-29 08:00Z, native1h BTC/ETH,375일(376 UTC 날짜 bucket). 원래 데이터/비용/GOAL 고정. 2026 native1h 적격 원천 부재로 해당 기간만 NOT_RUN.

| 구분 | 청산/미완결 | 승률% | 평균승/평균손 bps | 손익비 | PF | closed E bps/T | 종료net | 전체cost2 | 평가DD | 최대연패 | 노출symbol-days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P | 412/0 | 23.54 | 350.24/-144.93 | 2.417 | 0.744 | -28.35 | -11678.36 | -19918.36 | 12263.05 | 14 | 387.04 |
| TPR1_FULL | 382/0 | 22.25 | 402.44/-142.81 | 2.818 | 0.807 | -21.48 | -8206.03 | -15968.03 | 12459.86 | 15 | 410.92 |
| FIXED | 412/0 | 26.94 | 304.96/-145.57 | 2.095 | 0.773 | -24.19 | -9966.90 | -18206.90 | 11693.50 | 14 | 369.50 |
| FULL | 436/0 | 27.06 | 317.24/-145.30 | 2.183 | 0.810 | -20.11 | -8769.82 | -17489.82 | 11824.23 | 14 | 390.46 |

이번 원장에서는 미완결0이므로 closed net=종료net, open mark=0. P/TPR1_FULL은 저장된 부모·보존작업본의 회수값이고 과거 경제를 재실행하지 않았다. FIXED/FULL 모두 REJECT: 절대net/E/cost2<0, PF<1, daily delta95 하한도 양수 아님.

## 보존 이득과 피해

P 대비 FULL net 증분 +2908.53459084; 최대 기여 거래 제외 +1878.69819988. 직접 FIXED 경로 +1711.46152319, 추가 점유/후속진입 잔여 +1197.07306764.

| 일반/큰 승리 | 부모 이익 | 보존 이익 | 보존율% | 이익 훼손 | 제외 승리 | 승리→손실 |
|---|---:|---:|---:|---:|---:|---:|
| ordinary_winners | 23168.93588334 | 20328.52467454 | 87.7404 | 2840.41120880 | 2 | 0 |
| large_winners | 10804.15529033 | 9778.60441117 | 90.5078 | 1025.55087916 | 1 | 0 |

| 거래 전환 | 건수 | 종료net 기여 | 비용 변화 |
|---|---:|---:|---:|
| ABSENT_C | 35 | 1734.80655013 | 700.00000000 |
| C_ABSENT | 11 | -537.73348249 | -220.00000000 |
| C_C | 401 | 1711.46152319 | 0.00000000 |

C_C 공통거래 +1711.46152319 + 신규35건 +1734.80655013 + 제외11건 −537.73348249 = +2908.53459084. closed/open 전환0. FULL 총비용+480bps는 이미net에 반영돼 있다. FIXED funding proxy−56bps는 floor reserve+56bps로 상쇄돼 총비용절감0이며 별도 이익으로 더하지 않는다.

보존작업본 TPR1_FULL 대비 TPP1 FULL net 증분 -563.79954784; 일반/큰승리 보존율 79.6078%/53.8806%. 초기SL/H48 고정이라는 이번 한 축은 연장형 TPR1의 수익을 모두 보존하지 못한다. TPR1도 함께 유지하며 자동교체/합성하지 않는다.

| 비교 | daily delta95 구간의 달력합 bps | 판정 |
|---|---|---|
| FIXED | [-1394.216405335677, 4227.573974939282] | REJECT |
| FULL | [-688.0313999037356, 6403.94644013549] | REJECT |

BTC/ETH 증분과 진입월·동시시장사건 집중, 동일달력 DD창, 일반/큰 승리 개별 경로는 DEV2025.json.gz에 모두 보존한다. 재사용 DEV·종목 상관·선택편향이 있어 독립 우위/유효표본 충족을 주장하지 않는다.

## 실행 규칙·비용 의미

Native Primary parent; initial SL/TP/entry/H48 inclusive49/cooldown unchanged. After surviving native exits and before original timeout, close j activates/raises long (lowers short) protection only if native direction agrees, close is strictly beyond line and signed line gain bps strictly exceeds max(20, frozen full roundtrip fee+spread+impact plus modeled accrued absolute funding through j). Frozen costs are ex-ante DEV scenario parameters, not historical observable quotes; no future funding count/rate. Monotonic level effective j+1 only; gap through active level fills actual open before new HLC; otherwise native SL first, TP second, protection touch third, original timeout close fourth. No extension, TP cap, new filter, stop widening, partial sizing or future outcome feature. Final-boundary censor accounting and actual exit-bar-open+native cooldown ownership preserved.

native 초기SL/TP/H48 inclusive49 및 exit-bar-open+cooldown을 유지. 이전완료봉 활성수준의 gap은 실제open, 같은봉 intrabar SL/TP/보호touch는 동결 native우선순위. SL봉 HLC는 활성입력으로 쓰지 않는다. 실제 장중순서·거래소상주손절/체결품질 증거는 아니다. 비용은 동결된 DEV 시나리오 가정이며 당시 실제 호가나 signed funding을 입증한 값이 아니다. 활성계산은 현재완료봉까지의 settlement count만 사용하고 미래 funding을 보지 않는다.

FULL 원래 적격신호1555개 모두 허용/실제점유차단 사유와 함께 보존. 진입436, 차단1119, 미완결0. 보호활성98건(BTC49/ETH49). 새 원형신호·진입필터·SL확대·레버리지·연장은 없다.

## Supertrend

NOT_RUN / DISTINCT_EXECUTABLE_H12_DISCRIMINATOR_NOT_ESTABLISHED. 원시DEV는 존재한다. 원래H12 손실124/40건이 남았다는 총량과 t−1 연장 관측만으로 실행 가능한 조기실패 판별조건이 성립하지 않는다. signal-low/공통BE/flip/ADX상승/한봉지연 실패를 반복하지 않았다. 새로운 숫자·지표를 만들지 않았고 조건부 후보 예산은 미사용 상태로 보존한다.

## 종료·API·KR3 계약

- lifecycle_task_v1.py: scope별 등록/재개/완료, 원자 잠금/예약, 동일identity 중복차단, 누적후보/API예산, 정확한scope/head/run 결속, 유한대기 UNKNOWN, task소유 정리 경계. T1~T8 포함21 합성테스트 PASS. API 소스hash 보강 뒤 관련4개만 재검증PASS. 플랫폼 UI/숨은 추론/Work 과금 종료는 검증범위가 아니다.
- g5_exit_ai_pilot_v1.py + 기존workflow: PR/push 검증에 secret 없음, 수동호출 기본false, dossier/source/price/model/상한 결속, 요청당45초, provider당1회, 총USD5예약, 재시도/fallback0, 미정산예약 보존. 현재 키없음/공식가격·토큰상한 미봉인/원격 영속예약owner미결로 실제API0. 합성가격은 실제 가격표가 아니다. 모델null, 정산$0, 미정산예약$0, billing=NOT_CALLED. Work UI 차감은UNKNOWN.
- DOSSIER는 이미 승인해 사용한 native 실패·SL전 관측과 정확한정책 소스hash만 전달한다. 역사16/30 재검산이나 관측원장/미사용holdout 입력없음. 외부AI 성과기여 없음.
- KR3_FORMAL_APPLICATION_DRAFT.json: 코드/기존결과·12개boundary key·9개reports·P0~P6·현재G5B owner 기계결속.16개미결에는 초기SL없는KR3의NetR분모, retention분모, W창/purge/embargo/runoff, 유효표본임계값과권한, 비용/체결원천 등이 포함된다. 구조/해시검사PASS이며 공식G5A/G5B미충족은 유지. 신규boundary/T/승격0.

## 실제 실행·보존

원격 결과전 freeze 12a3cac9eb40fd77760500fdf8ed1409a2c6ed78; SPEC 58c8875cedbfcc639f545eb98bd877f3ffbbdeb911e4a5a873244d8994800f3a. 후보42 TPP1, 이번1/2 사용, 누계42, Supertrend 조건부0. root 경제실행1명, 읽기검토1명, 과거41 재실행0. FIXED1/FULL1 완료; 필수 CI/master의 동일결과 재현은 후보추가로 세지 않는다.

필수 최종CI·정확한merge 재현 상태는 이PR의 비트리거 completion receipt에 결속한다. 이보고서 작성 시 W6만 미완료이며 마지막 실제 성공 확인 뒤 REPORT_ONLY로 전환한다. collector의 이후master를 쫓지 않는다. 운영파일/Q0/G5B/별도수집 보존; 배포·실주문·공식채택 없음.
