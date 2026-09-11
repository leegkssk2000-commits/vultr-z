TrendRider Unified v1 = 생성안됨

ACK 수선은 실제 PASS. 두 번째 kline 채널 frame이 frozen decoder의 nested schema와 달라 `BLOCKED_REST_WS_TIMESTAMP_WITNESS`로 종료했다. 경제평가를 수행하지 않았으므로 전략의 경제 실패·G1~G6 탈락으로 판정하지 않는다.

| 단계 | 결과 | 근거 |
|---|---|---|
| ACK regression | PASS | ACK51 + source39 = 90 tests; deferred owner30 별도 PASS |
| 실제 ACK | PASS | {id:expected,code:0,msg:"",dataType:"",data:null} 정상 소비 |
| ACK→kline chronology | PASS 수신 | ACK `2026-09-11T19:46:57.568Z` → kline 채널 frame `2026-09-11T19:46:57.958Z` |
| canonical kline 해석 | FAIL | 실제 root.s + data[0].T; frozen data.s + data.K.t/K.T 없음 |
| REST↔WS timestamp | 미검증 | REST 0회, witness null; T 의미를 추정하지 않음 |
| BTC/ETH exact1000·SHA·DEV_A/B | NOT_RUN | calibration 전제조건 미충족 |
| G1~G6 survivor | NOT_EVALUATED | Stage0/Stage1 미실행 |
| U1/U2 | 생성안됨 | 후보·FULL 0회 |

원문 수신 chronology는 성공 ACK 이후 대기를 계속했다는 증거다. kline 채널 frame 수신 1개와 canonical kline 인정 0개를 구분한다. 실제 2번 frame의 구조는 다음과 같다. 이 frame의 가격·거래량은 calibration raw에만 보존하며 경제 입력으로 사용하지 않았다.

```json
{"code":0,"dataType":"BTC-USDT@kline_1h","s":"BTC-USDT","data":[{"c":"...","o":"...","h":"...","l":"...","v":"...","T":1789153200000}]}
```

| 구간 | 전략 | eligible/completed/open T | WR % | net bps | expectancy bps/T | PF | payoff | cost2 net bps | DD bps | loss-tail bps | exposure |
|---|---|---|---|---|---|---|---|---|---|---|---|
| DEV_A | P_COMMON | NOT_RUN | — | — | — | — | — | — | — | — | — |
| DEV_A | B_COMMON | NOT_RUN | — | — | — | — | — | — | — | — | — |
| DEV_A | U1 | NOT_RUN | — | — | — | — | — | — | — | — | — |
| DEV_A | U2 | NOT_RUN | — | — | — | — | — | — | — | — | — |
| DEV_B | P_COMMON | NOT_RUN | — | — | — | — | — | — | — | — | — |
| DEV_B | B_COMMON | NOT_RUN | — | — | — | — | — | — | — | — | — |
| DEV_B | U1 | NOT_RUN | — | — | — | — | — | — | — | — | — |
| DEV_B | U2 | NOT_RUN | — | — | — | — | — | — | — | — | — |

미실행 지표를 0으로 표시하지 않는다. 평균 이익·손실·최악손실·conflict·top1·overlap/P-only/B-only·feature/intent lineage·ordinary/top10 winner retention도 전부 NOT_RUN이다. Donor attribution은 공통 신호·원장 미생성으로 NOT_RUN이다.

실행 예산: WS 1 / subscribe 1 / ACK 1 / kline 채널 frame 1 / canonical kline 0 / REST 0 / historical source 0 / controls 0 / DEV_A screens 0 / DEV_B confirmations 0 / candidate 0 / FULL 0. retry·sweep·prospective decode·paid AI·live·order·deploy 모두 0.

기존 실패 decoder와 PR1272~1281 증거 149파일·경제계약16항목은 보존했다. 새 v2는 ACK 처리만 바꾸며, source v5는 새 semantic receipt 연결과 사용자가 요구한 완료봉 검증만 추가했다. 이번 실행은 완료봉 gate 이전의 schema 계약 불일치에서 끝났다. 동결 이후 실행코드 수선·재접속·자동 successor는 수행하지 않았다.

Prospective G5A handoff 없음. common replay formal credit 0. Unified seal 없음. G5B terminal PASS 전 G6 권한 없음.

CI·독립 리뷰·정상 PR 병합·고정 병합본 검증 결과는 EXACT_MERGE_VERIFICATION.json에 결속한다. 배포는 실행하지 않는다. 연구 파일만 추가했으므로 rollback은 해당 PR revert이며 live/order 상태 변경은 없다.
