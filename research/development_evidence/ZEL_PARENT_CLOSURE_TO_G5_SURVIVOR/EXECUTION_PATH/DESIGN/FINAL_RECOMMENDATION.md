# STEP7 정식 설계 타당성 — 비활성 최종 권고

**권고: 기존 11항목을 지금 일괄 승인·가동하지 않는다.** 현재 30일×3과 효과·검정력 설계가 일치하지 않으며, 유효한 regime control 정의도 미결이다. 코드 생산기 완성은 계속 가능하다. 기존 KR3 원형·TRADEOFF·경제 문턱을 바꾸지 않는다.

## 실제 계산과 명확한 적용성

정식 G5 공유계약은 `net_r>0`을 요구하지만 보호SL 존재나 위험R 분모를 직접 명세하지 않는다. `terminal_receipt_passes`는 numeric 값을 검사한다. Governance의 risk/stop never_exempt와 기존 DEV protective_stop_fixed를 보호SL을 새로 넣으라는 권한으로 해석할 수 없다. 따라서 no-SL 때문에 영구적격불가라고 단정할 근거는 없지만, no-SL cohort와 NetR 의미의 정식 승인이 없는 현 상태는 적격이 아니다. ATR통계R은 별도 `statistical_atr_r`; 기존 `risk_R`/`net_r`를 대체하지 않는다.

| 고정 DEV 설계 계산 | 실제점유만 | 실제+참조+UTC signalday 원안 |
|---|---:|---:|
| 분석 달력(일) | 375.0000 | 375.0000 |
| actual 거래행(미완결포함) | 203 | 203 |
| 완료 components | 43 | 36 |
| 검열 components | 1 | 1 |
| 최대 component 거래행 | 22 | 35 |
| sigma(구성요소별 평균 net trade-bps) | 458.2236 | 352.3722 |
| 30일당 완료 평균 | 3.4400 | 2.8800 |
| 30일 전체창 완료 범위 | 0–7 | 0–5 |
| W1/W2/W3 각각 필요한 N (5bps 효과차) | 90,999 | 53,813 |

375일의 이미 사용한 DEV 한 파일을 사전 동결하여 1회 계산했다. 거래 score/PF/승률 재감사나 경제 재생이 아니다. Reference 노드는 연결 근거일 뿐 0손익 거래가 아니다. Open 및 검열은 제거하지 않는다. 새 경제성과나 독립성이 입증된 N으로 보고하지 않는다.

검정 식의 sigma와 효과는 모두 **component 안 trade-net-bps의 평균** 단위다. 기존 `N=ceil(((z(1-alpha)+z(power))*sigma/5)^2)`는 H0≤0/H1=5 또는 H0≤5/H1=10인 **5bps 차이**를 계획한다. 최종 CI lower>5를 유지하면서 H1=5에서 power80%를 요구하면 유한 N은 없다. 53,813은 H0≤5/H1=10의 정규근사다. t분포·의존성·꼬리 및 sigma추정 오차를 포함한 보장값이 아니다.

원안의 완료속도 36/375일을 단순 적용하면 1개 창의 53,813개에 약560,552일이다. 미래예측이 아니라 **90일 가동 승인을 권고할 수 없는 규모 차이**다. Control 차이의 분산은 후보 자체 분산과 다르므로 이 N을 4개 paired control에 복사하지 않는다. 30일 경계에서 실제/참조 점유를 초기화하지 않았다. 합성 연쇄중첩100행→1component 반례도 시험했다.

## 원안 11항목과 변경 권고

