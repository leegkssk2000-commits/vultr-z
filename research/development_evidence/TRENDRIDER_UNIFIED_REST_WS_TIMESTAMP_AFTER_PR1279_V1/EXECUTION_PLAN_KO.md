# Issue1280 REST↔WS 시각 검증과 조건부 common replay

이 문서는 실제 WS/REST 응답과 경제 결과 전에 작성했다. 이전 PR1279의 차단은 경제 실패가 아니며, 이번 Issue1280은 별도의 session1·WS subscribe1·REST max2를 승인한다. root가 실제 네트워크·수집·경제 실행 및 예산의 단일 담당자다.

## 결과 전 고정

- 기존 코드·증거 108개 파일 SHA를 보존한다. PR1275 경제 계약 16개 구획의 canonical bytes를 그대로 유지한다. 기존 실패 결과를 덮어쓰거나 재실행하지 않는다.
- BingX 공식 WS 시작/종료 필드와 REST 배열 문서, CCXT 보조 구현을 고정 commit/blob/UTF8 SHA로 결속한다. 문서나 CCXT만으로 object time을 승인하지 않는다.
- 새 WS/REST 모듈과 합성 시험·protocol·이 문서·계약·출처를 원격 commit으로 봉인하고 다시 읽은 뒤 단일 calibration을 시작한다. 승인 경로와 외부 출처 파일의 변경을 실제 I/O 직전 다시 검사한다.

## 단일 시각 검증 세션

BTC-USDT@kline_1h를 공식 Swap WS에 한 번 구독한다. 단일 연결 시도이며 자동 redirect·재접속·transport retry는 0이다. session 최대180초, REST 최대2회다. GZIP 원문을 해제하기 전에 저장하며, REST 요청·상태·헤더·원문도 JSON 해석 전에 저장한다. application Ping 응답 Pong은 구독 수와 구분한다.

첫 유효한 현재 또는 직전 1시간 candle을 target으로 고정한다. 공식 dataType과 data.s로 symbol/interval을 확인하고 K.t/K.T와 OHLCV를 읽는다. 첫 REST는 해당 hour의 최소 범위를 즉시 요청한다. WS는 REST 처리 중에도 계속 수신한다. 같은 세션에서 정확한 Decimal OHLC 일치가 관측되지 않은 경우에만 첫 REST 시작60초 후 두 번째 요청을 허용한다. 근사값·가격 연속성·임의 ±1시간 보정은 사용하지 않는다.

REST object의 time==WS K.t, 정확한 OHLC, 동일 symbol/interval/candle이 함께 확인돼야 PASS다. array는 [0]==K.t와 [6]==K.T를 직접 확인한다. 불확실성 또는 연결·형식·시각 오류는 BLOCKED_REST_WS_TIMESTAMP_WITNESS로 끝내고 source와 경제 실행을 하지 않는다. 구체적인 원문과 예산 소비를 모두 보존한다.

## PASS 이후에만

실제 semantic PASS 영수증과 source authorization을 원격에 다시 봉인한다. source V4로 BTC/ETH 1시간 자료를 각 exact1000, 2026-07-19 08:00부터08-29 23:00 UTC까지 한 번 수집한다. cutoff는08-30 00:00 UTC다. backward pagination 최대3pages/symbol, retry0이며 guard를 경제 입력에서 격리한다. 누락·중복·오류 0, 두 symbol clock이 정확히 같아야 DATA_FREEZE_V4를 만든다. 수집 후 창 변경·refetch는 금지한다.

정규화 SHA와 실행 코드·계약을 원격 봉인한 뒤에만 경제 평가를 시작한다. controls는 B/P×DEV_A/B 최대4회이고 저장 결과를 재사용한다. G1~G6의 DEV_A screen 최대6회 후 기존 hard gates와 Pareto로 최대2개를 선택해 원격 고정한다. 고정된 gene만 DEV_B 최대2회 확인한다. 생존자가 없으면 NO_CAUSAL_UNIFIED_GENE_COMMON_REPLAY로 끝내며 rescue는 없다.

생존자가 있으면 U1, 필요할 때만 동결된 orthogonal AND U2를 실행한다. 최대2후보·child FULL4회다. 두 partition 모두 기존 순손익·expectancy·PF·payoff·cost2·무결성·승리 보존 게이트와 Pareto를 적용한다. Unified 성공에만 정확한 전략 봉인과 새 미래 G5A boundary를 부여한다. 모든 common history는 USED_DEV, formal credit0이며 prospective 자료를 해석하지 않는다.

## 종료

실측 결과와 N/A를 구분해 경제표·donor attribution·실행 횟수·원문 SHA를 보고한다. 테스트·읽기 전용 CI·자동 리뷰·정상 PR 병합·정확한 merge SHA 검증과 영수증 기록까지 수행한다. 배포·주문·live·유료 AI·Squeeze 자료 접근·자동 미세튜닝 successor는 모두0이다. 이번 범위의 terminal 결과를 보고하고 REPORT_ONLY로 종료한다.
