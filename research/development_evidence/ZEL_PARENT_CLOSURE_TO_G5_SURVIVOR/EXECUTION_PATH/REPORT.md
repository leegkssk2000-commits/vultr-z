# STEP7 PR1209 후속 실제 실행 결과

후속 구현·시험·한정 원천 연결·PR1210/고정 merge 재현 완료. REPORT_ONLY로 종료하며 경제 캠페인은 미완료다.

승인 인증 P1은 실제 production CLI→외부 인증→영속 조회예약→sealed read→producer 경로에서 수선했다. 호출자가 만든 승인객체+해시나 principal=USER 문자열만으로 접근하지 못한다. 독립 관리된 고정 trust anchor의 Ed25519 서명, 실행 UID, 정확한 scope/candidate/code/config/design/source/cost/범위/예산 결속을 요구한다. 위조·다른권한자·만료/철회·재사용·취소·production fixture 반례가 차단된다. 실제 CLI 결과는 BLOCKED_TRUST_ANCHOR_MISSING, sealed read0/dispatch0/독립예산0이다. 정상 승인 시험은 합성 fixture이며 실제 사용자 승인으로 사용하지 않았다. 신뢰키/독립 validator 배포는 미구축이다.

실제 실행한 통합 명령:

    python -m backend.research.rebuild.step7_kr3_execution_v1 --fixture --out-dir out/step7-path-integration

native raw→feature→KR3/KR1 각각 FULL 점유→청산→거래/비용→9종 보고서→바이트 소비 검증이 실행됐다. 합성 closed56/reference56/events56/trace168,6neighbors·4controls·4ablations가 실제 코드를 통과했다. 새 경제성과나 Survivor가 아니다. BUNDLE SHA483b978fc3990dd8cf0c3c8e8a4b9789af4eeecec1bbfe7178fc7d285ba3a307, 압축원본과9종별SHA를보존했다.

| 생산기 | 합성 native 실행 | 실제 독립 경제검증 |
|---|---|---|
| base_replay | 완료: KR3·KR1 각 FULL | 미실행 |
| realistic_cost | 완료: 기준가차·fee/spread/impact/signed funding·누락전파 | 미실행 |
| cost2x | 완료: closed/open/terminal 분리 | 미실행 |
| purged_oos | 완료: 실제/참조 overlap·embargo·미완결 | 미실행 |
| chronological_split | 완료: 창에서 점유초기화없음 | 미실행 |
| symbol_decomposition | 완료: 원래7종목 | 미실행 |
| regime_decomposition | 완료: 인과적 label | 미실행 |
| parameter_neighbor_stability | 완료:6개 EMA/HOLD·cap·참조예약전파 | 미실행 |
| negative_controls | 완료:4controls·4ablations. regime-label permutation은 경제효과0의퇴화대조군으로표시 | 미실행 |

생산기·실행명령 없음은 해소했다. 정식 비용/시각 미결과 유효control 결손은 남았다. quote-mid/native model 기준가차를 별도 비용항으로 기록하고, 필수 호가/펀딩/시각/비용이 없으면 null·이유를 유지한다. 부모 미확정 비용·미완결을 버려 retention/PnL을 양수로 만들지 않는다. 초기SL/TP=None, KR3규칙/TRADEOFF를 보존했다.

실제 source 추가배치: run34158767327/job101856080695, ownerSTEP7_SOURCE_SEQUENCE_ACTIONS, hostrunnervmejwal. 시장GET35+GitHubmetadataGET1=HTTP36, 원시수신321634bytes. 2026-09-07T20:16:52.664Z 시작→20:17:27.579Z 정상종료, 자동상한20:19:52.664Z. 승인최대24h/2000HTTP/1GiB 안에서 선택한180s/35marketGET 한배치다. 자동연장·재시도없음.