| 항목·상태 | 기존 확정 / 원안 새제안 | 권고·이유 | 단위·계산 owner | 권한·데이터·달력·비용 |
|---|---|---|---|---|
| R_and_no_protective_SL / 기존 확정+새제안+미확인 | KR3 초기SL=None/TP=None 및 shared net_r>0. 공유계약은 보호SL 존재나 R분모를 정의하지 않음. governance risk/stop never_exempt는 유지. / ATR20 통계정규화 R를 net_r에 사용하고 no-SL formal cohort 예외 허용. | 원형 비주문 구현은 유지. statistical_atr_r 별도 namespace만 기록; risk_R 및 기존 net_r는 승인 전 null. no-SL 정식 cohort 적용/NetR alias는 정확한 승인권자가 결정. 무보호SL 때문에 명시 조항상 영구불가라는 단정은 근거 없음. 현재 applicability blocker는 계약의 no-SL/NetR 의미 승인 부재. | dimensionless statistical_atr_r; account-risk R 아님 / g5_g14_shared_validation_contract_v1.json:g5_terminal_gate.economic_window_thresholds; g5_g14_generation_controller_v1.py:terminal_receipt_passes; g5_g14_governance_contract_v1.json:effective_development_objective.never_exempt | 정식 semantic authority; no-SL 비주문 예외와 live protection 별도. SL추가·실계좌 sizing 금지. / 데이터 추가 없음; formal 활용권한 없음 |
| retention_baseline / 기존 확정+새제안 | 공유 retention>=60%; KR1_FULL 직계부모와 실제 FULL 점유 보존. / KR1 양수closed D를 분모로 capped child profit; child open bounds. | 같은 calendar/universe/cost에서 KR1/KR3 각각 FULL. 미진입0은 profit contribution이며 zero trade/win 아님. Open bounds 또는 D=0이면 unavailable. 원형정의와 일치하나 새로운 분모/귀속 authority 필요. FIXED 목록 교체 금지. | % retained parent positive trade-bps / kr3_evidence_adapter_v1.approval_bundle; proposal retention_baseline | retention분모·cohort attribution approval / 추가 parent FULL replay는 승인된 한 독립묶음 내부에서만 |
| windows_review / 수정권고 | W1선택 W3까지 동결, 창별 기존경제gate 유지. / 30calendar days ×3, W3+7d한차례 review/runoff. | 현재안 formal 가동 비권고. 30d는 DEV 완결component 0~5, 평균2.88 vs 각창필요53,813. 유효N에 맞춘 estimand/자원/고정review 신규명세 먼저 결정; 기간이나 gate를 결과후 변경하지 않음. 375d 기존DEV 발생속도는 미래보장이 아니지만 현 power설계와90d의 크기차 명백. | 30d×3=90d G5A; +최대7d runoff; 이후fresh G5B 별도 / step7_design_feasibility_v1.summarize_components | window/review authority, source 지속수집예산 별도 / 기존90d artifact는 최소97d조차 못덮음; G5B기간은 추가 |
| purge_embargo_runoff / 기존 확정+수정권고 | 실제 label/reference overlap 제거; open을 강제종료하지 않음. cap24는 observed index. / actual training end 이후96h embargo;7d runoff deadline. | embargo를 leakage분리시간으로만 사용하고 liquidation시각으로 쓰지 않음. 7d기한에 미완결이면 INSUFFICIENT. 실제reference end 포함. 숫자는 새승인 필요. gap 또는 늦은 next-open으로 cap24!=96h. 실제+참조 연결로 완결component43→36 감소. | 96h embargo; 24observed4h bars;7calendar days / keltner_kr3_v1.path; keltner_opportunity_reservation_adapter_v1; design component code | purge semantics와runoff termination 승인 / N감소; 미완결제거로 성과 개선 금지 |
| regime_shock / 수정권고 | 공유 N_effective는 same source bar/market shock 독립으로 중복계수 금지. / UTC signalday + any transitive actual/reference overlaps;EMA50slope×DEVmedianATR regime. | 실제 연결결과를 의존성보수 진단으로 보존하되 증명된 iid shock으로 간주하지 않음. reference는 경제sample0. 연쇄상관 및 effective 독립성 가정 검토없이 formal N 할당 금지. 203행→37component(완료36/검열1), 최대35거래/묶음. 합성100연쇄행은1component. 평균수익 estimand가 component당trade평균으로 바뀜. | components, trade count, UTC ms; label only / step7_design_feasibility_v1.components; shared independence_audit | market dependency unit과regime code/frozenDEVthreshold 승인 / 형식적 iid 가정금지; 긴중첩은 N=1까지축소가능 |
| effective_N_minimum_effect / 수정권고 | 공유 numeric N threshold=null;6/12T는 terminal 아님. / delta5bps;beta=.2;normal power식;final one-sided t lower>5. | 원안의H0/H1모순수정 필수. lower>5 유지시 H0<=5,H1=10처럼 명시적5bps gap을 승인해야 N53,813/창. H1=5에서80%power는 유한N 없음. 이번수치는 타당성계산으로만 남기고53,813을 자동formal gate로 설정하지 않음. sigma352.372159bps/component mean;alpha.05/7. 독립성/tail/variance불확실성이 있어N는정밀보장아님. pairedcontrol차이sigma는 별도로필요. | N complete components;mean net trade-bps/component;80%power / step7_design_feasibility_v1.required_n | estimand,H0,H1,varianceunit,terminaltest authority / DEV속도 산술560,552days/창; 자동장기수집/예산승인 아님 |
| multiple_testing / 새제안+미확인 | 후보44 history와1selected/one independent bundle 보존. / alpha_family=.05;7one-sided claims;alpha_claim=.007142857. | 7claim family 유지 여부 별도 승인. 3windowmean과4pairedcontrol superiority의 sigma/추정량 구분. 과거44시도를 초기화하거나 oldp값을 새independent결과로 쓰지 않음. singlewindowcandidate 분산은 pooledcontrolcontrast 분산이 아님. 지금pairedcontrol N 산출 근거 부족. | probability;7claims;one fixed terminallook / APPROVAL_BUNDLE multiple_testing; design required_n | multiplicity and historical-selection protocol authority / 새control DEV기능결과로 독립표본 예산차감/credit 금지 |
| controls_neighbors / 수정권고+미확인 | P4 네control 및 neighbor6개+필수ablation 필요;새후보선택 금지. / direction_flip/full-directionmirror,+24h placebo,+1observedbar delay,regime permutation seed1178;6EMA/HOLDneighbors. | samecalendar component contribution contrasts와 각각 actualFULL을 사용. 없는거래를0returntrade로 생성금지. KR3에는regimeentryfilter없어 label rotation은DEGENERATE; formal superiority용 permutation으로 승인비권고. 방향/지연 fixture semantics delta를 exact code와 다시 결속한 최종inactive contract 필요. S2 native end-to-end fixture 구현과 유효control설계승인은 별개. 미래window signal목록을 shuffle하여앞당기기 금지. HOLD변경은cap2HOLD/판단HOLD-1/reference전파. | 4controls,6neighbors;fixedsource/cost/exposurecalendar / CONTRACT/PARAMETER_INVENTORY.json; S2 step7 economic producer; AUTHORITY original proposal | 구체적control direction/invalidation/timestamp/estimand/degenerate해결 승인 / 추가전략탐색 아님;유효control결손은formal gate차단 |
| source_stale / 새제안+미확인 | event/receive availability와signed funding/unknown을 그대로 유지. / 4h publication<=60s;BBO age<=2s;receive<=1s;RTT<=2s;clockuncertainty<=500ms. | 이번한시source시험에서는 실제metadata로각조건 가능성을측정하고 formal 숫자는미활성. exactseed warmup·늦은관측경로입증 후 timingcontract 별도. formal retention>=90+7+승인review/audit days 필요. 기존90d보존은90dG5A+7d최대runoff 대비최소7d부족하며검토기간추가. 향후3개G5B창도별도source/예산. | ms; retention calendar days;추가batch<=24h/2000GET/1GiB / step7 source/sequence owner; existing SOURCE/RUN_RECEIPT metadata | staleness/timing/retention/sourcehost capacity authority / 한시source 자료 formal0; 원본raw를 개발자가해독하지 않음 |
| concentration_operating_risk / 새제안+미확인 | 원래7symbols 각1actualslot;account sizing없음. / >=2symbols;one symbol<=50% positiveprofit;largestwinner remove aggregate>0. | 새formal absolute기준으로조용히추가하지말고승인필수. 먼저집중위험진단으로report;승인시통과문턱원형유지. trade나symbol을결과후제외하지않음. 경제양수여도집중으로reject가능. 기사용DEV의승패/수익표재합산은이번통계목적외라반복안함. | symbols;50%profit contribution;trade-bps,actual/reference occupied time / APPROVAL_BUNDLE concentration_operating_risk; nativeFULL occupancyowner | 새집중gate authority;noorders / 미래자금/lev위험예측으로해석금지 |
| existing_economic_integrity_gates / 기존 확정 | shared SHA bf596d0f… G5ApositiveE/PF>1/cost2>0+9reports;G5BNetR>0/PF>=1/E>0/payoff>=1/retention>=60/errors0/duplicate0/open0/unknown0. / 기존숫자 byte동일binding. | 유지. 새설계미달을문서/코드PASS로우회금지. G5A후새G5Bboundary별도. G5A평가자료는G5Bfresh로중복인정불가.기존KR3TRADEOFF유지. | 기존contract단위 / g5b_operational_terminal_v1.freeze_boundary; g5_g14_shared_validation_contract_v1.json | 현재구현승인은독립읽기/G5B등록/실주문권한아님 / formaldata credit0;독립bundle0/1 보존 |