7종목 각 완료4h399봉을 수신했고 depth cursor는각3회수신에서2회실제전진했다. native완료cursor는모두1788811200000(2026-09-07T20:00:00Z). prefix native reference36건은 이미완료된종가구간의계산결과이며 새거래/G5freshT가아니다. 3회직렬화재시작 stateSHA9ac47f92… 동일, 이후new_signal_count0. 원본·native state는 별도source artifact에만보존했고 개발자는가격/성과를열지않았다.

미관측: 배치시작후 신규4h봉진행0, 실제진입/청산0. depth진행은 전체호가stream 연속성이나 새4h봉경계 실제주문/체결 증거가아니다. 완전한formal source/cost준비는false다. source배치는종료됐으며 Work소유실행·대기없음.

Source artifact10031887621,91994bytesZIP, sha256:a38e1e1826658b18765bef908230b1368f8347c2b2fb9de62c8b9257860de55d, 만료2026-12-06T20:16:19Z. 90일은 한시적비정식연결증거 보존이며, 향후90d평가+7dRunoff+검토기간 충족을주장하지않는다.

승인안 권고: 원안b6d45358…11항의 일괄가동은 비권고. 기존DEV375일/203행을1회만분석하여 실제+참조+UTC일구성요소37개(완료36/검열1), 최대35거래묶음, sigma352.3722net-bps/구성요소평균을구했다. 30일당완료component평균2.88개, 관측0~5개다. alpha.05/7/power80%, H0<=5/H1=10의5bps효과차에 필요한계획N은각창53813개다. lower>5판정을쓰면서실제평균5에서80%power를요구하면유한N이없다. 계산을새gate로활성화하거나결과에맞춰문턱을완화하지않았다.

공유계약은net_r>0을요구하지만 보호SL존재/위험R분모를직접정의하지않는다. noSL영구부적격으로단정하지않고noSL정식비주문적용/NetR의미미결로기록했다. statistical_atr_r는risk_R/net_r를대체하지않는다. regime진입필터가없는KR3의label-permutation도유효경제대조군으로사용할수없다. 11행delta/단위/owner/권한/자료·달력·비용 영향은DESIGN/FINAL_RECOMMENDATION.md에있다.

권고 결정문(사용자승인으로기록하지않음): 원안11항의 정식가동은보류한다. KR3원형·기존경제기준을유지하고noSL/NetR·추정량/검정력/표본·달력·대조군·비용의 수정명세를정식승인선행조건으로확정한다. 독립자료접근·G5B등록·실주문은계속차단한다.

검증: PR1210 finalhead2c4c43841dc583aeedb6506481c57328741e94b6, 관련CI8개success, 자체run34158647888 신규42시험과9종동일hash재현PASS. merge409a440d935641403f8456dd6d166e3c33825b1e의masterrun34158767327completed/success(20:17:31Z). 이후별도collector master갱신은재검증하지않았다. PR1209시험39·전체성적·1469감사·22GET은재실행하지않았다.

S1 인증/13시험, S2 native9생산/10시험, S3 source/11시험, S4 DEV설계/5시험, Root dispatch3시험·직렬통합·공유원장·CI를반영했다. 전원종료. 정식독립검증자는이개발담당자를이름만바꿔배정할수없다.

후보44·신규0, 독립0/1, 기존source1/1+추가source1/1소비, 누적시장HTTP57. Gemini0/OpenAI0, 공유USD5중사용/예약$0/$0. Q0/G5B·기존수집·다른Work보존. 제품배포/실주문/자동승격없음. 변경범위는허가된backend/newtests/캠페인증거/해당workflow다. frontend사전·사후validatePASS, 배포실행불필요. 롤백시예산·노출이력·수집기록을초기화하면안된다.

세션COMPLETED_REPORT_ONLY / 구현·한정데이터연결완료(정식source부분) / 경제캠페인BLOCKED. G5Aqualifiedfalse, 신규G5Bboundary0/freshT0/terminalPASS0. 후속필수실행[]; 캠페인미결W3/W4는HANDOFF.json에별도보존했다.