## 최종 사용자 결정문 1개

> 원안 b6d45358…의 정식 가동은 승인하지 않는다. KR3 FULL 원형과 기존 경제 기준을 유지하고, 무보호SL 비주문 cohort 적용권한·statistical_atr_r와 risk_R/net_r의 구분·추정량과 검정력·유효표본·달력 및 비용의 수정 명세를 정식 승인 선행조건으로 확정한다. 독립자료 접근·G5B 등록·실주문은 계속 차단한다.

이 문구는 권고 초안이며 실제 사용자 승인으로 기록하지 않았다. P1 인증 경로를 통과한 실제 권한 증거 없이는 APPROVED_RECEIPT를 만들지 않는다. 원안 봉인 `b6d453587b6899c0fbf3a19530e6c9b4f0609266f51a302375330a1ebea04132`을 보존했고 본 수정권고는 별도 비활성 봉인이다.

기존 노출 metadata에는 적격 미사용 historical 검증 manifest가 확인되지 않는다. independent exposure 목록이 빈 것은 미사용 역사자료가 있다는 증거가 아니다. 별도 적격 manifest/접근승인이 나오지 않는 한 prospective가 필요하다. 이번/기존 원천 raw는 열지 않았다.

기존90일 source artifact 보존은 G5A90일+최대runoff7일의 최소97일에도7일 부족하다. 실제 정식 보존은 **97일+승인된 검토/감사기간 이상**이어야 하고, source owner가 기존자원/가격으로 지원함을 확인해야 한다. 이는 신규유료자원 승인이나 이번24시간 연결시험 자동연장이 아니다. 이후 새G5B 창은 시간·자료를 다시 필요로 한다.

## 실행 기록

```sh
python -m unittest backend.research.rebuild.test_step7_design_feasibility_v1 -v
python -m backend.research.rebuild.step7_design_feasibility_v1 --freeze research/development_evidence/ZEL_PARENT_CLOSURE_TO_G5_SURVIVOR/EXECUTION_PATH/DESIGN/DEV_ANALYSIS_FREEZE.json --projection research/development_evidence/ZEL_PARENT_CLOSURE_TO_G5_SURVIVOR/EXECUTION_PATH/DESIGN/DEV_PROJECTION.json --output research/development_evidence/ZEL_PARENT_CLOSURE_TO_G5_SURVIVOR/EXECUTION_PATH/DESIGN/FEASIBILITY_RESULT.json
```

합성 시험5개 PASS. 기존 DEV 계산1회, 경제재생0, sealed/current raw 읽기0, API0, 신규후보0. 위 DEV 명령은 완료됐으므로 CI에서 재실행하지 않는다. 출력 봉인 a840eb3e787a012a9c6f2547a439dd372bcd59ff2220bc0060d2373dbed53625.
